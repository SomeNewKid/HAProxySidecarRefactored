"""Tests for Docker sandbox run result assembly."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import DockerConfiguration, NetworkGatewayProfile
from docker_sandbox.orchestration import results, wiring
from docker_sandbox.orchestration.sidecar_lifecycle import SidecarStartResult
from docker_sandbox.orchestration.types import CommandResult, RunContext


def test_build_docker_run_result_includes_agent_and_sidecar_lifecycle_data() -> None:
    """Verify result assembly includes cleanup commands and sidecar records."""
    configuration = _create_network_configuration()
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
    command = ["docker", "run", "sandbox-agent-run-1"]
    completed = CommandResult(returncode=7, stdout="out", stderr="err")
    sidecar_start_result = SidecarStartResult(
        sidecar_names=(wiring.SQUID_GATEWAY, wiring.MCP),
        start_commands={
            wiring.SQUID_GATEWAY: [["docker", "network", "create"]],
            wiring.MCP: [["docker", "run", "mcp"]],
        },
        gateway_ip_address="172.18.0.2",
    )

    result = results.build_docker_run_result(
        configuration,
        run_context,
        command,
        completed,
        sidecar_start_result,
    )

    assert result.image_name == configuration.profile.image_name
    assert result.profile_name == configuration.profile.name
    assert result.container_name == "sandbox-agent-run-1"
    assert result.command == command
    assert result.remove_command == ["docker", "rm", "--force", "sandbox-agent-run-1"]
    assert result.exit_code == 7
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.network_name == "sandbox-agent-net-1"
    assert result.gateway_ip_address == "172.18.0.2"
    assert [sidecar.name for sidecar in result.sidecars] == [
        wiring.SQUID_GATEWAY,
        wiring.MCP,
    ]
    assert result.cleanup_commands == (
        ["docker", "rm", "--force", "mcp-sidecar-1"],
        ["docker", "rm", "--force", "sandbox-agent-gateway-1"],
        ["docker", "network", "rm", "sandbox-agent-net-1"],
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
