"""Hard-coded sidecar orchestration wiring rules."""

from __future__ import annotations

from docker_sandbox.models import DockerConfiguration, SandboxRunTarget
from docker_sandbox.orchestration import network
from docker_sandbox.sidecars import haproxy, ollama, squid_gateway

SQUID_GATEWAY = "squid_gateway"
JINA_READER = "jina_reader"
CODE_EXECUTION = "code_execution"
HAPROXY = "haproxy"
OLLAMA = "ollama"
MCP = "mcp"
JINA_READER_CAPABILITY = "jina_reader"
CODE_EXECUTION_CAPABILITY = "code_execution"
HAPROXY_CAPABILITY = "haproxy"
OLLAMA_CAPABILITY = "ollama"

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


def ordered_sidecars(configuration: DockerConfiguration) -> tuple[str, ...]:
    """Return configured sidecars in orchestration start order."""
    sidecars = []
    if should_start_squid_gateway(configuration):
        sidecars.append(SQUID_GATEWAY)
    if should_start_jina_reader(configuration):
        sidecars.append(JINA_READER)
    if should_start_code_sidecar(configuration):
        sidecars.append(CODE_EXECUTION)
    if should_start_haproxy_sidecar(configuration):
        sidecars.append(HAPROXY)
    if should_start_ollama_sidecar(configuration):
        sidecars.append(OLLAMA)
    if should_start_mcp_sidecar(configuration):
        sidecars.append(MCP)

    return tuple(sidecars)


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
    return _should_start_capability_sidecar(configuration, JINA_READER_CAPABILITY)


def should_start_code_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Code sidecar."""
    return _should_start_capability_sidecar(configuration, CODE_EXECUTION_CAPABILITY)


def should_start_haproxy_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the HAProxy sidecar."""
    return _should_start_capability_sidecar(configuration, HAPROXY_CAPABILITY)


def should_start_ollama_sidecar(configuration: DockerConfiguration) -> bool:
    """Return whether this run needs the Ollama sidecar."""
    return _should_start_capability_sidecar(configuration, OLLAMA_CAPABILITY)


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
        mcp_sidecar_url = network.http_url(
            network.MCP_SIDECAR_ALIAS,
            network.MCP_SIDECAR_PORT,
            "/mcp",
        )
        container_environment[_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE] = mcp_sidecar_url
    if should_start_ollama_sidecar(configuration):
        ollama.apply_agent_environment(container_environment, configuration)
    remove_agent_database_environment(container_environment)


def build_agent_gateway_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    """Return gateway no-proxy hosts contributed by sidecar wiring."""
    hosts = []
    if should_start_mcp_sidecar(configuration):
        hosts.append(network.MCP_SIDECAR_ALIAS)
    if should_start_ollama_sidecar(configuration):
        hosts.append(network.OLLAMA_SIDECAR_ALIAS)

    return tuple(hosts)


def build_mcp_sidecar_no_proxy_hosts(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    """Return MCP no-proxy hosts contributed by sidecar wiring."""
    hosts = [
        network.LOCALHOST,
        network.LOOPBACK_IPV4_ADDRESS,
        network.MCP_SIDECAR_ALIAS,
        network.JINA_READER_ALIAS,
        network.CODE_SIDECAR_ALIAS,
    ]
    if should_start_haproxy_sidecar(configuration):
        hosts.append(network.HAPROXY_SIDECAR_ALIAS)

    return tuple(hosts)


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
        f"{_MARIADB_HOST_ENVIRONMENT_VARIABLE}={network.HAPROXY_SIDECAR_ALIAS}",
        "--env",
        f"{_MARIADB_PORT_ENVIRONMENT_VARIABLE}={port}",
        "--env",
        f"{_MARIADB_DATABASE_ENVIRONMENT_VARIABLE}={_MARIADB_DATABASE_NAME}",
        "--env",
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    ]


def resolve_mariadb_proxy_port(ports: tuple[int, ...]) -> int:
    """Return the MariaDB port exposed through HAProxy."""
    if network.MARIADB_DEFAULT_PORT in ports:
        return network.MARIADB_DEFAULT_PORT

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


def _should_start_capability_sidecar(
    configuration: DockerConfiguration,
    capability: str,
) -> bool:
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and capability in configuration.enabled_capabilities
    )
