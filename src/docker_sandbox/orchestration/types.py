"""Neutral types shared by Docker sandbox orchestration code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    """Captured result from a command run during sandbox orchestration."""

    returncode: int
    stdout: str
    stderr: str
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunContext:
    """Names and paths derived for a single sandbox run."""

    timestamp: str
    run_id: str
    run_directory: Path
    container_name: str
    remote_run_directory: str
    allowed_directory: str
    denied_directory: str
    network_name: str | None = None
    gateway_container_name: str | None = None
    mcp_sidecar_container_name: str | None = None
    jina_reader_container_name: str | None = None
    code_sidecar_container_name: str | None = None
    haproxy_sidecar_container_name: str | None = None
    ollama_sidecar_container_name: str | None = None


@dataclass(frozen=True)
class SidecarPlan:
    """Planned commands and artifacts for one sidecar container."""

    name: str
    container_name: str | None
    start_commands: tuple[tuple[str, ...], ...] = ()
    cleanup_commands: tuple[tuple[str, ...], ...] = ()
    readiness_results_file_name: str | None = None
    log_file_names: tuple[str, ...] = ()
