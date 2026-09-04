"""Sidecar lifecycle orchestration for Docker sandbox runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from docker_sandbox.models import DockerConfiguration, SidecarRunRecord
from docker_sandbox.orchestration import wiring
from docker_sandbox.orchestration.types import RunContext
from docker_sandbox.sidecars import (
    code_execution,
    haproxy,
    jina_reader,
    mcp,
    ollama,
    squid_gateway,
)


@dataclass(frozen=True)
class SidecarStartResult:
    """Sidecar startup state needed by later sandbox orchestration phases."""

    sidecar_names: tuple[str, ...]
    start_commands: dict[str, list[list[str]] | None]
    gateway_ip_address: str | None = None


def start_all(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> SidecarStartResult:
    """Start configured sidecars in order and wait for readiness."""
    gateway_ip_address = None
    sidecar_names = wiring.ordered_sidecars(configuration)
    sidecar_start_commands: dict[str, list[list[str]] | None] = {}
    for sidecar_name in sidecar_names:
        if sidecar_name == wiring.SQUID_GATEWAY:
            commands, gateway_ip_address = squid_gateway.start_gateway(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.gateway_container_name,
            )
            sidecar_start_commands[sidecar_name] = commands
        elif sidecar_name == wiring.JINA_READER:
            sidecar_start_commands[sidecar_name] = jina_reader.start(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.jina_reader_container_name,
            )
            jina_reader.wait_until_ready(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.jina_reader_container_name,
                jina_reader._JINA_READER_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.CODE_EXECUTION:
            sidecar_start_commands[sidecar_name] = code_execution.start(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.code_sidecar_container_name,
            )
            code_execution.wait_until_ready(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.code_sidecar_container_name,
                code_execution._CODE_SIDECAR_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.HAPROXY:
            sidecar_start_commands[sidecar_name] = haproxy.start(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.haproxy_sidecar_container_name,
            )
            haproxy.wait_until_ready(
                configuration,
                run_context.run_directory,
                run_context.haproxy_sidecar_container_name,
                haproxy._HAPROXY_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.OLLAMA:
            sidecar_start_commands[sidecar_name] = ollama.start(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.ollama_sidecar_container_name,
            )
            ollama.wait_until_ready(
                configuration,
                run_context.run_directory,
                run_context.network_name,
                run_context.ollama_sidecar_container_name,
                ollama._OLLAMA_READINESS_INTERVALS_SECONDS,
            )
        elif sidecar_name == wiring.MCP:
            sidecar_start_commands[sidecar_name] = _start_mcp_sidecar(
                configuration,
                run_context,
            )
            _wait_for_mcp_sidecar_ready(configuration, run_context)

    return SidecarStartResult(
        sidecar_names=sidecar_names,
        start_commands=sidecar_start_commands,
        gateway_ip_address=gateway_ip_address,
    )


def write_logs(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> None:
    """Write Docker logs for all sidecars that may have started."""
    _write_mcp_sidecar_logs(configuration, run_context)
    jina_reader.write_logs(
        configuration,
        run_context.run_directory,
        run_context.jina_reader_container_name,
    )
    code_execution.write_logs(
        configuration,
        run_context.run_directory,
        run_context.code_sidecar_container_name,
    )
    haproxy.write_logs(
        configuration,
        run_context.run_directory,
        run_context.haproxy_sidecar_container_name,
    )
    ollama.write_logs(
        configuration,
        run_context.run_directory,
        run_context.ollama_sidecar_container_name,
    )
    squid_gateway.write_logs(
        configuration,
        run_context.run_directory,
        run_context.gateway_container_name,
    )


def build_cleanup_commands(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> dict[str, list[list[str]] | None]:
    """Build cleanup commands for configured sidecars and the sandbox network."""
    return {
        wiring.MCP: _build_mcp_sidecar_cleanup_commands(
            configuration,
            run_context.mcp_sidecar_container_name,
        ),
        wiring.JINA_READER: jina_reader.build_cleanup_commands(
            configuration,
            run_context.jina_reader_container_name,
        ),
        wiring.CODE_EXECUTION: code_execution.build_cleanup_commands(
            configuration,
            run_context.code_sidecar_container_name,
        ),
        wiring.HAPROXY: haproxy.build_cleanup_commands(
            configuration,
            run_context.haproxy_sidecar_container_name,
        ),
        wiring.OLLAMA: ollama.build_cleanup_commands(
            configuration,
            run_context.ollama_sidecar_container_name,
        ),
        wiring.SQUID_GATEWAY: squid_gateway.build_cleanup_commands(
            configuration,
            run_context.network_name,
            run_context.gateway_container_name,
        ),
    }


def build_run_records(
    start_result: SidecarStartResult,
    run_context: RunContext,
    sidecar_cleanup_commands: Mapping[str, list[list[str]] | None],
) -> tuple[SidecarRunRecord, ...]:
    """Build generic sidecar run records for the Docker run result."""
    sidecar_container_names = _build_sidecar_container_names(run_context)
    records = []
    for sidecar_name in start_result.sidecar_names:
        start_commands = start_result.start_commands.get(sidecar_name) or []
        cleanup_commands = sidecar_cleanup_commands.get(sidecar_name) or []
        records.append(
            SidecarRunRecord(
                name=sidecar_name,
                container_name=sidecar_container_names[sidecar_name],
                start_commands=tuple(start_commands),
                cleanup_commands=tuple(cleanup_commands),
            )
        )

    return tuple(records)


def flatten_cleanup_commands(
    sidecar_cleanup_commands: Mapping[str, list[list[str]] | None],
) -> tuple[list[str], ...]:
    """Return cleanup commands in dependency-safe removal order."""
    commands = []
    for sidecar_name in (
        wiring.MCP,
        wiring.JINA_READER,
        wiring.CODE_EXECUTION,
        wiring.HAPROXY,
        wiring.OLLAMA,
        wiring.SQUID_GATEWAY,
    ):
        cleanup_commands = sidecar_cleanup_commands.get(sidecar_name)
        if cleanup_commands is not None:
            commands.extend(cleanup_commands)

    return tuple(commands)


def _build_sidecar_container_names(run_context: RunContext) -> dict[str, str | None]:
    return {
        wiring.SQUID_GATEWAY: run_context.gateway_container_name,
        wiring.MCP: run_context.mcp_sidecar_container_name,
        wiring.JINA_READER: run_context.jina_reader_container_name,
        wiring.CODE_EXECUTION: run_context.code_sidecar_container_name,
        wiring.HAPROXY: run_context.haproxy_sidecar_container_name,
        wiring.OLLAMA: run_context.ollama_sidecar_container_name,
    }


def _start_mcp_sidecar(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> list[list[str]] | None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return mcp.start(
        configuration,
        run_context.run_directory,
        run_context.network_name,
        run_context.mcp_sidecar_container_name,
        wiring.build_mcp_sidecar_no_proxy_hosts(configuration),
        wiring.build_mcp_sidecar_database_environment_options(configuration),
    )


def _wait_for_mcp_sidecar_ready(
    configuration: DockerConfiguration,
    run_context: RunContext,
    intervals_seconds: tuple[float, ...] = mcp._MCP_SIDECAR_READINESS_INTERVALS_SECONDS,
) -> None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return

    mcp.wait_until_ready(
        configuration,
        run_context.run_directory,
        run_context.network_name,
        run_context.mcp_sidecar_container_name,
        intervals_seconds,
    )


def _write_mcp_sidecar_logs(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return

    mcp.write_logs(run_context.run_directory, run_context.mcp_sidecar_container_name)


def _build_mcp_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not wiring.should_start_mcp_sidecar(configuration):
        return None

    return mcp.build_cleanup_commands(mcp_sidecar_container_name)
