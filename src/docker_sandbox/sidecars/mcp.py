"""MCP sidecar orchestration helpers."""

from __future__ import annotations

import time
from pathlib import Path

from docker_sandbox.models import DockerConfiguration
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

_MCP_SIDECAR_START_RESULTS_FILE_NAME = "mcp-sidecar-start-results.json"
_MCP_SIDECAR_LOG_FILE_NAME = "mcp-sidecar-logs.json"
_MCP_SIDECAR_STDOUT_FILE_NAME = "mcp-sidecar-stdout.txt"
_MCP_SIDECAR_STDERR_FILE_NAME = "mcp-sidecar-stderr.txt"
_MCP_SIDECAR_METADATA_FILE_NAME = "mcp-sidecar-metadata.json"
_MCP_SIDECAR_TOOL_CALLS_FILE_NAME = "mcp-sidecar-tool-calls.jsonl"
_MCP_SIDECAR_EXPOSURE_FILE_NAME = "mcp-sidecar-exposure.json"
_MCP_SIDECAR_READINESS_RESULTS_FILE_NAME = "mcp-sidecar-readiness-results.json"
_MCP_SIDECAR_IMAGE_NAME = "mcp-sidecar:dev"
_MCP_SIDECAR_CONTAINER_NAME_PREFIX = "mcp-sidecar"
_MCP_SIDECAR_ALIAS = "mcp-sidecar"
_MCP_SIDECAR_PORT = 8000
_MCP_SIDECAR_AUDIT_LOG_PATH_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_AUDIT_LOG_PATH"
_MCP_SIDECAR_EXPOSURE_PATH_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_EXPOSURE_PATH"
_MCP_SIDECAR_OUTPUT_DIRECTORY = "/mcp-sidecar-output"
_MCP_SIDECAR_CONFIG_DIRECTORY = "/mcp-sidecar-config"
_MCP_SIDECAR_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_SQUID_GATEWAY_ALIAS = "egress-gateway"
_SQUID_GATEWAY_PORT = 3128


def build_container_name(timestamp: str) -> str:
    """Build the MCP sidecar container name for a sandbox run."""
    return f"{_MCP_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def start(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
    no_proxy_hosts: tuple[str, ...],
    database_environment_options: list[str],
) -> list[list[str]]:
    """Inspect/build/start the MCP sidecar and persist startup results."""
    if network_name is None or mcp_sidecar_container_name is None:
        raise RuntimeError("MCP sidecar requires an internal network.")

    inspect_command = build_image_inspect_command()
    build_command = build_image_build_command(configuration)
    run_command = build_run_command(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
        no_proxy_hosts,
        database_environment_options,
    )
    commands = []
    results = []

    inspect_result = _run_recorded_command(inspect_command)
    commands.append(inspect_command)
    results.append(inspect_result)

    build_result = _run_recorded_command(build_command)
    commands.append(build_command)
    results.append(build_result)

    run_result = _run_recorded_command(run_command)
    commands.append(run_command)
    results.append(run_result)

    write_start_results(run_directory, results)
    return commands


def build_image_inspect_command() -> list[str]:
    """Build the Docker image inspect command for the MCP sidecar image."""
    return [
        DOCKER_EXECUTABLE,
        "image",
        "inspect",
        _MCP_SIDECAR_IMAGE_NAME,
    ]


def build_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    """Build the Docker image build command for the MCP sidecar image."""
    dockerfile_path = (
        configuration.build_context
        / "src"
        / "mcp_sidecar"
        / "dockerfile"
        / "Dockerfile"
    )
    return [
        DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        _MCP_SIDECAR_IMAGE_NAME,
        str(configuration.build_context),
    ]


def build_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    mcp_sidecar_container_name: str,
    no_proxy_hosts: tuple[str, ...],
    database_environment_options: list[str],
) -> list[str]:
    """Build the Docker run command for the MCP sidecar."""
    proxy_url = f"http://{_SQUID_GATEWAY_ALIAS}:{_SQUID_GATEWAY_PORT}"
    source_mount = _build_source_mount(configuration)
    output_mount = _build_output_mount(run_directory)
    exposure_mount = _build_exposure_mount(run_directory)
    audit_log_path = (
        f"{_MCP_SIDECAR_OUTPUT_DIRECTORY}/{_MCP_SIDECAR_TOOL_CALLS_FILE_NAME}"
    )
    exposure_path = f"{_MCP_SIDECAR_CONFIG_DIRECTORY}/{_MCP_SIDECAR_EXPOSURE_FILE_NAME}"
    command = [
        DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        mcp_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        _MCP_SIDECAR_ALIAS,
        "--env",
        f"HTTP_PROXY={proxy_url}",
        "--env",
        f"HTTPS_PROXY={proxy_url}",
        "--env",
        f"NO_PROXY={','.join(no_proxy_hosts)}",
        "--env",
        (f"JINA_READER_URL=http://{jina_reader_alias()}:{jina_reader_port()}"),
        "--env",
        (f"CODE_SIDECAR_URL=http://{code_sidecar_alias()}:{code_sidecar_port()}"),
        "--env",
        f"{_MCP_SIDECAR_AUDIT_LOG_PATH_ENVIRONMENT_VARIABLE}={audit_log_path}",
        "--env",
        f"{_MCP_SIDECAR_EXPOSURE_PATH_ENVIRONMENT_VARIABLE}={exposure_path}",
    ]
    command.extend(database_environment_options)
    command.extend(
        [
            "--mount",
            source_mount,
            "--mount",
            output_mount,
            "--mount",
            exposure_mount,
            _MCP_SIDECAR_IMAGE_NAME,
            "python",
            "-m",
            "mcp_sidecar",
            "--host",
            "0.0.0.0",
            "--port",
            str(_MCP_SIDECAR_PORT),
        ]
    )
    return command


