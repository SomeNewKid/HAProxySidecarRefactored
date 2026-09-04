"""Tests for Docker sandbox orchestration docker."""

from __future__ import annotations

import subprocess

from docker_sandbox.orchestration.docker import (
    build_docker_remove_command,
    capture_docker_logs,
    run_captured_command,
)
from docker_sandbox.orchestration.types import CommandResult


def test_build_docker_remove_command() -> None:
    """Verify Docker remove command construction is shared."""
    command = build_docker_remove_command("container-1")

    assert command == ["docker", "rm", "--force", "container-1"]


def test_run_captured_command_returns_shared_result(monkeypatch) -> None:
    """Verify captured command execution returns a shared command result."""

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "version"]
        assert check is False
        assert capture_output is True
        assert text is True
        assert kwargs == {"encoding": "utf-8", "errors": "replace"}
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_captured_command(
        ["docker", "version"],
        encoding="utf-8",
        errors="replace",
    )

    assert result == CommandResult(
        returncode=0,
        stdout="ok\n",
        stderr="",
        command=("docker", "version"),
    )


def test_capture_docker_logs_uses_docker_logs_command(monkeypatch) -> None:
    """Verify Docker log capture uses the expected command."""
    commands = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="logs\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = capture_docker_logs("sidecar-1")

    assert commands == [["docker", "logs", "sidecar-1"]]
    assert result.stdout == "logs\n"
