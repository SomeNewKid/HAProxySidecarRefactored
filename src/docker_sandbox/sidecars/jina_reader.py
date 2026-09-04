"""Jina Reader sidecar orchestration helpers."""

from __future__ import annotations

import time
from pathlib import Path

from docker_sandbox.models import DockerConfiguration
from docker_sandbox.orchestration import network
from docker_sandbox.orchestration.artifacts import (
    write_docker_log_artifacts,
    write_json_artifact,
)
from docker_sandbox.orchestration.docker import (
    DOCKER_EXECUTABLE,
    capture_docker_logs,
    run_captured_command,
)

_JINA_READER_START_RESULTS_FILE_NAME = "jina-reader-start-results.json"
_JINA_READER_LOG_FILE_NAME = "jina-reader-logs.json"
_JINA_READER_STDOUT_FILE_NAME = "jina-reader-stdout.txt"
_JINA_READER_STDERR_FILE_NAME = "jina-reader-stderr.txt"
_JINA_READER_METADATA_FILE_NAME = "jina-reader-metadata.json"
_JINA_READER_READINESS_RESULTS_FILE_NAME = "jina-reader-readiness-results.json"
_JINA_READER_IMAGE_NAME = "ghcr.io/jina-ai/reader:oss"
_JINA_READER_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)


def start(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    """Start the Jina Reader sidecar and persist startup results."""
    if network_name is None or jina_reader_container_name is None:
        raise RuntimeError("Jina Reader requires an internal network.")

    run_command = build_run_command(network_name, jina_reader_container_name)
    result = run_captured_command(run_command, encoding="utf-8", errors="replace")
    write_start_results(
        run_directory,
        [
            {
                "command": run_command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        ],
    )
    return [run_command]


def build_run_command(
    network_name: str,
    jina_reader_container_name: str,
) -> list[str]:
    """Build the Docker run command for the Jina Reader sidecar."""
    proxy_url = network.http_url(
        network.SQUID_GATEWAY_ALIAS,
        network.SQUID_GATEWAY_PORT,
    )
    no_proxy = ",".join(
        (
            network.LOCALHOST,
            network.LOOPBACK_IPV4_ADDRESS,
            network.JINA_READER_ALIAS,
            network.MCP_SIDECAR_ALIAS,
        )
    )
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        jina_reader_container_name,
        "--network",
        network_name,
        "--network-alias",
        network.JINA_READER_ALIAS,
        "--env",
        f"HTTP_PROXY={proxy_url}",
        "--env",
        f"HTTPS_PROXY={proxy_url}",
        "--env",
        f"NO_PROXY={no_proxy}",
        _JINA_READER_IMAGE_NAME,
    ]


def wait_until_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _JINA_READER_READINESS_INTERVALS_SECONDS,
) -> None:
    """Wait for the Jina Reader sidecar readiness checks to pass."""
    if network_name is None or jina_reader_container_name is None:
        raise RuntimeError("Jina Reader readiness check requires an internal network.")

    phases = [
        _run_readiness_phase(
            configuration,
            network_name,
            "tcp",
            build_tcp_probe_script(),
            intervals_seconds,
        ),
        _run_readiness_phase(
            configuration,
            network_name,
            "fetch",
            build_fetch_probe_script(),
            intervals_seconds,
        ),
    ]
    ready = all(bool(phase["success"]) for phase in phases)
    result = {
        "container_name": jina_reader_container_name,
        "reader_url": network.http_url(
            network.JINA_READER_ALIAS,
            network.JINA_READER_PORT,
        ),
        "fetch_url": network.JINA_READER_READINESS_URL,
        "ready": ready,
        "phases": phases,
    }
    write_readiness_results(run_directory, result)
    if not ready:
        raise RuntimeError("Jina Reader did not become ready.")


def build_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    """Build the one-shot Docker command used for Jina readiness probes."""
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--rm",
        "--network",
        network_name,
        configuration.profile.image_name,
        "python",
        "-c",
        script,
    ]


def build_tcp_probe_script() -> str:
    """Build the TCP readiness probe script."""
    return (
        "import socket\n"
        f"with socket.create_connection(('{network.JINA_READER_ALIAS}', "
        f"{network.JINA_READER_PORT}), timeout=5):\n"
        "    print('ready')\n"
    )


def build_fetch_probe_script() -> str:
    """Build the HTTP fetch readiness probe script."""
    reader_url = network.http_url(
        network.JINA_READER_ALIAS,
        network.JINA_READER_PORT,
        network.JINA_READER_READINESS_URL,
    )
    return (
        "from urllib.request import urlopen\n"
        f"with urlopen({reader_url!r}, timeout=60) as response:\n"
        "    status = response.status\n"
        "    body = response.read(200)\n"
        "if status < 200 or status >= 300:\n"
        "    raise SystemExit(status)\n"
        "print(body.decode('utf-8', errors='replace'))\n"
    )


def write_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    """Write Jina Reader readiness results."""
    results_path = run_directory / _JINA_READER_READINESS_RESULTS_FILE_NAME
    write_json_artifact(results_path, result)


def write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    """Write Jina Reader startup results."""
    results_path = run_directory / _JINA_READER_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)


def write_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    jina_reader_container_name: str | None,
) -> None:
    """Write Jina Reader Docker logs for the sandbox run."""
    _ = configuration
    if jina_reader_container_name is None:
        return

    completed = capture_docker_logs(jina_reader_container_name, DOCKER_EXECUTABLE)
    metadata = {
        "container_name": jina_reader_container_name,
        "image_name": _JINA_READER_IMAGE_NAME,
    }
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_JINA_READER_LOG_FILE_NAME,
        stdout_file_name=_JINA_READER_STDOUT_FILE_NAME,
        stderr_file_name=_JINA_READER_STDERR_FILE_NAME,
        metadata_file_name=_JINA_READER_METADATA_FILE_NAME,
        metadata=metadata,
    )


def build_cleanup_commands(
    configuration: DockerConfiguration,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the Jina Reader sidecar."""
    _ = configuration
    if jina_reader_container_name is None:
        return None

    return [[DOCKER_EXECUTABLE, "rm", "--force", jina_reader_container_name]]


def _run_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    phase_name: str,
    script: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    attempts = []
    for attempt_index, interval_seconds in enumerate(intervals_seconds, start=1):
        if interval_seconds > 0:
            time.sleep(interval_seconds)

        command = build_probe_command(configuration, network_name, script)
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
        "name": phase_name,
        "success": bool(attempts and attempts[-1]["success"]),
        "attempts": attempts,
    }
