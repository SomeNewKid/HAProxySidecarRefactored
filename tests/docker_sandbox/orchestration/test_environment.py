"""Tests for Docker sandbox run environment derivation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import environment
from docker_sandbox.sandbox_spec import resolve_ollama_image_name


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

    context = environment.create_run_context(
        configuration,
        "2026-07-20-16-00-00",
    )

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

    container_name = environment.build_mcp_sidecar_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name == "mcp-sidecar-2026-07-20-16-00-00"


def test_mcp_sidecar_container_name_is_omitted_without_network() -> None:
    """Verify no-network runs do not get an MCP sidecar container."""
    configuration = _create_locked_down_configuration()

    container_name = environment.build_mcp_sidecar_container_name(
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

    container_name = environment.build_mcp_sidecar_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name is None


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


def _create_locked_down_configuration() -> DockerConfiguration:
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=hardening.base_locked_down_profile(),
    )
