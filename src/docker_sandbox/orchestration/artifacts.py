"""Artifact writing helpers for Docker sandbox orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .types import CommandResult


def write_json_artifact(path: Path, data: object) -> None:
    """Write JSON data with a trailing newline."""
    text = json.dumps(json_safe(data), indent=2)
    path.write_text(f"{text}\n", encoding="utf-8")


def write_text_artifact(path: Path, text: str) -> None:
    """Write text data as UTF-8."""
    path.write_text(text, encoding="utf-8")


def command_result_data(
    command: list[str] | tuple[str, ...],
    result: CommandResult,
) -> dict[str, object]:
    """Return JSON-safe command result data."""
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def write_docker_log_artifacts(
    *,
    run_directory: Path,
    log_result: CommandResult,
    log_file_name: str,
    stdout_file_name: str | None = None,
    stderr_file_name: str | None = None,
    metadata_file_name: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Write standard Docker log artifacts for a container."""
    if stdout_file_name is not None:
        write_text_artifact(run_directory / stdout_file_name, log_result.stdout)
    if stderr_file_name is not None:
        write_text_artifact(run_directory / stderr_file_name, log_result.stderr)

    if metadata_file_name is not None:
        metadata_data = {} if metadata is None else dict(metadata)
        metadata_data["log_command"] = list(log_result.command)
        metadata_data["log_returncode"] = log_result.returncode
        write_json_artifact(run_directory / metadata_file_name, metadata_data)

    write_json_artifact(
        run_directory / log_file_name,
        {
            "returncode": log_result.returncode,
            "stdout": log_result.stdout,
            "stderr": log_result.stderr,
        },
    )


def json_safe(value: object) -> object:
    """Convert common Python objects into JSON-safe values."""
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
