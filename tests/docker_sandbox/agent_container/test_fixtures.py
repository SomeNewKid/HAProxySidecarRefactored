"""Tests for AI agent container run directory fixtures."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import fixtures, hardening, run
from docker_sandbox.models import DockerConfiguration


def test_prepare_creates_mount_fixtures(tmp_path: Path) -> None:
    """Verify local fixtures are prepared for readonly mounts and denied tools."""
    configuration = _create_fixture_configuration()

    fixtures.prepare(configuration, tmp_path)

    readonly_denied_directory = tmp_path / run.READONLY_DENIED_SOURCE_DIRECTORY
    persistence_directory = tmp_path / run.READONLY_PERSISTENCE_SOURCE_DIRECTORY
    denied_executable_directory = tmp_path / run.DENIED_EXECUTABLE_SOURCE_DIRECTORY

    assert (readonly_denied_directory / "denied" / "denied.txt").read_text() == (
        run.DENIED_FILE_CONTENT
    )
    assert (readonly_denied_directory / "denied" / ".hidden").read_text() == (
        run.HIDDEN_DENIED_FILE_CONTENT
    )
    assert (persistence_directory / "tmp__sandbox-home").is_dir()
    stub_text = (denied_executable_directory / "usr__bin__git").read_text()
    assert "git: denied by sandbox profile" in stub_text
    assert "exit 127" in stub_text


def test_clean_removes_mount_fixtures(tmp_path: Path) -> None:
    """Verify local fixture directories are removed after the run."""
    configuration = _create_fixture_configuration()
    fixtures.prepare(configuration, tmp_path)

    fixtures.clean(configuration, tmp_path)

    assert not (tmp_path / run.READONLY_DENIED_SOURCE_DIRECTORY).exists()
    assert not (tmp_path / run.READONLY_PERSISTENCE_SOURCE_DIRECTORY).exists()
    assert not (tmp_path / run.DENIED_EXECUTABLE_SOURCE_DIRECTORY).exists()


def _create_fixture_configuration() -> DockerConfiguration:
    profile = replace(
        hardening.base_locked_down_profile(),
        readonly_persistence_directories=("/tmp/sandbox-home",),
        denied_executable_paths=("/usr/bin/git",),
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
    )
