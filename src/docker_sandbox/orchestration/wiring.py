"""Hard-coded sidecar orchestration wiring rules."""

from __future__ import annotations

from docker_sandbox.models import DockerConfiguration, SandboxRunTarget
from docker_sandbox.sidecars import (
    code_execution,
    haproxy,
    jina_reader,
    mcp,
    ollama,
    squid_gateway,
)

SQUID_GATEWAY = "squid_gateway"
JINA_READER = "jina_reader"
CODE_EXECUTION = "code_execution"
HAPROXY = "haproxy"
OLLAMA = "ollama"
MCP = "mcp"

SIDECAR_START_ORDER = (
    SQUID_GATEWAY,
    JINA_READER,
    CODE_EXECUTION,
    HAPROXY,
    OLLAMA,
    MCP,
)

_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_URL"
_MARIADB_HOST_ENVIRONMENT_VARIABLE = "MARIADB_HOST"
_MARIADB_PORT_ENVIRONMENT_VARIABLE = "MARIADB_PORT"
_MARIADB_DATABASE_ENVIRONMENT_VARIABLE = "MARIADB_DATABASE"
_MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE = "SANDBOX_TESTER_MARIADB_CREDENTIALS"
_MARIADB_DATABASE_NAME = "agent_allowed"
_MARIADB_DEFAULT_PORT = 3306


def ordered_sidecars(configuration: DockerConfiguration) -> tuple[str, ...]:
    """Return configured sidecars in orchestration start order."""
    return tuple(
        sidecar_name
        for sidecar_name in SIDECAR_START_ORDER
        if should_start_sidecar(configuration, sidecar_name)
    )


def should_start_sidecar(
    configuration: DockerConfiguration,
    sidecar_name: str,
) -> bool:
    """Return whether a named sidecar should be started for a run."""
    if sidecar_name == SQUID_GATEWAY:
        return should_start_squid_gateway(configuration)
    if sidecar_name == JINA_READER:
        return should_start_jina_reader(configuration)
    if sidecar_name == CODE_EXECUTION:
        return should_start_code_sidecar(configuration)
    if sidecar_name == HAPROXY:
        return should_start_haproxy_sidecar(configuration)
    if sidecar_name == OLLAMA:
        return should_start_ollama_sidecar(configuration)
    if sidecar_name == MCP:
        return should_start_mcp_sidecar(configuration)

    raise ValueError(f"Unknown sidecar: {sidecar_name}")


def sidecar_dependencies(sidecar_name: str) -> tuple[str, ...]:
    """Return the plain-code dependency list for a named sidecar."""
    if sidecar_name == SQUID_GATEWAY:
        return ()
    if sidecar_name in (JINA_READER, CODE_EXECUTION, HAPROXY, OLLAMA):
        return (SQUID_GATEWAY,)
    if sidecar_name == MCP:
        return (SQUID_GATEWAY, JINA_READER, CODE_EXECUTION, HAPROXY)

    raise ValueError(f"Unknown sidecar: {sidecar_name}")


def should_start_squid_gateway(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Squid gateway."""
    return configuration.profile.network_gateway is not None


def should_start_mcp_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the MCP sidecar."""
    has_mcp_exposure = bool(
        configuration.mcp_sidecar_tools or configuration.mcp_sidecar_resources
    )
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and has_mcp_exposure
    )


def should_start_jina_reader(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Jina Reader sidecar."""
    return jina_reader.should_start(configuration)


def should_start_code_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Code sidecar."""
    return code_execution.should_start(configuration)


def should_start_haproxy_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the HAProxy sidecar."""
    return haproxy.should_start(configuration)


def should_start_ollama_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Ollama sidecar."""
    return ollama.should_start(configuration)


def apply_agent_sidecar_environment(
    container_environment: dict[str, str],
    configuration: DockerConfiguration,
    gateway_ip_address: str | None = None,
) -> None:
    """Add sidecar-derived environment variables for the AI agent container."""
    gateway = configuration.profile.network_gateway
    if gateway is not None:
        squid_gateway.apply_agent_environment(
            container_environment,
            gateway,
            gateway_ip_address,
            build_agent_gateway_no_proxy_hosts(configuration),
        )
    if should_start_mcp_sidecar(configuration):
        mcp_sidecar_url = f"http://{mcp.alias()}:{mcp.port()}/mcp"
        container_environment[_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE] = mcp_sidecar_url
    ollama.apply_agent_environment(container_environment, configuration)
    remove_agent_database_environment(container_environment)


def build_agent_gateway_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    """Return gateway no-proxy hosts contributed by sidecar wiring."""
    hosts = []
    if should_start_mcp_sidecar(configuration):
        hosts.append(mcp.alias())
    if should_start_ollama_sidecar(configuration):
        hosts.append(ollama.alias())

    return tuple(hosts)


def build_mcp_sidecar_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    """Return MCP no-proxy hosts contributed by sidecar wiring."""
    hosts = []
    if should_start_haproxy_sidecar(configuration):
        hosts.append(haproxy.alias())

    return mcp.build_no_proxy_hosts(tuple(hosts))


def build_mcp_sidecar_database_environment_options(
    configuration: DockerConfiguration,
) -> list[str]:
    """Return MCP environment options for the HAProxy database path."""
    if not should_start_haproxy_sidecar(configuration):
        return []

    haproxy_configuration = haproxy.get_configuration(configuration)
    port = resolve_mariadb_proxy_port(haproxy_configuration.ports)
    return [
        "--env",
        f"{_MARIADB_HOST_ENVIRONMENT_VARIABLE}={haproxy.alias()}",
        "--env",
        f"{_MARIADB_PORT_ENVIRONMENT_VARIABLE}={port}",
        "--env",
        f"{_MARIADB_DATABASE_ENVIRONMENT_VARIABLE}={_MARIADB_DATABASE_NAME}",
        "--env",
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    ]


def resolve_mariadb_proxy_port(ports: tuple[int, ...]) -> int:
    """Return the MariaDB port exposed through HAProxy."""
    if _MARIADB_DEFAULT_PORT in ports:
        return _MARIADB_DEFAULT_PORT

    return ports[0]


def remove_agent_database_environment(environment: dict[str, str]) -> None:
    """Remove host database variables from the AI agent environment."""
    for name in (
        _MARIADB_HOST_ENVIRONMENT_VARIABLE,
        _MARIADB_PORT_ENVIRONMENT_VARIABLE,
        _MARIADB_DATABASE_ENVIRONMENT_VARIABLE,
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    ):
        environment.pop(name, None)


def database_environment_variable_names() -> set[str]:
    """Return host database environment variable names blocked from the agent."""
    return {
        _MARIADB_HOST_ENVIRONMENT_VARIABLE,
        _MARIADB_PORT_ENVIRONMENT_VARIABLE,
        _MARIADB_DATABASE_ENVIRONMENT_VARIABLE,
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    }
