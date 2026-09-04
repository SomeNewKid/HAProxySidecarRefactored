"""Tests for mcp."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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


def test_mcp_sidecar_database_env_falls_back_to_first_haproxy_port() -> None:
    """Verify non-MariaDB HAProxy configs still produce one MCP port value."""
    configuration = _create_haproxy_configuration(ports=(5432,))

    command = _build_expected_mcp_run_command(
        configuration,
        Path(".docker_sandbox") / "runs" / "run-1",
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    env_values = _option_values(command, "--env")
    assert "MARIADB_PORT=5432" in env_values


def test_mcp_sidecar_database_env_prefers_mariadb_port() -> None:
    """Verify MCP uses port 3306 when HAProxy exposes multiple ports."""
    configuration = _create_haproxy_configuration(ports=(5432, 3306))

    command = _build_expected_mcp_run_command(
        configuration,
        Path(".docker_sandbox") / "runs" / "run-1",
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    env_values = _option_values(command, "--env")
    assert "MARIADB_PORT=3306" in env_values


def test_mcp_sidecar_health_probe_script_targets_health_route() -> None:
    """Verify the MCP sidecar readiness probe uses the health endpoint."""
    script = mcp.build_health_probe_script()

    assert "http://mcp-sidecar:8000/health" in script
    assert "data.get('status') != 'ok'" in script


def test_mcp_sidecar_image_commands_use_static_dockerfile() -> None:
    """Verify the MCP sidecar image commands target the static Dockerfile."""
    configuration = _create_network_configuration()

    inspect_command = mcp.build_image_inspect_command()
    build_command = mcp.build_image_build_command(configuration)

    assert inspect_command == ["docker", "image", "inspect", "mcp-sidecar:dev"]
    assert build_command == [
        "docker",
        "build",
        "--file",
        str(Path("src") / "mcp_sidecar" / "dockerfile" / "Dockerfile"),
        "--tag",
        "mcp-sidecar:dev",
        ".",
    ]


def test_mcp_sidecar_run_command_includes_database_env_only_for_haproxy() -> None:
    """Verify only the MCP sidecar receives MariaDB settings through HAProxy."""
    command = _build_expected_mcp_run_command(
        _create_haproxy_configuration(),
        Path(".docker_sandbox") / "runs" / "run-1",
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    env_values = _option_values(command, "--env")
    assert (
        "NO_PROXY=localhost,127.0.0.1,mcp-sidecar,jina-reader,code-sidecar,haproxy-sidecar"
        in (env_values)
    )
    assert "MARIADB_HOST=haproxy-sidecar" in env_values
    assert "MARIADB_PORT=3306" in env_values
    assert "MARIADB_DATABASE=agent_allowed" in env_values
    assert "SANDBOX_TESTER_MARIADB_CREDENTIALS" in env_values
    assert "MARIADB_USER" not in env_values
    assert not any("sandbox_tester.secret" in value for value in env_values)


def test_mcp_sidecar_run_command_uses_internal_network_and_proxy() -> None:
    """Verify the sidecar is started on the internal network with Squid proxy env."""
    command = _build_expected_mcp_run_command(
        _create_network_configuration(),
        Path(".docker_sandbox") / "runs" / "run-1",
        "sandbox-agent-net-1",
        "mcp-sidecar-1",
    )

    assert command[:4] == ["docker", "run", "--detach", "--name"]
    assert "mcp-sidecar-1" in command
    assert _option_value(command, "--network") == "sandbox-agent-net-1"
    assert _option_value(command, "--network-alias") == "mcp-sidecar"
    assert "HTTP_PROXY=http://egress-gateway:3128" in _option_values(
        command,
        "--env",
    )
    assert "HTTPS_PROXY=http://egress-gateway:3128" in _option_values(
        command,
        "--env",
    )
    env_values = _option_values(command, "--env")
    assert "NO_PROXY=localhost,127.0.0.1,mcp-sidecar,jina-reader,code-sidecar" in (
        env_values
    )
    assert not any(value.startswith("MARIADB_") for value in env_values)
    assert "SANDBOX_TESTER_MARIADB_CREDENTIALS" not in env_values
    assert "JINA_READER_URL=http://jina-reader:8081" in _option_values(
        command,
        "--env",
    )
    assert "CODE_SIDECAR_URL=http://code-sidecar:8090" in _option_values(
        command,
        "--env",
    )
    assert (
        "MCP_SIDECAR_AUDIT_LOG_PATH=/mcp-sidecar-output/mcp-sidecar-tool-calls.jsonl"
    ) in _option_values(command, "--env")
    assert (
        "MCP_SIDECAR_EXPOSURE_PATH=/mcp-sidecar-config/mcp-sidecar-exposure.json"
    ) in _option_values(command, "--env")
    assert _option_values(command, "--mount") == [
        "type=bind,source=src\\mcp_sidecar,target=/opt/mcp-sidecar/mcp_sidecar,readonly",
        ("type=bind,source=.docker_sandbox\\runs\\run-1,target=/mcp-sidecar-output"),
        (
            "type=bind,source=.docker_sandbox\\runs\\run-1\\mcp-sidecar-exposure.json,"
            "target=/mcp-sidecar-config/mcp-sidecar-exposure.json,readonly"
        ),
    ]
    assert command[-8:] == [
        "mcp-sidecar:dev",
        "python",
        "-m",
        "mcp_sidecar",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]


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
