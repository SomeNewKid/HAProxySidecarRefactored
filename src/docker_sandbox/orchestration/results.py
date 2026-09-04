"""Docker sandbox run result assembly."""

from __future__ import annotations

from docker_sandbox.models import DockerConfiguration, DockerRunResult
from docker_sandbox.orchestration import sidecar_lifecycle
from docker_sandbox.orchestration.docker import build_docker_remove_command
from docker_sandbox.orchestration.sidecar_lifecycle import SidecarStartResult
from docker_sandbox.orchestration.types import CommandResult, RunContext

_DOCKER_EXECUTABLE = "docker"


def build_docker_run_result(
    configuration: DockerConfiguration,
    run_context: RunContext,
    command: list[str],
    completed: CommandResult,
    sidecar_start_result: SidecarStartResult,
) -> DockerRunResult:
    """Build the Docker sandbox run result for a completed agent container run."""
    remove_command = build_docker_remove_command(
        run_context.container_name,
        _DOCKER_EXECUTABLE,
    )
    sidecar_cleanup_commands = sidecar_lifecycle.build_cleanup_commands(
        configuration,
        run_context,
    )
    sidecars = sidecar_lifecycle.build_run_records(
        sidecar_start_result,
        run_context,
        sidecar_cleanup_commands,
    )
    cleanup_commands = sidecar_lifecycle.flatten_cleanup_commands(
        sidecar_cleanup_commands
    )

    return DockerRunResult(
        image_name=configuration.profile.image_name,
        profile_name=configuration.profile.name,
        container_name=run_context.container_name,
        run_directory=run_context.run_directory,
        command=command,
        remove_command=remove_command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        network_name=run_context.network_name,
        gateway_ip_address=sidecar_start_result.gateway_ip_address,
        sidecars=sidecars,
        cleanup_commands=cleanup_commands,
    )
