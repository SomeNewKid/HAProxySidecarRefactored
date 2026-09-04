"""Tests for Docker sandbox orchestration artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from docker_sandbox.orchestration.artifacts import (
    command_result_data,
    write_docker_log_artifacts,
    write_json_artifact,
)
from docker_sandbox.orchestration.types import CommandResult


def test_command_result_data_includes_command() -> None:
    """Verify command result data preserves command and captured output."""
    result = CommandResult(
        returncode=1,
        stdout="out",
        stderr="err",
        command=("ignored",),
    )

    assert command_result_data(["docker", "ps"], result) == {
        "command": ["docker", "ps"],
        "returncode": 1,
        "stdout": "out",
        "stderr": "err",
    }


def test_write_json_artifact_serializes_paths(tmp_path: Path) -> None:
    """Verify JSON artifacts serialize common orchestration values."""
    path = tmp_path / "artifact.json"

    write_json_artifact(path, {"path": tmp_path / "child", "items": ("a", "b")})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "path": str(tmp_path / "child"),
        "items": ["a", "b"],
    }


def test_write_docker_log_artifacts_writes_standard_files(tmp_path: Path) -> None:
    """Verify Docker log artifact writing is shared across sidecars."""
    result = CommandResult(
        returncode=0,
        stdout="container stdout\n",
        stderr="container stderr\n",
        command=("docker", "logs", "sidecar-1"),
    )

    write_docker_log_artifacts(
        run_directory=tmp_path,
        log_result=result,
        log_file_name="sidecar-logs.json",
        stdout_file_name="sidecar-stdout.txt",
        stderr_file_name="sidecar-stderr.txt",
        metadata_file_name="sidecar-metadata.json",
        metadata={"container_name": "sidecar-1"},
    )

    assert (tmp_path / "sidecar-stdout.txt").read_text() == "container stdout\n"
    assert (tmp_path / "sidecar-stderr.txt").read_text() == "container stderr\n"
    assert '"returncode": 0' in (tmp_path / "sidecar-logs.json").read_text()
    metadata = (tmp_path / "sidecar-metadata.json").read_text()
    assert '"container_name": "sidecar-1"' in metadata
    assert '"log_command": [' in metadata
    assert '"log_returncode": 0' in metadata
