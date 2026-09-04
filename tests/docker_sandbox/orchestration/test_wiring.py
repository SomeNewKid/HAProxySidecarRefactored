"""Tests for Docker sandbox orchestration wiring."""

from __future__ import annotations

from pathlib import Path

from docker_sandbox.models import (
    DockerConfiguration,
    DockerProfile,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring


def test_wiring_omits_mcp_without_exposed_tools_or_resources() -> None:
    """Verify MCP is driven by exposure, not by a single sidecar capability."""
    configuration = _create_wired_configuration(mcp_sidecar_tools=())

    assert wiring.MCP not in wiring.ordered_sidecars(configuration)
    assert wiring.should_start_mcp_sidecar(configuration) is False


def test_wiring_applies_agent_sidecar_environment() -> None:
    """Verify agent sidecar environment is centralized in wiring."""
    configuration = _create_wired_configuration()
    environment = {"OPENAI_API_KEY": "host-secret", "MARIADB_HOST": "local"}

    wiring.apply_agent_sidecar_environment(
        environment,
        configuration,
        gateway_ip_address="172.18.0.2",
    )

    assert environment["HTTP_PROXY"] == "http://172.18.0.2:3128"
    assert environment["MCP_SIDECAR_URL"] == "http://mcp-sidecar:8000/mcp"
    assert environment["OLLAMA_BASE_URL"] == "http://ollama-sidecar:11434"
    assert environment["OLLAMA_MODEL"] == "qwen3:4b"
    assert "mcp-sidecar" in environment["NO_PROXY"].split(",")
    assert "ollama-sidecar" in environment["NO_PROXY"].split(",")
    assert "MARIADB_HOST" not in environment


def test_wiring_builds_mcp_database_environment_options() -> None:
    """Verify MCP gets database settings through HAProxy wiring."""
    configuration = _create_wired_configuration()

    assert wiring.build_mcp_sidecar_database_environment_options(configuration) == [
        "--env",
        "MARIADB_HOST=haproxy-sidecar",
        "--env",
        "MARIADB_PORT=3306",
        "--env",
        "MARIADB_DATABASE=agent_allowed",
        "--env",
        "SANDBOX_TESTER_MARIADB_CREDENTIALS",
    ]


def test_wiring_documents_plain_sidecar_dependencies() -> None:
    """Verify sidecar dependencies are explicit plain code."""
    assert wiring.sidecar_dependencies(wiring.SQUID_GATEWAY) == ()
    assert wiring.sidecar_dependencies(wiring.JINA_READER) == (wiring.SQUID_GATEWAY,)
    assert wiring.sidecar_dependencies(wiring.OLLAMA) == (wiring.SQUID_GATEWAY,)
    assert wiring.sidecar_dependencies(wiring.MCP) == (
        wiring.SQUID_GATEWAY,
        wiring.JINA_READER,
        wiring.CODE_EXECUTION,
        wiring.HAPROXY,
    )


def test_wiring_orders_enabled_sidecars() -> None:
    """Verify sidecar startup order is centralized in wiring."""
    configuration = _create_wired_configuration()

    assert wiring.ordered_sidecars(configuration) == (
        wiring.SQUID_GATEWAY,
        wiring.JINA_READER,
        wiring.CODE_EXECUTION,
        wiring.HAPROXY,
        wiring.OLLAMA,
        wiring.MCP,
    )


def _create_wired_configuration(
    mcp_sidecar_tools: tuple[str, ...] = ("get_active_items",),
) -> DockerConfiguration:
    profile = DockerProfile(
        name="locked-down",
        description="Locked down test profile.",
        image_name="sandbox-agent/sandbox-agent:locked-down",
        network_gateway=NetworkGatewayProfile(
            image_name="ubuntu/squid:latest",
            proxy_host="egress-gateway",
            proxy_port=3128,
            allowed_domains=("example.com",),
            no_proxy_hosts=("localhost",),
        ),
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
        enabled_capabilities=frozenset(
            {
                "jina_reader",
                "code_execution",
                "haproxy",
                "ollama",
            }
        ),
        mcp_sidecar_tools=mcp_sidecar_tools,
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=(3306,),
        ),
        ollama_models=("qwen3:4b",),
        ollama_image_name="sandbox-agent/ollama-sidecar:test",
    )
