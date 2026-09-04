"""Tests for Docker sidecar lifecycle orchestration."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import DockerConfiguration, NetworkGatewayProfile
from docker_sandbox.orchestration import sidecar_lifecycle, wiring
from docker_sandbox.orchestration.sidecar_lifecycle import (
    _build_mcp_sidecar_cleanup_commands,
    _start_mcp_sidecar,
    _wait_for_mcp_sidecar_ready,
    _write_mcp_sidecar_logs,
)
from docker_sandbox.orchestration.types import RunContext
from docker_sandbox.sidecars import mcp


def test_start_mcp_sidecar_rebuilds_image_before_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP startup refreshes the dev image before running the sidecar."""
    configuration = _create_network_configuration()
    run_context = _create_mcp_run_context(tmp_path)
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

    commands = _start_mcp_sidecar(configuration, run_context)

    expected_commands = [
        mcp.build_image_inspect_command(),
        mcp.build_image_build_command(configuration),
        _build_expected_mcp_run_command(configuration, run_context),
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
    run_context = _create_mcp_run_context(tmp_path)
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

    _wait_for_mcp_sidecar_ready(configuration, run_context)

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
    run_context = _create_mcp_run_context(tmp_path)

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
            run_context,
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
    run_context = _create_mcp_run_context(tmp_path)

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

    _write_mcp_sidecar_logs(configuration, run_context)

    metadata = json.loads((tmp_path / "mcp-sidecar-metadata.json").read_text())
    assert (tmp_path / "mcp-sidecar-stdout.txt").read_text() == "sidecar stdout\n"
    assert (tmp_path / "mcp-sidecar-stderr.txt").read_text() == "sidecar stderr\n"
    assert metadata == {
        "container_name": "mcp-sidecar-1",
        "image_name": "mcp-sidecar:dev",
        "log_command": ["docker", "logs", "mcp-sidecar-1"],
        "log_returncode": 0,
    }


def test_build_run_records_uses_start_result_and_cleanup_commands() -> None:
    """Verify sidecar lifecycle builds generic run records."""
    run_context = RunContext(
        timestamp="1",
        run_id="run-1",
        run_directory=Path(".docker_sandbox/runs/run-1"),
        container_name="sandbox-agent-run-1",
        remote_run_directory="/sandbox-work/run-1",
        allowed_directory="/sandbox-work/run-1/allowed",
        denied_directory="/sandbox-denied",
        network_name="sandbox-agent-net-1",
        gateway_container_name="sandbox-agent-gateway-1",
        mcp_sidecar_container_name="mcp-sidecar-1",
    )
    start_result = sidecar_lifecycle.SidecarStartResult(
        sidecar_names=(wiring.SQUID_GATEWAY, wiring.MCP),
        start_commands={
            wiring.SQUID_GATEWAY: [["docker", "network", "create"]],
            wiring.MCP: [["docker", "run", "mcp"]],
        },
        gateway_ip_address="172.18.0.2",
    )
    cleanup_commands = {
        wiring.SQUID_GATEWAY: [["docker", "network", "rm"]],
        wiring.MCP: [["docker", "rm", "mcp"]],
    }

    records = sidecar_lifecycle.build_run_records(
        start_result,
        run_context,
        cleanup_commands,
    )

    assert [record.name for record in records] == [wiring.SQUID_GATEWAY, wiring.MCP]
    assert records[0].container_name == "sandbox-agent-gateway-1"
    assert records[1].container_name == "mcp-sidecar-1"
    assert records[0].start_commands == (["docker", "network", "create"],)
    assert records[1].cleanup_commands == (["docker", "rm", "mcp"],)


def test_flatten_cleanup_commands_uses_dependency_safe_order() -> None:
    """Verify sidecar cleanup command flattening preserves removal order."""
    cleanup_commands = {
        wiring.SQUID_GATEWAY: [["docker", "rm", "squid"], ["docker", "network", "rm"]],
        wiring.MCP: [["docker", "rm", "mcp"]],
        wiring.OLLAMA: [["docker", "rm", "ollama"]],
    }

    commands = sidecar_lifecycle.flatten_cleanup_commands(cleanup_commands)

    assert commands == (
        ["docker", "rm", "mcp"],
        ["docker", "rm", "ollama"],
        ["docker", "rm", "squid"],
        ["docker", "network", "rm"],
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


def _create_mcp_run_context(run_directory: Path) -> RunContext:
    return RunContext(
        timestamp="1",
        run_id="run-1",
        run_directory=run_directory,
        container_name="sandbox-agent-run-1",
        remote_run_directory="/sandbox-work/run-1",
        allowed_directory="/sandbox-work/run-1/allowed",
        denied_directory="/sandbox-denied",
        network_name="sandbox-agent-net-1",
        mcp_sidecar_container_name="mcp-sidecar-1",
    )


def _build_expected_mcp_run_command(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> list[str]:
    no_proxy_hosts = wiring.build_mcp_sidecar_no_proxy_hosts(configuration)
    database_options = wiring.build_mcp_sidecar_database_environment_options(
        configuration
    )
    return mcp.build_run_command(
        configuration,
        run_context.run_directory,
        run_context.network_name or "",
        run_context.mcp_sidecar_container_name or "",
        no_proxy_hosts,
        database_options,
    )