def wait_until_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _MCP_SIDECAR_READINESS_INTERVALS_SECONDS,
) -> None:
    """Wait for the MCP sidecar health check to pass."""
    if network_name is None or mcp_sidecar_container_name is None:
        raise RuntimeError("MCP sidecar readiness check requires an internal network.")

    phase = _run_readiness_phase(configuration, network_name, intervals_seconds)
    result = {
        "container_name": mcp_sidecar_container_name,
        "health_url": f"http://{_MCP_SIDECAR_ALIAS}:{_MCP_SIDECAR_PORT}/health",
        "ready": bool(phase["success"]),
        "phases": [phase],
    }
    write_readiness_results(run_directory, result)
    if not result["ready"]:
        raise RuntimeError("MCP sidecar did not become ready.")


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
    """Build the MCP sidecar health probe script."""
    health_url = f"http://{_MCP_SIDECAR_ALIAS}:{_MCP_SIDECAR_PORT}/health"
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
    """Write MCP sidecar readiness results."""
    results_path = run_directory / _MCP_SIDECAR_READINESS_RESULTS_FILE_NAME
    write_json_artifact(results_path, result)


def write_exposure(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    """Write the MCP sidecar exposure artifact."""
    exposure = {
        "tools": list(configuration.mcp_sidecar_tools),
        "resources": list(configuration.mcp_sidecar_resources),
    }
    exposure_path = run_directory / _MCP_SIDECAR_EXPOSURE_FILE_NAME
    write_json_artifact(exposure_path, exposure)


def write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    """Write MCP sidecar startup results."""
    results_path = run_directory / _MCP_SIDECAR_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)


def write_logs(
    run_directory: Path,
    mcp_sidecar_container_name: str | None,
) -> None:
    """Write MCP sidecar Docker logs for the sandbox run."""
    if mcp_sidecar_container_name is None:
        return

    completed = capture_docker_logs(mcp_sidecar_container_name, DOCKER_EXECUTABLE)
    metadata = {
        "container_name": mcp_sidecar_container_name,
        "image_name": _MCP_SIDECAR_IMAGE_NAME,
    }
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_MCP_SIDECAR_LOG_FILE_NAME,
        stdout_file_name=_MCP_SIDECAR_STDOUT_FILE_NAME,
        stderr_file_name=_MCP_SIDECAR_STDERR_FILE_NAME,
        metadata_file_name=_MCP_SIDECAR_METADATA_FILE_NAME,
        metadata=metadata,
    )


def build_cleanup_commands(
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the MCP sidecar."""
    if mcp_sidecar_container_name is None:
        return None

    return [[DOCKER_EXECUTABLE, "rm", "--force", mcp_sidecar_container_name]]


def build_no_proxy_hosts(
    extra_hosts: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Build the MCP sidecar no-proxy host list."""
    return (
        "localhost",
        "127.0.0.1",
        _MCP_SIDECAR_ALIAS,
        jina_reader_alias(),
        code_sidecar_alias(),
        *extra_hosts,
    )


def alias() -> str:
    """Return the MCP sidecar network alias."""
    return _MCP_SIDECAR_ALIAS


def port() -> int:
    """Return the MCP sidecar port."""
    return _MCP_SIDECAR_PORT


def tool_calls_file_name() -> str:
    """Return the MCP sidecar audit log file name."""
    return _MCP_SIDECAR_TOOL_CALLS_FILE_NAME


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
    source_directory = configuration.build_context / "src" / "mcp_sidecar"
    return (
        f"type=bind,source={source_directory},"
        "target=/opt/mcp-sidecar/mcp_sidecar,readonly"
    )


def _build_output_mount(run_directory: Path) -> str:
    return f"type=bind,source={run_directory},target={_MCP_SIDECAR_OUTPUT_DIRECTORY}"


def _build_exposure_mount(run_directory: Path) -> str:
    source_path = run_directory / _MCP_SIDECAR_EXPOSURE_FILE_NAME
    return (
        f"type=bind,source={source_path},"
        f"target={_MCP_SIDECAR_CONFIG_DIRECTORY}/{_MCP_SIDECAR_EXPOSURE_FILE_NAME},"
        "readonly"
    )


def jina_reader_alias() -> str:
    """Return the Jina Reader network alias used by MCP."""
    return "jina-reader"


def jina_reader_port() -> int:
    """Return the Jina Reader port used by MCP."""
    return 8081


def code_sidecar_alias() -> str:
    """Return the Code sidecar network alias used by MCP."""
    return "code-sidecar"


def code_sidecar_port() -> int:
    """Return the Code sidecar port used by MCP."""
    return 8090
