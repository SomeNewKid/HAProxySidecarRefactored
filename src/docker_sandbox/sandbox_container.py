"""Run Sandbox Agent inside disposable Docker containers."""

from __future__ import annotations

import datetime as dt
import json
import shlex
import shutil
import threading
import time
from collections.abc import Mapping, Set
from pathlib import Path, PurePosixPath
from typing import IO, Any, TextIO

from .agent_container import run as agent_run
from .models import (
    AgentSocketForward,
    BrowserDebuggingProfile,
    BrowserSurfaceProfile,
    DockerConfiguration,
    DockerRunResult,
    EnvironmentVariablePolicy,
    HAProxyConfiguration,
    NetworkDnsPolicy,
    SandboxRunTarget,
    SeccompProfile,
    SocketMount,
)
from .orchestration import wiring
from .orchestration.artifacts import write_json_artifact
from .orchestration.docker import build_docker_remove_command
from .orchestration.types import CommandResult, RunContext
from .sidecars import code_execution, haproxy, jina_reader, mcp, ollama, squid_gateway

_DOCKER_EXECUTABLE = "docker"
_REMOTE_OUTPUT_DIRECTORY = agent_run.REMOTE_OUTPUT_DIRECTORY
_REMOTE_LANDLOCK_POLICY_PATH = agent_run.REMOTE_LANDLOCK_POLICY_PATH
_REMOTE_SOURCE_DIRECTORY = agent_run.REMOTE_SOURCE_DIRECTORY
_CONTAINER_NAME_PREFIX = "sandbox-agent-run"
_NETWORK_NAME_PREFIX = "sandbox-agent-net"
_READONLY_DENIED_SOURCE_DIRECTORY = agent_run.READONLY_DENIED_SOURCE_DIRECTORY
_SECCOMP_PROFILE_FILE_NAME = agent_run.SECCOMP_PROFILE_FILE_NAME
_DENIED_EXECUTABLE_SOURCE_DIRECTORY = agent_run.DENIED_EXECUTABLE_SOURCE_DIRECTORY
_READONLY_PERSISTENCE_SOURCE_DIRECTORY = agent_run.READONLY_PERSISTENCE_SOURCE_DIRECTORY
_DESKTOP_AUTOMATION_ENVIRONMENT_NAMES = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
)
_DESKTOP_AUTOMATION_EXECUTABLE_PATHS = (
    "/usr/bin/busctl",
    "/usr/bin/dbus-send",
    "/usr/bin/gdbus",
    "/usr/bin/qdbus",
    "/usr/bin/wmctrl",
    "/usr/bin/xdotool",
)
_ALLOWED_FILE_CONTENT = agent_run.ALLOWED_FILE_CONTENT
_DENIED_FILE_CONTENT = agent_run.DENIED_FILE_CONTENT
_HIDDEN_ALLOWED_FILE_CONTENT = agent_run.HIDDEN_ALLOWED_FILE_CONTENT
_HIDDEN_DENIED_FILE_CONTENT = agent_run.HIDDEN_DENIED_FILE_CONTENT
_GIT_REMOTE_URL = agent_run.GIT_REMOTE_URL
_LOCAL_ENVIRONMENT_VALUE = agent_run.LOCAL_ENVIRONMENT_VALUE
_SANDBOX_TESTER_ENVIRONMENT_VARIABLES = {
    "OPENAI_API_KEY": _LOCAL_ENVIRONMENT_VALUE,
}
_OPENAI_API_KEY_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"
_TIME_MODULE_FOR_TEST_COMPATIBILITY = time


