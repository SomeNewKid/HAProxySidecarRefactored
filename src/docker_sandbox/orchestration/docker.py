"""Docker command helpers for sandbox orchestration."""

from __future__ import annotations

import subprocess

from .types import CommandResult

DOCKER_EXECUTABLE = "docker"


def build_docker_remove_command(
    container_name: str,
    docker_executable: str = DOCKER_EXECUTABLE,
) -> list[str]:
    """Build a command that removes a Docker container."""
    return [
        docker_executable,
        "rm",
        "--force",
        container_name,
    ]


def capture_docker_logs(
    container_name: str,
    docker_executable: str = DOCKER_EXECUTABLE,
) -> CommandResult:
    """Capture stdout and stderr from `docker logs`."""
    return run_captured_command([docker_executable, "logs", container_name])


def run_captured_command(
    command: list[str],
    encoding: str | None = None,
    errors: str | None = None,
) -> CommandResult:
    """Run a command and capture its stdout, stderr, and return code."""
    if encoding is not None and errors is not None:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors=errors,
        )
    elif encoding is not None:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding=encoding,
        )
    elif errors is not None:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            errors=errors,
        )
    else:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        command=tuple(command),
    )
