"""Run Sandbox Agent inside disposable Docker containers."""

from __future__ import annotations

import datetime as dt
import shlex
import shutil
from pathlib import Path, PurePosixPath

from .agent_container import run as agent_run
from .models import (
    DockerConfiguration,
    DockerRunResult,
    SeccompProfile,
)
from .orchestration import wiring
from .orchestration.artifacts import write_json_artifact
from .orchestration.docker import build_docker_remove_command
from .orchestration.types import RunContext
from .sidecars import code_execution, haproxy, jina_reader, mcp, ollama, squid_gateway

_DOCKER_EXECUTABLE = "docker"
_CONTAINER_NAME_PREFIX = "sandbox-agent-run"
_NETWORK_NAME_PREFIX = "sandbox-agent-net"


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
    config_data = agent_run.build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        configuration.guest_user,
        agent_run.get_container_ssh_agent_socket(configuration),
        configuration.profile.browser_debugging,
        configuration.profile.browser_surface,
    )
    squid_gateway.write_configuration(configuration, run_directory, config_data)
    _write_mcp_sidecar_exposure(configuration, run_directory)
    haproxy.write_configuration(configuration, run_directory)
    config_path = run_directory / "config.json"
    write_json_artifact(config_path, config_data)
    configured_environment_variables = dict(configuration.environment_variables)
    environment_variables = agent_run.resolve_environment_variables(
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
            gateway_commands, gateway_ip_address = squid_gateway.start_gateway(
                configuration,
                run_directory,
                network_name,
                gateway_container_name,
            )
        elif sidecar_name == wiring.JINA_READER:
            jina_reader_commands = jina_reader.start(
                configuration,
                run_directory,
                network_name,
                jina_reader_container_name,
            )
            jina_reader.wait_until_ready(
                configuration,
                run_directory,
                network_name,
                jina_reader_container_name,
                jina_reader._JINA_READER_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.CODE_EXECUTION:
            code_sidecar_commands = code_execution.start(
                configuration,
                run_directory,
                network_name,
                code_sidecar_container_name,
            )
            code_execution.wait_until_ready(
                configuration,
                run_directory,
                network_name,
                code_sidecar_container_name,
                code_execution._CODE_SIDECAR_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.HAPROXY:
            haproxy_sidecar_commands = haproxy.start(
                configuration,
                run_directory,
                network_name,
                haproxy_sidecar_container_name,
            )
            haproxy.wait_until_ready(
                configuration,
                run_directory,
                haproxy_sidecar_container_name,
                haproxy._HAPROXY_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.OLLAMA:
            ollama_sidecar_commands = ollama.start(
                configuration,
                run_directory,
                network_name,
                ollama_sidecar_container_name,
            )
            ollama.wait_until_ready(
                configuration,
                run_directory,
                network_name,
                ollama_sidecar_container_name,
                ollama._OLLAMA_READINESS_INTERVALS_SECONDS,
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
    command = agent_run.build_docker_run_command(
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
    completed = agent_run.run_interactive_command(command)
    _write_mcp_sidecar_logs(configuration, run_directory, mcp_sidecar_container_name)
    jina_reader.write_logs(configuration, run_directory, jina_reader_container_name)
    code_execution.write_logs(configuration, run_directory, code_sidecar_container_name)
    haproxy.write_logs(
        configuration,
        run_directory,
        haproxy_sidecar_container_name,
    )
    ollama.write_logs(
        configuration,
        run_directory,
        ollama_sidecar_container_name,
    )
    squid_gateway.write_logs(configuration, run_directory, gateway_container_name)
    _delete_readonly_denied_directory(configuration, run_directory)
    _delete_readonly_persistence_directory(configuration, run_directory)
    _delete_denied_executable_directory(configuration, run_directory)
    remove_command = build_docker_remove_command(container_name, _DOCKER_EXECUTABLE)
    gateway_cleanup_commands = squid_gateway.build_cleanup_commands(
        configuration,
        network_name,
        gateway_container_name,
    )
    mcp_sidecar_cleanup_commands = _build_mcp_sidecar_cleanup_commands(
        configuration,
        mcp_sidecar_container_name,
    )
    jina_reader_cleanup_commands = jina_reader.build_cleanup_commands(
        configuration,
        jina_reader_container_name,
    )
    code_sidecar_cleanup_commands = code_execution.build_cleanup_commands(
        configuration,
        code_sidecar_container_name,
    )
    haproxy_sidecar_cleanup_commands = haproxy.build_cleanup_commands(
        configuration,
        haproxy_sidecar_container_name,
    )
    ollama_sidecar_cleanup_commands = ollama.build_cleanup_commands(
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
        allowed_directory=agent_run.build_allowed_directory(
            configuration,
            remote_run_directory,
        ),
        denied_directory=agent_run.build_denied_directory(
            configuration,
            remote_run_directory,
        ),
        network_name=_build_network_name(configuration, timestamp),
        gateway_container_name=squid_gateway.build_container_name(
            configuration,
            timestamp,
        ),
        mcp_sidecar_container_name=_build_mcp_sidecar_container_name(
            configuration,
            timestamp,
        ),
        jina_reader_container_name=jina_reader.build_container_name(
            configuration,
            timestamp,
        ),
        code_sidecar_container_name=code_execution.build_container_name(
            configuration,
            timestamp,
        ),
        haproxy_sidecar_container_name=haproxy.build_container_name(
            configuration,
            timestamp,
        ),
        ollama_sidecar_container_name=ollama.build_container_name(
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


def _build_mcp_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return mcp.build_container_name(timestamp)


def _build_network_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if configuration.profile.network_gateway is None:
        return None

    return f"{_NETWORK_NAME_PREFIX}-{timestamp}"


def _prepare_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_child_directory = (
        run_directory / agent_run.READONLY_DENIED_SOURCE_DIRECTORY / "denied"
    )
    denied_child_directory.mkdir(parents=True, exist_ok=True)
    denied_file = denied_child_directory / "denied.txt"
    denied_file.write_text(agent_run.DENIED_FILE_CONTENT, encoding="utf-8")
    hidden_file = denied_child_directory / ".hidden"
    hidden_file.write_text(agent_run.HIDDEN_DENIED_FILE_CONTENT, encoding="utf-8")


def _prepare_readonly_persistence_directories(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    for target in configuration.profile.readonly_persistence_directories:
        agent_run.validate_container_directory(target)
        source_directory = agent_run.build_readonly_persistence_source_directory(
            run_directory,
            target,
        )
        source_directory.mkdir(parents=True, exist_ok=True)


def _prepare_denied_executable_stubs(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    denied_targets = agent_run.get_denied_executable_targets(configuration)
    if not denied_targets:
        return

    stub_directory = run_directory / agent_run.DENIED_EXECUTABLE_SOURCE_DIRECTORY
    stub_directory.mkdir(parents=True, exist_ok=True)
    for target_path in denied_targets:
        stub_path = stub_directory / agent_run.build_denied_executable_stub_name(
            target_path
        )
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
    profile_path = run_directory / agent_run.SECCOMP_PROFILE_FILE_NAME
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


def _start_mcp_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return mcp.start(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        wiring.build_mcp_sidecar_no_proxy_hosts(configuration),
        wiring.build_mcp_sidecar_database_environment_options(configuration),
    )


def _wait_for_mcp_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = mcp._MCP_SIDECAR_READINESS_INTERVALS_SECONDS,
) -> None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return

    mcp.wait_until_ready(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        intervals_seconds,
    )


def _write_mcp_sidecar_exposure(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return

    mcp.write_exposure(configuration, run_directory)


def _write_mcp_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    mcp_sidecar_container_name: str | None,
) -> None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return

    mcp.write_logs(run_directory, mcp_sidecar_container_name)


def _build_mcp_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return mcp.build_cleanup_commands(mcp_sidecar_container_name)


def _delete_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_source_directory = run_directory / agent_run.READONLY_DENIED_SOURCE_DIRECTORY
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
        run_directory / agent_run.READONLY_PERSISTENCE_SOURCE_DIRECTORY
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
    if not agent_run.get_denied_executable_targets(configuration):
        return

    stub_directory = run_directory / agent_run.DENIED_EXECUTABLE_SOURCE_DIRECTORY
    resolved_run_directory = run_directory.resolve()
    resolved_stub_directory = stub_directory.resolve()

    if resolved_run_directory not in resolved_stub_directory.parents:
        raise RuntimeError(
            "Refusing to remove denied executable stubs outside the run "
            f"directory: {resolved_stub_directory}"
        )

    shutil.rmtree(stub_directory, ignore_errors=True)
