"""Code execution sidecar orchestration helpers."""

from __future__ import annotations

import time
from pathlib import Path

from docker_sandbox.models import DockerConfiguration, SandboxRunTarget
from docker_sandbox.orchestration.artifacts import (
    command_result_data,
    write_docker_log_artifacts,
    write_json_artifact,
)
from docker_sandbox.orchestration.docker import (
    DOCKER_EXECUTABLE,
    capture_docker_logs,
    run_captured_command,
)

_CODE_SIDECAR_START_RESULTS_FILE_NAME = "code-sidecar-start-results.json"
_CODE_SIDECAR_LOG_FILE_NAME = "code-sidecar-logs.json"
_CODE_SIDECAR_STDOUT_FILE_NAME = "code-sidecar-stdout.txt"
_CODE_SIDECAR_STDERR_FILE_NAME = "code-sidecar-stderr.txt"
_CODE_SIDECAR_METADATA_FILE_NAME = "code-sidecar-metadata.json"
_CODE_SIDECAR_READINESS_RESULTS_FILE_NAME = "code-sidecar-readiness-results.json"
_CODE_SIDECAR_IMAGE_NAME = "code-sidecar:dev"
_CODE_SIDECAR_CONTAINER_NAME_PREFIX = "code-sidecar"
_CODE_SIDECAR_ALIAS = "code-sidecar"
_CODE_SIDECAR_PORT = 8090
_CODE_SIDECAR_OUTPUT_DIRECTORY_ENVIRONMENT_VARIABLE = "CODE_SIDECAR_OUTPUT_DIRECTORY"
_CODE_SIDECAR_OUTPUT_DIRECTORY = "/code-sidecar-output"
_CODE_SIDECAR_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_CODE_EXECUTION_CAPABILITY = "code_execution"
_SECCOMP_PROFILE_FILE_NAME = "seccomp-profile.json"


def should_start(configuration: DockerConfiguration) -> bool:
    """Return whether the Code sidecar should be started."""
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _CODE_EXECUTION_CAPABILITY in configuration.enabled_capabilities
    )


def build_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    """Build the Code sidecar container name for a sandbox run."""
    if not should_start(configuration):
        return None

    return f"{_CODE_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def start(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Inspect/build/start the Code sidecar and persist startup results."""
    if not should_start(configuration):
        return None

    if network_name is None or code_sidecar_container_name is None:
        raise RuntimeError("Code sidecar requires an internal network.")

    inspect_command = build_image_inspect_command()
    build_command = build_image_build_command(configuration)
    run_command = build_run_command(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
    )
    commands = []
    results = []

    inspect_result = _run_recorded_command(inspect_command)
    commands.append(inspect_command)
    results.append(inspect_result)

    if inspect_result["returncode"] != 0:
        build_result = _run_recorded_command(build_command)
        commands.append(build_command)
        results.append(build_result)

    run_result = _run_recorded_command(run_command)
    commands.append(run_command)
    results.append(run_result)

    write_start_results(run_directory, results)
    return commands


def wait_until_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    code_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _CODE_SIDECAR_READINESS_INTERVALS_SECONDS,
) -> None:
    """Wait for the Code sidecar health check to pass."""
    if not should_start(configuration):
        return

    if network_name is None or code_sidecar_container_name is None:
        raise RuntimeError("Code sidecar readiness check requires an internal network.")

    phase = _run_readiness_phase(configuration, network_name, intervals_seconds)
    result = {
        "container_name": code_sidecar_container_name,
        "health_url": f"http://{_CODE_SIDECAR_ALIAS}:{_CODE_SIDECAR_PORT}/health",
        "ready": bool(phase["success"]),
        "phases": [phase],
    }
    write_readiness_results(run_directory, result)
    if not result["ready"]:
        raise RuntimeError("Code sidecar did not become ready.")


def build_health_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
) -> list[str]:
    """Build the one-shot Docker command used for the health probe."""
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--rm",
        "--network",
        network_name,
        configuration.profile.image_name,
        "python",
        "-c",
        build_health_probe_script(),
    ]


def build_health_probe_script() -> str:
    """Build the Code sidecar health probe script."""
    health_url = f"http://{_CODE_SIDECAR_ALIAS}:{_CODE_SIDECAR_PORT}/health"
    return (
        "import json\n"
        "from urllib.request import urlopen\n"
        f"with urlopen({health_url!r}, timeout=5) as response:\n"
        "    status = response.status\n"
        "    body = response.read()\n"
        "if status < 200 or status >= 300:\n"
        "    raise SystemExit(status)\n"
        "data = json.loads(body.decode('utf-8'))\n"
        "if data.get('status') != 'ok':\n"
        "    raise SystemExit(1)\n"
        "print('ready')\n"
    )


