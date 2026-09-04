"""Tests for jina reader."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    jina_reader,
    mcp,
)


def test_jina_reader_cleanup_removes_reader_before_network_cleanup() -> None:
    """Verify Jina Reader cleanup removes the reader container."""
    configuration = _create_jina_reader_configuration()

    cleanup_commands = jina_reader.build_cleanup_commands(
        configuration,
        "jina-reader-1",
    )

    assert cleanup_commands == [["docker", "rm", "--force", "jina-reader-1"]]


def test_jina_reader_run_command_uses_internal_network_and_proxy() -> None:
    """Verify Jina Reader is started on the internal network with Squid proxy env."""
    command = jina_reader.build_run_command(
        "sandbox-agent-net-1",
        "jina-reader-1",
    )

    assert command[:4] == ["docker", "run", "--detach", "--name"]
    assert "jina-reader-1" in command
    assert _option_value(command, "--network") == "sandbox-agent-net-1"
    assert _option_value(command, "--network-alias") == "jina-reader"
    assert "HTTP_PROXY=http://egress-gateway:3128" in _option_values(
        command,
        "--env",
    )
    assert "HTTPS_PROXY=http://egress-gateway:3128" in _option_values(
        command,
        "--env",
    )
    assert "NO_PROXY=localhost,127.0.0.1,jina-reader,mcp-sidecar" in _option_values(
        command,
        "--env",
    )
    assert command[-1] == "ghcr.io/jina-ai/reader:oss"


def test_jina_reader_start_persists_start_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Jina Reader startup command results are persisted for debugging."""
    configuration = _create_jina_reader_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert command == jina_reader.build_run_command(
            "sandbox-agent-net-1",
            "jina-reader-1",
        )
        assert check is False
        assert capture_output is True
        assert text is True
        assert encoding == "utf-8"
        assert errors == "replace"
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="reader started\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    commands = jina_reader.start(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "jina-reader-1",
    )

    start_results = json.loads(
        (tmp_path / "jina-reader-start-results.json").read_text()
    )
    assert commands == [
        jina_reader.build_run_command("sandbox-agent-net-1", "jina-reader-1")
    ]
    assert commands is not None
    assert start_results == [
        {
            "command": commands[0],
            "returncode": 0,
            "stdout": "reader started\n",
            "stderr": "",
        }
    ]


def test_jina_reader_wait_until_ready_persists_two_phase_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Jina Reader readiness writes TCP and fetch probe results."""
    configuration = _create_jina_reader_configuration()
    calls = []
    sleeps = []

    def fake_sleep(interval_seconds: float) -> None:
        sleeps.append(interval_seconds)

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="connection refused",
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ready\n",
            stderr="",
        )

    monkeypatch.setattr("docker_sandbox.sidecars.jina_reader.time.sleep", fake_sleep)
    monkeypatch.setattr(subprocess, "run", fake_run)

    jina_reader.wait_until_ready(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "jina-reader-1",
        intervals_seconds=(0.0, 1.0),
    )

    readiness_results = json.loads(
        (tmp_path / "jina-reader-readiness-results.json").read_text()
    )
    assert sleeps == [1.0]
    assert readiness_results["container_name"] == "jina-reader-1"
    assert readiness_results["reader_url"] == "http://jina-reader:8081"
    assert readiness_results["fetch_url"] == "https://example.com"
    assert readiness_results["ready"] is True
    assert [phase["name"] for phase in readiness_results["phases"]] == [
        "tcp",
        "fetch",
    ]
    assert readiness_results["phases"][0]["success"] is True
    assert readiness_results["phases"][0]["attempts"][0]["success"] is False
    assert readiness_results["phases"][0]["attempts"][1]["success"] is True
    assert readiness_results["phases"][1]["success"] is True
    assert len(calls) == 3
    assert all(
        command[:5] == ["docker", "run", "--rm", "--network", "sandbox-agent-net-1"]
        for command in calls
    )
    assert all(
        "sandbox-agent/sandbox-agent:locked-down" in command for command in calls
    )


def test_jina_reader_write_logs_persists_debug_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Jina Reader logs are persisted as text and metadata artifacts."""
    configuration = _create_jina_reader_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "logs", "jina-reader-1"]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="reader stdout\n",
            stderr="reader stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    jina_reader.write_logs(configuration, tmp_path, "jina-reader-1")

    metadata = json.loads((tmp_path / "jina-reader-metadata.json").read_text())
    assert (tmp_path / "jina-reader-stdout.txt").read_text() == "reader stdout\n"
    assert (tmp_path / "jina-reader-stderr.txt").read_text() == "reader stderr\n"
    assert metadata == {
        "container_name": "jina-reader-1",
        "image_name": "ghcr.io/jina-ai/reader:oss",
        "log_command": ["docker", "logs", "jina-reader-1"],
        "log_returncode": 0,
    }


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
