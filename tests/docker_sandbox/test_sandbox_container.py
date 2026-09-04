"""Tests for Docker MCP sidecar container orchestration."""

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
from docker_sandbox.sandbox_container import (
    _build_mcp_sidecar_cleanup_commands,
    _build_mcp_sidecar_container_name,
    _build_run_context,
    _start_mcp_sidecar,
    _wait_for_mcp_sidecar_ready,
    _write_mcp_sidecar_exposure,
    _write_mcp_sidecar_logs,
)
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    mcp,
)


def test_run_context_collects_run_paths_and_container_names(tmp_path: Path) -> None:
    """Verify run context centralizes names derived for one sandbox run."""
    configuration = _create_ollama_configuration(tmp_path)
    configuration = replace(
        configuration,
        enabled_capabilities=frozenset(
            {
                "code_execution",
                "haproxy",
                "jina_reader",
                "mcp_client",
                "ollama",
                "openai_agents",
            }
        ),
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=(3306,),
        ),
    )

    context = _build_run_context(configuration, "2026-07-20-16-00-00")

    assert context.timestamp == "2026-07-20-16-00-00"
    assert context.run_id == "run-2026-07-20-16-00-00"
    assert context.run_directory == tmp_path / "runs" / context.run_id
    assert context.container_name == "sandbox-agent-run-2026-07-20-16-00-00"
    assert context.network_name == "sandbox-agent-net-2026-07-20-16-00-00"
    assert context.gateway_container_name == (
        "sandbox-agent-gateway-2026-07-20-16-00-00"
    )
    assert context.mcp_sidecar_container_name == ("mcp-sidecar-2026-07-20-16-00-00")
    assert context.jina_reader_container_name == ("jina-reader-2026-07-20-16-00-00")
    assert context.code_sidecar_container_name == ("code-sidecar-2026-07-20-16-00-00")
    assert context.haproxy_sidecar_container_name == (
        "haproxy-sidecar-2026-07-20-16-00-00"
    )
    assert context.ollama_sidecar_container_name == (
        "ollama-sidecar-2026-07-20-16-00-00"
    )


def test_mcp_sidecar_container_name_is_created_for_agent_network_runs() -> None:
    """Verify agent runs with a network gateway get an MCP sidecar container."""
    configuration = _create_network_configuration()

    container_name = _build_mcp_sidecar_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name == "mcp-sidecar-2026-07-20-16-00-00"


def test_mcp_sidecar_container_name_is_omitted_without_network() -> None:
    """Verify no-network runs do not get an MCP sidecar container."""
    configuration = _create_locked_down_configuration()

    container_name = _build_mcp_sidecar_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name is None


def test_mcp_sidecar_container_name_is_omitted_without_exposure() -> None:
    """Verify MCP is not started unless tools or resources are exposed."""
    configuration = replace(
        _create_network_configuration(),
        mcp_sidecar_tools=(),
        mcp_sidecar_resources=(),
    )

    container_name = _build_mcp_sidecar_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name is None


def test_start_mcp_sidecar_rebuilds_image_before_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP startup refreshes the dev image before running the sidecar."""
    configuration = _create_network_configuration()
    calls = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        assert encoding == "utf-8"
        assert errors == "replace"
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    commands = _start_mcp_sidecar(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    expected_commands = [
        mcp.build_image_inspect_command(),
        mcp.build_image_build_command(configuration),
        _build_expected_mcp_run_command(
            configuration,
            tmp_path,
            "sandbox-agent-net-1",
            "mcp-sidecar-1",
        ),
    ]
    start_results = json.loads(
        (tmp_path / "mcp-sidecar-start-results.json").read_text()
    )

    assert commands == expected_commands
    assert calls == expected_commands
    assert [result["command"] for result in start_results] == expected_commands


def test_wait_for_mcp_sidecar_ready_persists_health_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP readiness writes health probe results."""
    configuration = _create_network_configuration()
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

    _wait_for_mcp_sidecar_ready(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    readiness_results = json.loads(
        (tmp_path / "mcp-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["container_name"] == "mcp-sidecar-1"
    assert readiness_results["health_url"] == "http://mcp-sidecar:8000/health"
    assert readiness_results["ready"] is True
    assert readiness_results["phases"][0]["name"] == "health"
    assert readiness_results["phases"][0]["success"] is True
    assert readiness_results["phases"][0]["attempts"][0]["command"] == attempts[0]


def test_wait_for_mcp_sidecar_ready_raises_when_health_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP readiness stops orchestration when health does not pass."""
    configuration = _create_network_configuration()

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

    with pytest.raises(RuntimeError, match="MCP sidecar did not become ready"):
        _wait_for_mcp_sidecar_ready(
            configuration,
            tmp_path,
            "sandbox-agent-net-1",
            "mcp-sidecar-1",
            intervals_seconds=(0.0,),
        )

    readiness_results = json.loads(
        (tmp_path / "mcp-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["ready"] is False
    assert readiness_results["phases"][0]["attempts"][0]["stderr"] == (
        "connection refused\n"
    )


def test_mcp_sidecar_cleanup_removes_sidecar_before_network_cleanup() -> None:
    """Verify MCP sidecar cleanup removes the sidecar container."""
    configuration = _create_network_configuration()

    cleanup_commands = _build_mcp_sidecar_cleanup_commands(
        configuration,
        "mcp-sidecar-1",
    )

    assert cleanup_commands == [["docker", "rm", "--force", "mcp-sidecar-1"]]


def test_write_mcp_sidecar_logs_persists_debug_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP sidecar logs are persisted as text and metadata artifacts."""
    configuration = _create_network_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "logs", "mcp-sidecar-1"]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="sidecar stdout\n",
            stderr="sidecar stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    _write_mcp_sidecar_logs(configuration, tmp_path, "mcp-sidecar-1")

    metadata = json.loads((tmp_path / "mcp-sidecar-metadata.json").read_text())
    assert (tmp_path / "mcp-sidecar-stdout.txt").read_text() == "sidecar stdout\n"
    assert (tmp_path / "mcp-sidecar-stderr.txt").read_text() == "sidecar stderr\n"
    assert metadata == {
        "container_name": "mcp-sidecar-1",
        "image_name": "mcp-sidecar:dev",
        "log_command": ["docker", "logs", "mcp-sidecar-1"],
        "log_returncode": 0,
    }


def test_write_mcp_sidecar_exposure_persists_config(tmp_path: Path) -> None:
    """Verify MCP sidecar exposure config is persisted as a run artifact."""
    configuration = _create_network_configuration()
    configuration = replace(
        configuration,
        mcp_sidecar_tools=("jina_read_url",),
        mcp_sidecar_resources=("answer_format",),
    )

    _write_mcp_sidecar_exposure(configuration, tmp_path)

    exposure = json.loads((tmp_path / "mcp-sidecar-exposure.json").read_text())
    assert exposure == {
        "tools": ["jina_read_url"],
        "resources": ["answer_format"],
    }


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


def _create_jina_reader_configuration() -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"jina_reader"}),
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


def _create_locked_down_configuration() -> DockerConfiguration:
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=hardening.base_locked_down_profile(),
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


def _option_value(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def _option_values(command: list[str], option: str) -> list[str]:
    return [
        value
        for index, value in enumerate(command)
        if index > 0 and command[index - 1] == option
    ]
