"""Tests for run."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import run as agent_run
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.profiles import LOCKED_DOWN_PROFILE_NAME, get_docker_profile
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    mcp,
)


def test_agent_docker_run_command_includes_mcp_sidecar_url() -> None:
    """Verify the agent Docker command passes MCP sidecar connection info."""
    configuration = _create_network_configuration()

    command = agent_run.build_docker_run_command(
        configuration=configuration,
        run_directory=Path(".docker_sandbox") / "runs" / "run-1",
        container_name="sandbox-agent-run-1",
        remote_run_directory="/tmp/sandbox-tester/run-1",
        network_name="sandbox-agent-net-1",
    )

    env_values = _option_values(command, "--env")
    assert "MCP_SIDECAR_URL=http://mcp-sidecar:8000/mcp" in env_values


def test_agent_docker_run_command_includes_ollama_environment(
    tmp_path: Path,
) -> None:
    """Verify Ollama agent Docker env does not replace hosted OpenAI settings."""
    configuration = _create_ollama_configuration(tmp_path)

    command = agent_run.build_docker_run_command(
        configuration=configuration,
        run_directory=Path(".docker_sandbox") / "runs" / "run-1",
        container_name="sandbox-agent-run-1",
        remote_run_directory="/tmp/sandbox-tester/run-1",
        network_name="sandbox-agent-net-1",
        environment_variables={"OPENAI_API_KEY": "host-secret"},
        local_environment_variable_names=frozenset({"OPENAI_API_KEY"}),
    )

    env_values = _option_values(command, "--env")
    assert "OLLAMA_BASE_URL=http://ollama-sidecar:11434" in env_values
    assert "OLLAMA_MODEL=phi4-mini:latest" in env_values
    assert not any(value.startswith("OPENAI_BASE_URL=") for value in env_values)
    assert "OPENAI_API_KEY" in env_values
    assert "OPENAI_API_KEY=ollama" not in env_values
    no_proxy_value = next(
        value for value in env_values if value.startswith("NO_PROXY=")
    )
    assert "ollama-sidecar" in no_proxy_value.split("=", 1)[1].split(",")


def test_agent_environment_includes_mcp_sidecar_url() -> None:
    """Verify the agent container receives the MCP sidecar URL."""
    configuration = _create_network_configuration()

    environment = agent_run.build_container_environment(configuration, {})

    assert environment["MCP_SIDECAR_URL"] == "http://mcp-sidecar:8000/mcp"
    assert "mcp-sidecar" in environment["NO_PROXY"].split(",")
    assert "mcp-sidecar" in environment["no_proxy"].split(",")


def test_agent_environment_includes_ollama_settings_without_replacing_openai(
    tmp_path: Path,
) -> None:
    """Verify Ollama runs keep hosted OpenAI settings available."""
    configuration = _create_ollama_configuration(tmp_path)

    environment = agent_run.build_container_environment(
        configuration,
        {"OPENAI_API_KEY": "host-secret"},
    )

    assert environment["OLLAMA_BASE_URL"] == "http://ollama-sidecar:11434"
    assert environment["OLLAMA_MODEL"] == "phi4-mini:latest"
    assert "OPENAI_BASE_URL" not in environment
    assert environment["OPENAI_API_KEY"] == "host-secret"
    assert "ollama-sidecar" in environment["NO_PROXY"].split(",")
    assert "ollama-sidecar" in environment["no_proxy"].split(",")


def test_agent_environment_omits_database_settings_with_haproxy() -> None:
    """Verify MariaDB settings are not passed into the AI agent container."""
    configuration = _create_haproxy_configuration()

    environment = agent_run.build_container_environment(
        configuration,
        {
            "SANDBOX_TESTER_MARIADB_CREDENTIALS": "sandbox_tester.secret",
        },
    )

    assert "MARIADB_HOST" not in environment
    assert "MARIADB_PORT" not in environment
    assert "MARIADB_DATABASE" not in environment
    assert "SANDBOX_TESTER_MARIADB_CREDENTIALS" not in environment


def test_agent_environment_omits_mcp_sidecar_url_without_network() -> None:
    """Verify no-network agent containers do not receive MCP sidecar settings."""
    configuration = _create_locked_down_configuration()

    environment = agent_run.build_container_environment(configuration, {})

    assert "MCP_SIDECAR_URL" not in environment


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
        profile=get_docker_profile(LOCKED_DOWN_PROFILE_NAME),
    )


def _create_network_configuration() -> DockerConfiguration:
    profile = get_docker_profile(LOCKED_DOWN_PROFILE_NAME)
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
