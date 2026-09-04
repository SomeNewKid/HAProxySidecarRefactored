"""Run directory fixture preparation for the AI agent container."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path, PurePosixPath

from docker_sandbox.agent_container import run as agent_run
from docker_sandbox.models import DockerConfiguration


def prepare(configuration: DockerConfiguration, run_directory: Path) -> None:
    """Prepare local run directory fixtures mounted into the agent container."""
    _prepare_readonly_denied_directory(configuration, run_directory)
    _prepare_readonly_persistence_directories(configuration, run_directory)
    _prepare_denied_executable_stubs(configuration, run_directory)


def clean(configuration: DockerConfiguration, run_directory: Path) -> None:
    """Remove local run directory fixtures after the agent container exits."""
    _delete_readonly_denied_directory(configuration, run_directory)
    _delete_readonly_persistence_directory(configuration, run_directory)
    _delete_denied_executable_directory(configuration, run_directory)


def _prepare_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_child_directory = (
        run_directory / agent_run.READONLY_DENIED_SOURCE_DIRECTORY / "denied"
    )
    denied_child_directory.mkdir(parents=True, exist_ok=True)
    denied_file = denied_child_directory / "denied.txt"
    denied_file.write_text(agent_run.DENIED_FILE_CONTENT, encoding="utf-8")
    hidden_file = denied_child_directory / ".hidden"
    hidden_file.write_text(agent_run.HIDDEN_DENIED_FILE_CONTENT, encoding="utf-8")


def _prepare_readonly_persistence_directories(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    for target in configuration.profile.readonly_persistence_directories:
        agent_run.validate_container_directory(target)
        source_directory = agent_run.build_readonly_persistence_source_directory(
            run_directory,
            target,
        )
        source_directory.mkdir(parents=True, exist_ok=True)


def _prepare_denied_executable_stubs(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    denied_targets = agent_run.get_denied_executable_targets(configuration)
    if not denied_targets:
        return

    stub_directory = run_directory / agent_run.DENIED_EXECUTABLE_SOURCE_DIRECTORY
    stub_directory.mkdir(parents=True, exist_ok=True)
    for target_path in denied_targets:
        stub_path = stub_directory / agent_run.build_denied_executable_stub_name(
            target_path
        )
        stub_path.write_text(
            _build_denied_executable_stub_text(PurePosixPath(target_path).name),
            encoding="utf-8",
        )
        stub_path.chmod(0o755)


def _build_denied_executable_stub_text(executable_name: str) -> str:
    return (
        "#!/bin/sh\n"
        f"echo {shlex.quote(executable_name)}: denied by sandbox profile >&2\n"
        "exit 127\n"
    )


def _delete_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_source_directory = run_directory / agent_run.READONLY_DENIED_SOURCE_DIRECTORY
    _validate_child_path(run_directory, denied_source_directory, "readonly denied")

    shutil.rmtree(denied_source_directory, ignore_errors=True)


def _delete_readonly_persistence_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.readonly_persistence_directories:
        return

    persistence_source_directory = (
        run_directory / agent_run.READONLY_PERSISTENCE_SOURCE_DIRECTORY
    )
    _validate_child_path(
        run_directory, persistence_source_directory, "readonly persistence"
    )

    shutil.rmtree(persistence_source_directory, ignore_errors=True)


def _delete_denied_executable_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not agent_run.get_denied_executable_targets(configuration):
        return

    stub_directory = run_directory / agent_run.DENIED_EXECUTABLE_SOURCE_DIRECTORY
    _validate_child_path(run_directory, stub_directory, "denied executable stubs")

    shutil.rmtree(stub_directory, ignore_errors=True)


def _validate_child_path(
    run_directory: Path,
    child_path: Path,
    description: str,
) -> None:
    resolved_run_directory = run_directory.resolve()
    resolved_child_path = child_path.resolve()

    if resolved_run_directory in resolved_child_path.parents:
        return

    raise RuntimeError(
        f"Refusing to remove {description} outside the run "
        f"directory: {resolved_child_path}"
    )
