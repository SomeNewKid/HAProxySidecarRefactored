"""Persist Docker sandbox run results."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import DockerRunResult

_STDOUT_FILE_NAME = "stdout.txt"
_STDERR_FILE_NAME = "stderr.txt"
_METADATA_FILE_NAME = "run-metadata.json"


def save_run_results(result: DockerRunResult) -> None:
    """Save Docker container output and metadata to the run directory."""
    result.run_directory.mkdir(parents=True, exist_ok=True)
    _write_text(result.run_directory / _STDOUT_FILE_NAME, result.stdout)
    _write_text(result.run_directory / _STDERR_FILE_NAME, result.stderr)
    _write_json(
        result.run_directory / _METADATA_FILE_NAME,
        _create_metadata_data(result),
    )


def _create_metadata_data(result: DockerRunResult) -> dict[str, object]:
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "image_name": result.image_name,
        "profile_name": result.profile_name,
        "container_name": result.container_name,
        "network_name": result.network_name,
        "exit_code": result.exit_code,
        "command": result.command,
        "remove_command": result.remove_command,
        "gateway_ip_address": result.gateway_ip_address,
        "sidecars": [
            {
                "name": sidecar.name,
                "container_name": sidecar.container_name,
                "start_commands": sidecar.start_commands,
                "cleanup_commands": sidecar.cleanup_commands,
            }
            for sidecar in result.sidecars
        ],
        "cleanup_commands": result.cleanup_commands,
    }


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, object]) -> None:
    text = json.dumps(data, indent=2)
    path.write_text(f"{text}\n", encoding="utf-8")
