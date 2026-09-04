"""Tests for code execution."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    code_execution,
    mcp,
)


def test_code_execution_write_logs_persists_debug_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify code sidecar logs are persisted as text and metadata artifacts."""
    configuration = _create_code_execution_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "logs", "code-sidecar-1"]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="code stdout\n",
            stderr="code stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    code_execution.write_logs(configuration, tmp_path, "code-sidecar-1")

    metadata = json.loads((tmp_path / "code-sidecar-metadata.json").read_text())
    assert (tmp_path / "code-sidecar-stdout.txt").read_text() == "code stdout\n"
    assert (tmp_path / "code-sidecar-stderr.txt").read_text() == "code stderr\n"
    assert metadata == {
        "container_name": "code-sidecar-1",
        "image_name": "code-sidecar:dev",
        "log_command": ["docker", "logs", "code-sidecar-1"],
        "log_returncode": 0,
    }


def test_code_sidecar_cleanup_removes_sidecar_before_network_cleanup() -> None:
    """Verify code sidecar cleanup removes the sidecar container."""
    configuration = _create_code_execution_configuration()

    cleanup_commands = code_execution.build_cleanup_commands(
        configuration,
        "code-sidecar-1",
    )

    assert cleanup_commands == [["docker", "rm", "--force", "code-sidecar-1"]]


def test_code_sidecar_health_probe_script_targets_health_route() -> None:
    """Verify the Code sidecar readiness probe uses the health endpoint."""
    script = code_execution.build_health_probe_script()

    assert "http://code-sidecar:8090/health" in script
    assert "data.get('status') != 'ok'" in script


def test_code_sidecar_image_commands_use_static_dockerfile() -> None:
    """Verify the code sidecar image commands target the static Dockerfile."""
    configuration = _create_network_configuration()

    inspect_command = code_execution.build_image_inspect_command()
    build_command = code_execution.build_image_build_command(configuration)

    assert inspect_command == ["docker", "image", "inspect", "code-sidecar:dev"]
    assert build_command == [
        "docker",
        "build",
        "--file",
        str(Path("src") / "code_sidecar" / "dockerfile" / "Dockerfile"),
        "--tag",
        "code-sidecar:dev",
        ".",
    ]


def test_code_sidecar_run_command_uses_internal_network_without_proxy() -> None:
    """Verify the code sidecar starts with tight local-only hardening."""
    command = code_execution.build_run_command(
        _create_code_execution_configuration(),
        Path(".docker_sandbox") / "runs" / "run-1",
        "sandbox-agent-net-1",
        "code-sidecar-1",
    )

    assert command[:5] == ["docker", "run", "--detach", "--init", "--read-only"]
    assert "code-sidecar-1" in command
    assert _option_value(command, "--network") == "sandbox-agent-net-1"
    assert _option_value(command, "--network-alias") == "code-sidecar"
    assert _option_value(command, "--pids-limit") == "32"
    assert _option_value(command, "--memory") == "128m"
    assert _option_value(command, "--memory-swap") == "128m"
    assert _option_value(command, "--cpus") == "0.5"
    assert "--cap-drop=ALL" in command
    assert "no-new-privileges" in _option_values(command, "--security-opt")
    assert (
        "seccomp=.docker_sandbox\\runs\\run-1\\seccomp-profile.json"
    ) in _option_values(command, "--security-opt")
    assert _option_value(command, "--tmpfs") == "/tmp:rw,nosuid,nodev,noexec,size=16m"
    assert "HTTP_PROXY=http://egress-gateway:3128" not in _option_values(
        command,
        "--env",
    )
    assert ("CODE_SIDECAR_OUTPUT_DIRECTORY=/code-sidecar-output") in _option_values(
        command, "--env"
    )
    assert _option_values(command, "--mount") == [
        "type=bind,source=src\\code_sidecar,target=/opt/code-sidecar/code_sidecar,readonly",
        "type=bind,source=.docker_sandbox\\runs\\run-1,target=/code-sidecar-output",
    ]
    assert command[-8:] == [
        "code-sidecar:dev",
        "python",
        "-m",
        "code_sidecar",
        "--host",
        "0.0.0.0",
        "--port",
        "8090",
    ]


def test_code_sidecar_wait_until_ready_persists_health_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Code readiness writes health probe results."""
    configuration = _create_code_execution_configuration()
    attempts = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        attempts.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ready\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    code_execution.wait_until_ready(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "code-sidecar-1",
    )

    readiness_results = json.loads(
        (tmp_path / "code-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["container_name"] == "code-sidecar-1"
    assert readiness_results["health_url"] == "http://code-sidecar:8090/health"
    assert readiness_results["ready"] is True
    assert readiness_results["phases"][0]["name"] == "health"
    assert readiness_results["phases"][0]["success"] is True
    assert readiness_results["phases"][0]["attempts"][0]["command"] == attempts[0]


def test_code_sidecar_wait_until_ready_raises_when_health_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Code readiness stops orchestration when health does not pass."""
    configuration = _create_code_execution_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        _ = capture_output
        _ = text
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="connection refused\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Code sidecar did not become ready"):
        code_execution.wait_until_ready(
            configuration,
            tmp_path,
            "sandbox-agent-net-1",
            "code-sidecar-1",
            intervals_seconds=(0.0,),
        )

    readiness_results = json.loads(
        (tmp_path / "code-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["ready"] is False
    assert readiness_results["phases"][0]["attempts"][0]["stderr"] == (
        "connection refused\n"
    )


def _build_expected_mcp_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    container_name: str,
) -> list[str]:
    no_proxy_hosts = wiring.build_mcp_sidecar_no_proxy_hosts(configuration)
    database_options = wiring.build_mcp_sidecar_database_environment_options(
        configuration
    )
    return mcp.build_run_command(
        configuration,
        run_directory,
        network_name,
        container_name,
        no_proxy_hosts,
        database_options,
    )


def _create_code_execution_configuration() -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"code_execution"}),
    )


def _create_haproxy_configuration(
    ports: tuple[int, ...] = (3306,),
) -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"haproxy"}),
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=ports,
        ),
    )


def _create_jina_reader_configuration() -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"jina_reader"}),
    )


def _create_locked_down_configuration() -> DockerConfiguration:
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=hardening.base_locked_down_profile(),
    )


def _create_network_configuration() -> DockerConfiguration:
    profile = hardening.base_locked_down_profile()
    network_gateway = NetworkGatewayProfile(
        image_name="ubuntu/squid:latest",
        proxy_host="egress-gateway",
        proxy_port=3128,
    )
    profile = replace(
        profile,
        network_gateway=network_gateway,
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
        mcp_sidecar_tools=("get_active_items",),
    )


def _create_ollama_configuration(base_directory: Path) -> DockerConfiguration:
    configuration = _create_network_configuration()
    models = ("phi4-mini:latest", "qwen3:4b")
    profile = replace(
        configuration.profile,
        environment=tuple(
            policy
            for policy in configuration.profile.environment
            if policy.name != "OPENAI_API_KEY"
        ),
    )
    return replace(
        configuration,
        base_directory=base_directory,
        enabled_capabilities=frozenset({"openai_agents", "ollama"}),
        profile=profile,
        ollama_models=models,
        ollama_image_name=resolve_ollama_image_name(models),
    )


def _option_value(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def _option_values(command: list[str], option: str) -> list[str]:
    return [
        value
        for index, value in enumerate(command)
        if index > 0 and command[index - 1] == option
    ]