def run_sandbox_container(
    configuration: DockerConfiguration,
    verbose: bool = False,
    serialize_evidence: bool = False,
) -> DockerRunResult:
    """Run Sandbox Agent in a disposable Docker container."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    run_context = _build_run_context(configuration, timestamp)
    run_directory = run_context.run_directory
    run_directory.mkdir(parents=True, exist_ok=True)
    _write_configuration_artifacts(configuration, run_context.run_directory)
    container_name = run_context.container_name
    network_name = run_context.network_name
    gateway_container_name = run_context.gateway_container_name
    mcp_sidecar_container_name = run_context.mcp_sidecar_container_name
    jina_reader_container_name = run_context.jina_reader_container_name
    code_sidecar_container_name = run_context.code_sidecar_container_name
    haproxy_sidecar_container_name = run_context.haproxy_sidecar_container_name
    ollama_sidecar_container_name = run_context.ollama_sidecar_container_name
    remote_run_directory = run_context.remote_run_directory
    allowed_directory = run_context.allowed_directory
    denied_directory = run_context.denied_directory
    _prepare_readonly_denied_directory(configuration, run_directory)
    _prepare_readonly_persistence_directories(configuration, run_directory)
    _prepare_denied_executable_stubs(configuration, run_directory)
    _write_landlock_policy(configuration, run_directory)
    _write_seccomp_profile(configuration, run_directory)
    config_data = _build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        configuration.guest_user,
        _get_container_ssh_agent_socket(configuration),
        configuration.profile.browser_debugging,
        configuration.profile.browser_surface,
    )
    _write_squid_configuration(configuration, run_directory, config_data)
    _write_mcp_sidecar_exposure(configuration, run_directory)
    _write_haproxy_configuration(configuration, run_directory)
    config_path = run_directory / "config.json"
    write_json_artifact(config_path, config_data)
    configured_environment_variables = dict(configuration.environment_variables)
    environment_variables = _resolve_environment_variables(
        configured_environment_variables,
    )
    gateway_commands = None
    gateway_ip_address = None
    jina_reader_commands = None
    code_sidecar_commands = None
    haproxy_sidecar_commands = None
    ollama_sidecar_commands = None
    mcp_sidecar_commands = None
    for sidecar_name in wiring.ordered_sidecars(configuration):
        if sidecar_name == wiring.SQUID_GATEWAY:
            gateway_commands, gateway_ip_address = _start_network_gateway(
                configuration,
                run_directory,
                network_name,
                gateway_container_name,
            )
        elif sidecar_name == wiring.JINA_READER:
            jina_reader_commands = _start_jina_reader(
                configuration,
                run_directory,
                network_name,
                jina_reader_container_name,
            )
            _wait_for_jina_reader_ready(
                configuration,
                run_directory,
                network_name,
                jina_reader_container_name,
            )
        elif sidecar_name == wiring.CODE_EXECUTION:
            code_sidecar_commands = _start_code_sidecar(
                configuration,
                run_directory,
                network_name,
                code_sidecar_container_name,
            )
            _wait_for_code_sidecar_ready(
                configuration,
                run_directory,
                network_name,
                code_sidecar_container_name,
            )
        elif sidecar_name == wiring.HAPROXY:
            haproxy_sidecar_commands = _start_haproxy_sidecar(
                configuration,
                run_directory,
                network_name,
                haproxy_sidecar_container_name,
            )
            _wait_for_haproxy_sidecar_ready(
                configuration,
                run_directory,
                haproxy_sidecar_container_name,
            )
        elif sidecar_name == wiring.OLLAMA:
            ollama_sidecar_commands = _start_ollama_sidecar(
                configuration,
                run_directory,
                network_name,
                ollama_sidecar_container_name,
            )
            _wait_for_ollama_sidecar_ready(
                configuration,
                run_directory,
                network_name,
                ollama_sidecar_container_name,
            )
        elif sidecar_name == wiring.MCP:
            mcp_sidecar_commands = _start_mcp_sidecar(
                configuration,
                run_directory,
                network_name,
                mcp_sidecar_container_name,
            )
            _wait_for_mcp_sidecar_ready(
                configuration,
                run_directory,
                network_name,
                mcp_sidecar_container_name,
            )
    command = _build_docker_run_command(
        configuration=configuration,
        run_directory=run_directory,
        container_name=container_name,
        network_name=network_name,
        remote_run_directory=remote_run_directory,
        allowed_directory=allowed_directory,
        denied_directory=denied_directory,
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=configuration.local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
    )
    completed = _run_interactive_command(command)
    _write_mcp_sidecar_logs(configuration, run_directory, mcp_sidecar_container_name)
    _write_jina_reader_logs(configuration, run_directory, jina_reader_container_name)
    _write_code_sidecar_logs(configuration, run_directory, code_sidecar_container_name)
    _write_haproxy_sidecar_logs(
        configuration,
        run_directory,
        haproxy_sidecar_container_name,
    )
    _write_ollama_sidecar_logs(
        configuration,
        run_directory,
        ollama_sidecar_container_name,
    )
    _write_gateway_logs(configuration, run_directory, gateway_container_name)
    _delete_readonly_denied_directory(configuration, run_directory)
    _delete_readonly_persistence_directory(configuration, run_directory)
    _delete_denied_executable_directory(configuration, run_directory)
    remove_command = build_docker_remove_command(container_name, _DOCKER_EXECUTABLE)
    gateway_cleanup_commands = _build_gateway_cleanup_commands(
        configuration,
        network_name,
        gateway_container_name,
    )
    mcp_sidecar_cleanup_commands = _build_mcp_sidecar_cleanup_commands(
        configuration,
        mcp_sidecar_container_name,
    )
    jina_reader_cleanup_commands = _build_jina_reader_cleanup_commands(
        configuration,
        jina_reader_container_name,
    )
    code_sidecar_cleanup_commands = _build_code_sidecar_cleanup_commands(
        configuration,
        code_sidecar_container_name,
    )
    haproxy_sidecar_cleanup_commands = _build_haproxy_sidecar_cleanup_commands(
        configuration,
        haproxy_sidecar_container_name,
    )
    ollama_sidecar_cleanup_commands = _build_ollama_sidecar_cleanup_commands(
        configuration,
        ollama_sidecar_container_name,
    )

    return DockerRunResult(
        image_name=configuration.profile.image_name,
        profile_name=configuration.profile.name,
        container_name=container_name,
        run_directory=run_directory,
        command=command,
        remove_command=remove_command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        network_name=network_name,
        gateway_container_name=gateway_container_name,
        gateway_ip_address=gateway_ip_address,
        gateway_commands=gateway_commands,
        gateway_cleanup_commands=gateway_cleanup_commands,
        mcp_sidecar_container_name=mcp_sidecar_container_name,
        mcp_sidecar_commands=mcp_sidecar_commands,
        mcp_sidecar_cleanup_commands=mcp_sidecar_cleanup_commands,
        jina_reader_container_name=jina_reader_container_name,
        jina_reader_commands=jina_reader_commands,
        jina_reader_cleanup_commands=jina_reader_cleanup_commands,
        code_sidecar_container_name=code_sidecar_container_name,
        code_sidecar_commands=code_sidecar_commands,
        code_sidecar_cleanup_commands=code_sidecar_cleanup_commands,
        haproxy_sidecar_container_name=haproxy_sidecar_container_name,
        haproxy_sidecar_commands=haproxy_sidecar_commands,
        haproxy_sidecar_cleanup_commands=haproxy_sidecar_cleanup_commands,
        ollama_sidecar_container_name=ollama_sidecar_container_name,
        ollama_sidecar_commands=ollama_sidecar_commands,
        ollama_sidecar_cleanup_commands=ollama_sidecar_cleanup_commands,
    )


def _build_run_context(
    configuration: DockerConfiguration,
    timestamp: str,
) -> RunContext:
    run_id = f"run-{timestamp}"
    run_directory = configuration.base_directory / "runs" / run_id
    remote_run_directory = _build_remote_run_directory(configuration, run_id)
    return RunContext(
        timestamp=timestamp,
        run_id=run_id,
        run_directory=run_directory,
        container_name=f"{_CONTAINER_NAME_PREFIX}-{timestamp}",
        remote_run_directory=remote_run_directory,
        allowed_directory=_build_allowed_directory(configuration, remote_run_directory),
        denied_directory=_build_denied_directory(configuration, remote_run_directory),
        network_name=_build_network_name(configuration, timestamp),
        gateway_container_name=_build_gateway_container_name(
            configuration,
            timestamp,
        ),
        mcp_sidecar_container_name=_build_mcp_sidecar_container_name(
            configuration,
            timestamp,
        ),
        jina_reader_container_name=_build_jina_reader_container_name(
            configuration,
            timestamp,
        ),
        code_sidecar_container_name=_build_code_sidecar_container_name(
            configuration,
            timestamp,
        ),
        haproxy_sidecar_container_name=_build_haproxy_sidecar_container_name(
            configuration,
            timestamp,
        ),
        ollama_sidecar_container_name=_build_ollama_sidecar_container_name(
            configuration,
            timestamp,
        ),
    )


def _write_configuration_artifacts(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.generated_dockerfile is not None:
        dockerfile_text = configuration.generated_dockerfile.rstrip()
        (run_directory / "Dockerfile").write_text(
            f"{dockerfile_text}\n",
            encoding="utf-8",
        )

    if configuration.resolved_spec is not None:
        write_json_artifact(
            run_directory / "sandbox-spec.json", configuration.resolved_spec
        )

    write_json_artifact(run_directory / "resolved-profile.json", configuration.profile)


def _build_remote_run_directory(
    configuration: DockerConfiguration,
    run_id: str,
) -> str:
    remote_root = configuration.profile.remote_run_root.rstrip("/")
    return f"{remote_root}/{run_id}"


def _build_gateway_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    return squid_gateway.build_container_name(configuration, timestamp)


def _build_mcp_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if not _should_start_mcp_sidecar(configuration):
        return None

    return mcp.build_container_name(timestamp)


def _build_jina_reader_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    return jina_reader.build_container_name(configuration, timestamp)


def _build_code_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    return code_execution.build_container_name(configuration, timestamp)


def _build_haproxy_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    return haproxy.build_container_name(configuration, timestamp)


def _build_ollama_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    return ollama.build_container_name(configuration, timestamp)


def _build_network_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if configuration.profile.network_gateway is None:
        return None

    return f"{_NETWORK_NAME_PREFIX}-{timestamp}"


def _build_allowed_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    return agent_run.build_allowed_directory(configuration, remote_run_directory)


def _build_denied_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    return agent_run.build_denied_directory(configuration, remote_run_directory)


def _format_directory_template(template: str, remote_run_directory: str) -> str:
    return agent_run.format_directory_template(template, remote_run_directory)


def _prepare_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_child_directory = (
        run_directory / _READONLY_DENIED_SOURCE_DIRECTORY / "denied"
    )
    denied_child_directory.mkdir(parents=True, exist_ok=True)
    denied_file = denied_child_directory / "denied.txt"
    denied_file.write_text(_DENIED_FILE_CONTENT, encoding="utf-8")
    hidden_file = denied_child_directory / ".hidden"
    hidden_file.write_text(_HIDDEN_DENIED_FILE_CONTENT, encoding="utf-8")


def _prepare_readonly_persistence_directories(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    for target in configuration.profile.readonly_persistence_directories:
        _validate_container_directory(target)
        source_directory = _build_readonly_persistence_source_directory(
            run_directory,
            target,
        )
        source_directory.mkdir(parents=True, exist_ok=True)


def _prepare_denied_executable_stubs(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    denied_targets = _get_denied_executable_targets(configuration)
    if not denied_targets:
        return

    stub_directory = run_directory / _DENIED_EXECUTABLE_SOURCE_DIRECTORY
    stub_directory.mkdir(parents=True, exist_ok=True)
    for target_path in denied_targets:
        stub_path = stub_directory / _build_denied_executable_stub_name(target_path)
        stub_path.write_text(
            _build_denied_executable_stub_text(PurePosixPath(target_path).name),
            encoding="utf-8",
        )
        stub_path.chmod(0o755)


def _build_denied_executable_stub_text(executable_name: str) -> str:
    return (
        "#!/bin/sh\n"
        f"echo {shlex.quote(executable_name)}: denied by sandbox profile >&2\n"
        "exit 127\n"
    )


def _validate_executable_name(executable_name: str) -> None:
    agent_run.validate_executable_name(executable_name)


def _validate_executable_path(executable_path: str) -> None:
    agent_run.validate_executable_path(executable_path)


def _validate_container_directory(directory: str) -> None:
    agent_run.validate_container_directory(directory)


def _build_denied_executable_stub_name(target_path: str) -> str:
    return agent_run.build_denied_executable_stub_name(target_path)


def _build_readonly_persistence_source_directory(
    run_directory: Path,
    target: str,
) -> Path:
    return agent_run.build_readonly_persistence_source_directory(run_directory, target)


def _get_denied_executable_targets(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    return agent_run.get_denied_executable_targets(configuration)


def _write_landlock_policy(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.landlock_rules:
        return

    policy = {
        "rules": [
            {
                "path": rule.path,
                "access": rule.access,
            }
            for rule in configuration.profile.landlock_rules
        ],
    }
    policy_path = run_directory / "landlock-policy.json"
    write_json_artifact(policy_path, policy)


def _write_seccomp_profile(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    seccomp_profile = configuration.profile.seccomp_profile
    if seccomp_profile is None:
        return

    profile_data = _build_seccomp_profile_data(seccomp_profile)
    profile_path = run_directory / _SECCOMP_PROFILE_FILE_NAME
    write_json_artifact(profile_path, profile_data)


def _build_seccomp_profile_data(seccomp_profile: SeccompProfile) -> dict[str, object]:
    return {
        "defaultAction": seccomp_profile.default_action,
        "syscalls": [
            {
                "names": list(seccomp_profile.denied_syscalls),
                "action": seccomp_profile.action,
            },
        ],
    }


def _write_squid_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
    config_data: Mapping[str, object],
) -> None:
    squid_gateway.write_configuration(configuration, run_directory, config_data)


def _build_allowed_gateway_domains(
    configured_domains: tuple[str, ...],
    config_data: Mapping[str, object],
) -> tuple[str, ...]:
    return squid_gateway.build_allowed_domains(configured_domains, config_data)


def _start_network_gateway(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    gateway_container_name: str | None,
) -> tuple[list[list[str]] | None, str | None]:
    return squid_gateway.start_gateway(
        configuration,
        run_directory,
        network_name,
        gateway_container_name,
    )


def _write_gateway_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    gateway_container_name: str | None,
) -> None:
    squid_gateway.write_logs(configuration, run_directory, gateway_container_name)


def _start_mcp_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_mcp_sidecar(configuration):
        return None

    return mcp.start(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        _build_mcp_sidecar_no_proxy_hosts(configuration),
        _build_mcp_sidecar_database_environment_options(configuration),
    )


def _build_mcp_sidecar_image_inspect_command() -> list[str]:
    return mcp.build_image_inspect_command()


def _build_mcp_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    return mcp.build_image_build_command(configuration)


def _build_mcp_sidecar_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    mcp_sidecar_container_name: str,
) -> list[str]:
    return mcp.build_run_command(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        _build_mcp_sidecar_no_proxy_hosts(configuration),
        _build_mcp_sidecar_database_environment_options(configuration),
    )


def _wait_for_mcp_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = mcp._MCP_SIDECAR_READINESS_INTERVALS_SECONDS,
) -> None:
    if not _should_start_mcp_sidecar(configuration):
        return

    mcp.wait_until_ready(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        intervals_seconds,
    )


def _run_mcp_sidecar_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    return mcp._run_readiness_phase(configuration, network_name, intervals_seconds)


def _build_mcp_sidecar_health_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
) -> list[str]:
    return mcp.build_health_probe_command(configuration, network_name)


def _build_mcp_sidecar_health_probe_script() -> str:
    return mcp.build_health_probe_script()


def _write_mcp_sidecar_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    mcp.write_readiness_results(run_directory, result)


def _build_mcp_sidecar_no_proxy(configuration: DockerConfiguration) -> str:
    return ",".join(_build_mcp_sidecar_no_proxy_hosts(configuration))


def _build_mcp_sidecar_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    return wiring.build_mcp_sidecar_no_proxy_hosts(configuration)


def _build_mcp_sidecar_database_environment_options(
    configuration: DockerConfiguration,
) -> list[str]:
    return wiring.build_mcp_sidecar_database_environment_options(configuration)


def _resolve_mariadb_proxy_port(ports: tuple[int, ...]) -> int:
    return wiring.resolve_mariadb_proxy_port(ports)


def _build_mcp_sidecar_source_mount(configuration: DockerConfiguration) -> str:
    return mcp._build_source_mount(configuration)


def _build_mcp_sidecar_output_mount(run_directory: Path) -> str:
    return mcp._build_output_mount(run_directory)


def _build_mcp_sidecar_exposure_mount(run_directory: Path) -> str:
    return mcp._build_exposure_mount(run_directory)


def _write_mcp_sidecar_exposure(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not _should_start_mcp_sidecar(configuration):
        return

    mcp.write_exposure(configuration, run_directory)


def _write_mcp_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    mcp.write_start_results(run_directory, results)


def _write_mcp_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    mcp_sidecar_container_name: str | None,
) -> None:
    if not _should_start_mcp_sidecar(configuration):
        return

    mcp.write_logs(run_directory, mcp_sidecar_container_name)


def _start_code_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return code_execution.start(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
    )


def _wait_for_code_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    code_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = (
        code_execution._CODE_SIDECAR_READINESS_INTERVALS_SECONDS
    ),
) -> None:
    code_execution.wait_until_ready(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
        intervals_seconds,
    )


def _run_code_sidecar_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    return code_execution._run_readiness_phase(
        configuration,
        network_name,
        intervals_seconds,
    )


def _build_code_sidecar_health_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
) -> list[str]:
    return code_execution.build_health_probe_command(configuration, network_name)


def _build_code_sidecar_health_probe_script() -> str:
    return code_execution.build_health_probe_script()


def _write_code_sidecar_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    code_execution.write_readiness_results(run_directory, result)


def _build_code_sidecar_image_inspect_command() -> list[str]:
    return code_execution.build_image_inspect_command()


def _build_code_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    return code_execution.build_image_build_command(configuration)


def _build_ollama_sidecar_image_inspect_command(
    configuration: DockerConfiguration,
) -> list[str]:
    return ollama.build_image_inspect_command(configuration)


def _build_ollama_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    return ollama.build_image_build_command(configuration)


def _write_ollama_sidecar_dockerfile(configuration: DockerConfiguration) -> Path:
    return ollama.write_dockerfile(configuration)


def _generate_ollama_sidecar_dockerfile(models: tuple[str, ...]) -> str:
    return ollama.generate_dockerfile(models)


def _build_ollama_model_pull_commands(models: tuple[str, ...]) -> str:
    return ollama._build_model_pull_commands(models)


def _get_ollama_sidecar_image_name(configuration: DockerConfiguration) -> str:
    return ollama.get_image_name(configuration)


def _start_ollama_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return ollama.start(
        configuration,
        run_directory,
        network_name,
        ollama_sidecar_container_name,
    )


def _build_ollama_sidecar_run_command(
    configuration: DockerConfiguration,
    network_name: str,
    ollama_sidecar_container_name: str,
) -> list[str]:
    return ollama.build_run_command(
        configuration,
        network_name,
        ollama_sidecar_container_name,
    )


def _write_ollama_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    ollama.write_start_results(run_directory, results)


def _write_ollama_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    ollama_sidecar_container_name: str | None,
) -> None:
    ollama.write_logs(configuration, run_directory, ollama_sidecar_container_name)


def _wait_for_ollama_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = ollama._OLLAMA_READINESS_INTERVALS_SECONDS,
) -> None:
    ollama.wait_until_ready(
        configuration,
        run_directory,
        network_name,
        ollama_sidecar_container_name,
        intervals_seconds,
    )


def _run_ollama_sidecar_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    phase_name: str,
    script: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    return ollama._run_readiness_phase(
        configuration,
        network_name,
        phase_name,
        script,
        intervals_seconds,
    )


def _build_ollama_sidecar_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    return ollama.build_probe_command(configuration, network_name, script)


def _build_ollama_sidecar_tcp_probe_script() -> str:
    return ollama.build_tcp_probe_script()


def _build_ollama_sidecar_models_probe_script(models: tuple[str, ...]) -> str:
    return ollama.build_models_probe_script(models)


def _write_ollama_sidecar_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    ollama.write_readiness_results(run_directory, result)


def _build_code_sidecar_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    code_sidecar_container_name: str,
) -> list[str]:
    return code_execution.build_run_command(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
    )


def _build_code_sidecar_source_mount(configuration: DockerConfiguration) -> str:
    return code_execution._build_source_mount(configuration)


def _build_code_sidecar_output_mount(run_directory: Path) -> str:
    return code_execution._build_output_mount(run_directory)


def _write_code_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    code_execution.write_start_results(run_directory, results)


def _write_code_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    code_sidecar_container_name: str | None,
) -> None:
    code_execution.write_logs(configuration, run_directory, code_sidecar_container_name)


def _write_haproxy_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    haproxy.write_configuration(configuration, run_directory)


def _generate_haproxy_configuration(backend_host: str, ports: tuple[int, ...]) -> str:
    return haproxy.generate_configuration(backend_host, ports)


def _get_haproxy_configuration(
    configuration: DockerConfiguration,
) -> HAProxyConfiguration:
    return haproxy.get_configuration(configuration)


def _start_haproxy_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return haproxy.start(
        configuration,
        run_directory,
        network_name,
        haproxy_sidecar_container_name,
    )


def _wait_for_haproxy_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    haproxy_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = haproxy._HAPROXY_READINESS_INTERVALS_SECONDS,
) -> None:
    haproxy.wait_until_ready(
        configuration,
        run_directory,
        haproxy_sidecar_container_name,
        intervals_seconds,
    )


def _run_haproxy_sidecar_readiness_phase(
    phase_name: str,
    command: list[str],
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    return haproxy.run_readiness_phase(phase_name, command, intervals_seconds)


def _build_haproxy_sidecar_process_probe_command(
    haproxy_sidecar_container_name: str,
) -> list[str]:
    return haproxy.build_process_probe_command(haproxy_sidecar_container_name)


def _build_haproxy_sidecar_config_probe_command(
    haproxy_sidecar_container_name: str,
) -> list[str]:
    return haproxy.build_config_probe_command(haproxy_sidecar_container_name)


def _build_haproxy_sidecar_run_command(
    run_directory: Path,
    haproxy_sidecar_container_name: str,
) -> list[str]:
    return haproxy.build_run_command(run_directory, haproxy_sidecar_container_name)


def _build_haproxy_sidecar_network_connect_command(
    network_name: str,
    haproxy_sidecar_container_name: str,
) -> list[str]:
    return haproxy.build_network_connect_command(
        network_name,
        haproxy_sidecar_container_name,
    )


def _write_haproxy_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    haproxy.write_start_results(run_directory, results)


def _write_haproxy_sidecar_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    haproxy.write_readiness_results(run_directory, result)


def _write_haproxy_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    haproxy_sidecar_container_name: str | None,
) -> None:
    haproxy.write_logs(configuration, run_directory, haproxy_sidecar_container_name)


def _start_jina_reader(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    return jina_reader.start(
        configuration,
        run_directory,
        network_name,
        jina_reader_container_name,
    )


def _build_jina_reader_run_command(
    network_name: str,
    jina_reader_container_name: str,
) -> list[str]:
    return jina_reader.build_run_command(network_name, jina_reader_container_name)


def _wait_for_jina_reader_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
    intervals_seconds: tuple[float, ...] = (
        jina_reader._JINA_READER_READINESS_INTERVALS_SECONDS
    ),
) -> None:
    jina_reader.wait_until_ready(
        configuration,
        run_directory,
        network_name,
        jina_reader_container_name,
        intervals_seconds,
    )


def _run_jina_reader_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    phase_name: str,
    script: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    return jina_reader._run_readiness_phase(
        configuration,
        network_name,
        phase_name,
        script,
        intervals_seconds,
    )


def _build_jina_reader_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    return jina_reader.build_probe_command(configuration, network_name, script)


def _build_jina_reader_tcp_probe_script() -> str:
    return jina_reader.build_tcp_probe_script()


def _build_jina_reader_fetch_probe_script() -> str:
    return jina_reader.build_fetch_probe_script()


def _write_jina_reader_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    jina_reader.write_readiness_results(run_directory, result)


def _write_jina_reader_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    jina_reader.write_start_results(run_directory, results)


def _write_jina_reader_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    jina_reader_container_name: str | None,
) -> None:
    jina_reader.write_logs(configuration, run_directory, jina_reader_container_name)


def _build_gateway_start_commands(
    gateway_image_name: str,
    gateway_container_name: str,
    network_name: str,
    squid_config_path: Path,
) -> list[list[str]]:
    return squid_gateway.build_start_commands(
        gateway_image_name,
        gateway_container_name,
        network_name,
        squid_config_path,
    )


def _build_gateway_cleanup_commands(
    configuration: DockerConfiguration,
    network_name: str | None,
    gateway_container_name: str | None,
) -> list[list[str]] | None:
    return squid_gateway.build_cleanup_commands(
        configuration,
        network_name,
        gateway_container_name,
    )


def _build_mcp_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_mcp_sidecar(configuration):
        return None

    return mcp.build_cleanup_commands(mcp_sidecar_container_name)


def _build_jina_reader_cleanup_commands(
    configuration: DockerConfiguration,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    return jina_reader.build_cleanup_commands(configuration, jina_reader_container_name)


def _build_code_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return code_execution.build_cleanup_commands(
        configuration,
        code_sidecar_container_name,
    )


def _build_haproxy_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return haproxy.build_cleanup_commands(
        configuration,
        haproxy_sidecar_container_name,
    )


def _build_ollama_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    return ollama.build_cleanup_commands(configuration, ollama_sidecar_container_name)


def _should_start_mcp_sidecar(configuration: DockerConfiguration) -> bool:
    return wiring.should_start_mcp_sidecar(configuration)


def _should_start_jina_reader(configuration: DockerConfiguration) -> bool:
    return wiring.should_start_jina_reader(configuration)


def _should_start_code_sidecar(configuration: DockerConfiguration) -> bool:
    return wiring.should_start_code_sidecar(configuration)


def _should_start_haproxy_sidecar(configuration: DockerConfiguration) -> bool:
    return wiring.should_start_haproxy_sidecar(configuration)


def _should_start_ollama_sidecar(configuration: DockerConfiguration) -> bool:
    return wiring.should_start_ollama_sidecar(configuration)


def _delete_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_source_directory = run_directory / _READONLY_DENIED_SOURCE_DIRECTORY
    resolved_run_directory = run_directory.resolve()
    resolved_denied_source_directory = denied_source_directory.resolve()

    if resolved_run_directory not in resolved_denied_source_directory.parents:
        raise RuntimeError(
            "Refusing to remove readonly denied fixture outside the run "
            f"directory: {resolved_denied_source_directory}"
        )

    shutil.rmtree(denied_source_directory, ignore_errors=True)


def _delete_readonly_persistence_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.readonly_persistence_directories:
        return

    persistence_source_directory = (
        run_directory / _READONLY_PERSISTENCE_SOURCE_DIRECTORY
    )
    resolved_run_directory = run_directory.resolve()
    resolved_persistence_source_directory = persistence_source_directory.resolve()

    if resolved_run_directory not in resolved_persistence_source_directory.parents:
        raise RuntimeError(
            "Refusing to remove readonly persistence fixture outside the run "
            f"directory: {resolved_persistence_source_directory}"
        )

    shutil.rmtree(persistence_source_directory, ignore_errors=True)


def _delete_denied_executable_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not _get_denied_executable_targets(configuration):
        return

    stub_directory = run_directory / _DENIED_EXECUTABLE_SOURCE_DIRECTORY
    resolved_run_directory = run_directory.resolve()
    resolved_stub_directory = stub_directory.resolve()

    if resolved_run_directory not in resolved_stub_directory.parents:
        raise RuntimeError(
            "Refusing to remove denied executable stubs outside the run "
            f"directory: {resolved_stub_directory}"
        )

    shutil.rmtree(stub_directory, ignore_errors=True)


def _build_config_data(
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    guest_user: str,
    ssh_agent_socket: str | None = None,
    browser_debugging: BrowserDebuggingProfile | None = None,
    browser_surface: BrowserSurfaceProfile | None = None,
) -> dict[str, object]:
    return agent_run.build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        guest_user,
        ssh_agent_socket,
        browser_debugging,
        browser_surface,
    )


def _build_config_json(
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    guest_user: str,
    ssh_agent_socket: str | None = None,
    browser_debugging: BrowserDebuggingProfile | None = None,
    browser_surface: BrowserSurfaceProfile | None = None,
) -> str:
    config = agent_run.build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        guest_user,
        ssh_agent_socket,
        browser_debugging,
        browser_surface,
    )
    return f"{json.dumps(config, indent=2)}\n"


def _get_browser_debugging_url(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    return agent_run.get_browser_debugging_url(browser_debugging)


def _get_browser_executable(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    return agent_run.get_browser_executable(browser_debugging)


def _get_existing_browser_profile(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    return agent_run.get_existing_browser_profile(browser_debugging)


def _get_browser_chromium_arguments(
    browser_surface: BrowserSurfaceProfile | None,
) -> list[str]:
    return agent_run.get_browser_chromium_arguments(browser_surface)


def _get_allow_camera_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    return agent_run.get_allow_camera_capture(browser_surface)


def _get_allow_microphone_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    return agent_run.get_allow_microphone_capture(browser_surface)


def _build_docker_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    container_name: str,
    remote_run_directory: str,
    network_name: str | None = None,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    environment_variables: dict[str, str] | None = None,
    gateway_ip_address: str | None = None,
    local_environment_variable_names: Set[str] | None = None,
    verbose: bool = False,
    serialize_evidence: bool = False,
) -> list[str]:
    return agent_run.build_docker_run_command(
        configuration=configuration,
        run_directory=run_directory,
        container_name=container_name,
        remote_run_directory=remote_run_directory,
        network_name=network_name,
        allowed_directory=allowed_directory,
        denied_directory=denied_directory,
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
    )


def _build_ipc_options(configuration: DockerConfiguration) -> list[str]:
    return agent_run.build_ipc_options(configuration)


def _build_security_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    return agent_run.build_security_options(configuration, run_directory)


def _build_dns_policy_options(
    configuration: DockerConfiguration,
    gateway_ip_address: str | None,
) -> list[str]:
    return agent_run.build_dns_policy_options(configuration, gateway_ip_address)


def _get_dns_policy_address(
    dns_policy: NetworkDnsPolicy,
    gateway_ip_address: str | None,
) -> str:
    return agent_run.get_dns_policy_address(dns_policy, gateway_ip_address)


def _build_source_mount(configuration: DockerConfiguration) -> str:
    return agent_run.build_source_mount(configuration)


def _build_container_environment(
    configuration: DockerConfiguration,
    environment_variables: Mapping[str, str],
    gateway_ip_address: str | None = None,
) -> dict[str, str]:
    return agent_run.build_container_environment(
        configuration,
        environment_variables,
        gateway_ip_address,
    )


def _remove_agent_database_environment(environment: dict[str, str]) -> None:
    wiring.remove_agent_database_environment(environment)


def _build_agent_gateway_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    return wiring.build_agent_gateway_no_proxy_hosts(configuration)


def _build_effective_local_environment_variable_names(
    configuration: DockerConfiguration,
    local_environment_variable_names: Set[str],
) -> Set[str]:
    _ = configuration
    return agent_run.build_effective_local_environment_variable_names(
        local_environment_variable_names,
    )


def _apply_environment_policies(
    environment: dict[str, str],
    policies: tuple[EnvironmentVariablePolicy, ...],
) -> None:
    agent_run.apply_environment_policies(environment, policies)


def _apply_desktop_automation_policy(
    environment: dict[str, str],
    allow_desktop_automation_channel: bool,
) -> None:
    agent_run.apply_desktop_automation_policy(
        environment,
        allow_desktop_automation_channel,
    )


def _build_readonly_denied_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    return agent_run.build_readonly_denied_mount_options(configuration, run_directory)


def _build_readonly_persistence_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    return agent_run.build_readonly_persistence_mount_options(
        configuration,
        run_directory,
    )


def _build_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    return agent_run.build_socket_mount_options(configuration)


def _build_agent_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    return agent_run.build_agent_socket_mount_options(configuration)


def _get_agent_socket_forwards(
    configuration: DockerConfiguration,
) -> tuple[AgentSocketForward, ...]:
    return agent_run.get_agent_socket_forwards(configuration)


def _build_agent_socket_mount_option(agent_socket: AgentSocketForward) -> str:
    return agent_run.build_agent_socket_mount_option(agent_socket)


def _build_denied_executable_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    return agent_run.build_denied_executable_mount_options(configuration, run_directory)


def _build_socket_mount_option(socket_mount: SocketMount) -> str:
    return agent_run.build_socket_mount_option(socket_mount)


def _get_container_ssh_agent_socket(
    configuration: DockerConfiguration,
) -> str | None:
    return agent_run.get_container_ssh_agent_socket(configuration)


def _get_container_gpg_home(configuration: DockerConfiguration) -> str | None:
    return agent_run.get_container_gpg_home(configuration)


def _build_container_script(
    run_target: SandboxRunTarget,
    remote_run_directory: str,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    create_denied_fixture: bool = True,
    verbose: bool = False,
    serialize_evidence: bool = False,
    landlock_policy_path: str | None = None,
) -> str:
    return agent_run.build_container_script(
        run_target=run_target,
        remote_run_directory=remote_run_directory,
        allowed_directory=allowed_directory,
        denied_directory=denied_directory,
        create_denied_fixture=create_denied_fixture,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
        landlock_policy_path=landlock_policy_path,
    )


def _build_sandbox_command_arguments(
    run_target: SandboxRunTarget,
    landlock_policy_path: str | None,
) -> list[str]:
    return agent_run.build_sandbox_command_arguments(run_target, landlock_policy_path)


def _build_write_text_command(path: str, content: str) -> str:
    return agent_run.build_write_text_command(path, content)


def _resolve_environment_variables(
    configured_variables: Mapping[str, str],
    host_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return agent_run.resolve_environment_variables(
        configured_variables,
        host_environment,
    )


def _get_local_environment_variable_names(
    configured_variables: Mapping[str, str],
) -> set[str]:
    return agent_run.get_local_environment_variable_names(configured_variables)


def _build_environment_options(
    environment_variables: Mapping[str, str],
    local_environment_variable_names: Set[str],
) -> list[str]:
    return agent_run.build_environment_options(
        environment_variables,
        local_environment_variable_names,
    )


def _run_interactive_command(command: list[str]) -> CommandResult:
    return agent_run.run_interactive_command(command)


def _start_stream_thread(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> threading.Thread:
    return agent_run._start_stream_thread(source, destination, chunks)


def _stream_text(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> None:
    agent_run._stream_text(source, destination, chunks)
