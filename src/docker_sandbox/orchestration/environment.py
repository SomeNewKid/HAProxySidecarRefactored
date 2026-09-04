"""Run environment names and paths for Docker sandbox orchestration."""

from __future__ import annotations

from docker_sandbox.agent_container import run as agent_run
from docker_sandbox.models import DockerConfiguration
from docker_sandbox.orchestration import wiring
from docker_sandbox.orchestration.types import RunContext

_AGENT_CONTAINER_NAME_PREFIX = "sandbox-agent-run"
_NETWORK_NAME_PREFIX = "sandbox-agent-net"
_SQUID_GATEWAY_CONTAINER_NAME_PREFIX = "sandbox-agent-gateway"
_MCP_SIDECAR_CONTAINER_NAME_PREFIX = "mcp-sidecar"
_JINA_READER_CONTAINER_NAME_PREFIX = "jina-reader"
_CODE_SIDECAR_CONTAINER_NAME_PREFIX = "code-sidecar"
_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX = "haproxy-sidecar"
_OLLAMA_SIDECAR_CONTAINER_NAME_PREFIX = "ollama-sidecar"


def create_run_context(
    configuration: DockerConfiguration,
    timestamp: str,
) -> RunContext:
    """Create derived names and paths for one sandbox run."""
    run_id = f"run-{timestamp}"
    run_directory = configuration.base_directory / "runs" / run_id
    remote_run_directory = build_remote_run_directory(configuration, run_id)
    return RunContext(
        timestamp=timestamp,
        run_id=run_id,
        run_directory=run_directory,
        container_name=build_container_name(_AGENT_CONTAINER_NAME_PREFIX, timestamp),
        remote_run_directory=remote_run_directory,
        allowed_directory=agent_run.build_allowed_directory(
            configuration,
            remote_run_directory,
        ),
        denied_directory=agent_run.build_denied_directory(
            configuration,
            remote_run_directory,
        ),
        network_name=build_network_name(configuration, timestamp),
        gateway_container_name=(
            build_container_name(_SQUID_GATEWAY_CONTAINER_NAME_PREFIX, timestamp)
            if wiring.should_start_squid_gateway(configuration)
            else None
        ),
        mcp_sidecar_container_name=build_mcp_sidecar_container_name(
            configuration,
            timestamp,
        ),
        jina_reader_container_name=(
            build_container_name(_JINA_READER_CONTAINER_NAME_PREFIX, timestamp)
            if wiring.should_start_jina_reader(configuration)
            else None
        ),
        code_sidecar_container_name=(
            build_container_name(_CODE_SIDECAR_CONTAINER_NAME_PREFIX, timestamp)
            if wiring.should_start_code_sidecar(configuration)
            else None
        ),
        haproxy_sidecar_container_name=(
            build_container_name(_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX, timestamp)
            if wiring.should_start_haproxy_sidecar(configuration)
            else None
        ),
        ollama_sidecar_container_name=(
            build_container_name(_OLLAMA_SIDECAR_CONTAINER_NAME_PREFIX, timestamp)
            if wiring.should_start_ollama_sidecar(configuration)
            else None
        ),
    )


def build_remote_run_directory(
    configuration: DockerConfiguration,
    run_id: str,
) -> str:
    """Build the remote working directory for one sandbox run."""
    remote_root = configuration.profile.remote_run_root.rstrip("/")
    return f"{remote_root}/{run_id}"


def build_mcp_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    """Build the MCP sidecar container name when this run uses MCP."""
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return build_container_name(_MCP_SIDECAR_CONTAINER_NAME_PREFIX, timestamp)


def build_container_name(prefix: str, timestamp: str) -> str:
    """Build a timestamped sandbox container name."""
    return f"{prefix}-{timestamp}"


def build_network_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    """Build the sandbox network name when this run uses a network gateway."""
    if configuration.profile.network_gateway is None:
        return None

    return f"{_NETWORK_NAME_PREFIX}-{timestamp}"