def write_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    """Write Code sidecar readiness results."""
    results_path = run_directory / _CODE_SIDECAR_READINESS_RESULTS_FILE_NAME
    write_json_artifact(results_path, result)


def build_image_inspect_command() -> list[str]:
    """Build the Docker image inspect command for the Code sidecar image."""
    return [
        DOCKER_EXECUTABLE,
        "image",
        "inspect",
        _CODE_SIDECAR_IMAGE_NAME,
    ]


def build_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    """Build the Docker image build command for the Code sidecar image."""
    dockerfile_path = (
        configuration.build_context
        / "src"
        / "code_sidecar"
        / "dockerfile"
        / "Dockerfile"
    )
    return [
        DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        _CODE_SIDECAR_IMAGE_NAME,
        str(configuration.build_context),
    ]


def build_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    code_sidecar_container_name: str,
) -> list[str]:
    """Build the Docker run command for the Code sidecar."""
    source_mount = _build_source_mount(configuration)
    output_mount = _build_output_mount(run_directory)
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--init",
        "--read-only",
        "--name",
        code_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        _CODE_SIDECAR_ALIAS,
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--security-opt",
        f"seccomp={run_directory / _SECCOMP_PROFILE_FILE_NAME}",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--env",
        f"{_CODE_SIDECAR_OUTPUT_DIRECTORY_ENVIRONMENT_VARIABLE}="
        f"{_CODE_SIDECAR_OUTPUT_DIRECTORY}",
        "--mount",
        source_mount,
        "--mount",
        output_mount,
        _CODE_SIDECAR_IMAGE_NAME,
        "python",
        "-m",
        "code_sidecar",
        "--host",
        "0.0.0.0",
        "--port",
        str(_CODE_SIDECAR_PORT),
    ]


def write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    """Write Code sidecar startup results."""
    results_path = run_directory / _CODE_SIDECAR_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)


def write_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    code_sidecar_container_name: str | None,
) -> None:
    """Write Code sidecar Docker logs for the sandbox run."""
    if not should_start(configuration):
        return

    if code_sidecar_container_name is None:
        return

    completed = capture_docker_logs(code_sidecar_container_name, DOCKER_EXECUTABLE)
    metadata = {
        "container_name": code_sidecar_container_name,
        "image_name": _CODE_SIDECAR_IMAGE_NAME,
    }
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_CODE_SIDECAR_LOG_FILE_NAME,
        stdout_file_name=_CODE_SIDECAR_STDOUT_FILE_NAME,
        stderr_file_name=_CODE_SIDECAR_STDERR_FILE_NAME,
        metadata_file_name=_CODE_SIDECAR_METADATA_FILE_NAME,
        metadata=metadata,
    )


def build_cleanup_commands(
    configuration: DockerConfiguration,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the Code sidecar."""
    if not should_start(configuration):
        return None

    if code_sidecar_container_name is None:
        return None

    return [[DOCKER_EXECUTABLE, "rm", "--force", code_sidecar_container_name]]


def _run_recorded_command(command: list[str]) -> dict[str, object]:
    completed = run_captured_command(command, encoding="utf-8", errors="replace")
    return command_result_data(command, completed)


def _run_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    attempts = []
    for attempt_index, interval_seconds in enumerate(intervals_seconds, start=1):
        if interval_seconds > 0:
            time.sleep(interval_seconds)

        command = build_health_probe_command(configuration, network_name)
        completed = run_captured_command(command)
        success = completed.returncode == 0
        attempts.append(
            {
                "attempt": attempt_index,
                "wait_seconds": interval_seconds,
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "success": success,
            }
        )
        if success:
            break

    return {
        "name": "health",
        "success": bool(attempts and attempts[-1]["success"]),
        "attempts": attempts,
    }


def _build_source_mount(configuration: DockerConfiguration) -> str:
    source_directory = configuration.build_context / "src" / "code_sidecar"
    return (
        f"type=bind,source={source_directory},"
        "target=/opt/code-sidecar/code_sidecar,readonly"
    )


def _build_output_mount(run_directory: Path) -> str:
    return f"type=bind,source={run_directory},target={_CODE_SIDECAR_OUTPUT_DIRECTORY}"
