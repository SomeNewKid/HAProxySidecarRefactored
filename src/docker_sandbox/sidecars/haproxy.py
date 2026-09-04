"""HAProxy sidecar orchestration helpers."""

from __future__ import annotations

import time
from pathlib import Path

from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    SandboxRunTarget,
)
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

_HAPROXY_CONFIGURATION_FILE_NAME = "haproxy.cfg"
_HAPROXY_SIDECAR_START_RESULTS_FILE_NAME = "haproxy-sidecar-start-results.json"
_HAPROXY_SIDECAR_LOG_FILE_NAME = "haproxy-sidecar-logs.json"
_HAPROXY_SIDECAR_STDOUT_FILE_NAME = "haproxy-sidecar-stdout.txt"
_HAPROXY_SIDECAR_STDERR_FILE_NAME = "haproxy-sidecar-stderr.txt"
_HAPROXY_SIDECAR_METADATA_FILE_NAME = "haproxy-sidecar-metadata.json"
_HAPROXY_SIDECAR_READINESS_RESULTS_FILE_NAME = "haproxy-sidecar-readiness-results.json"
_HAPROXY_CAPABILITY = "haproxy"
_HAPROXY_IMAGE_NAME = "haproxy:latest"
_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX = "haproxy-sidecar"
_HAPROXY_SIDECAR_ALIAS = "haproxy-sidecar"
_HAPROXY_CONFIGURATION_PATH = "/usr/local/etc/haproxy/haproxy.cfg"
_HAPROXY_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)


def should_start(configuration: DockerConfiguration) -> bool:
    """Return whether the HAProxy sidecar should be started."""
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _HAPROXY_CAPABILITY in configuration.enabled_capabilities
    )


def build_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    """Build the HAProxy container name for a sandbox run."""
    if not should_start(configuration):
        return None

    return f"{_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def write_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    """Write the HAProxy configuration artifact for the sandbox run."""
    if not should_start(configuration):
        return

    haproxy = get_configuration(configuration)
    config_path = run_directory / _HAPROXY_CONFIGURATION_FILE_NAME
    config_text = generate_configuration(haproxy.backend_host, haproxy.ports)
    config_path.write_text(f"{config_text.rstrip()}\n", encoding="utf-8")


def generate_configuration(backend_host: str, ports: tuple[int, ...]) -> str:
    """Generate HAProxy TCP proxy configuration text."""
    port_sections = []
    for port in ports:
        port_sections.append(
            "\n".join(
                [
                    f"frontend tcp_{port}",
                    f"    bind *:{port}",
                    f"    default_backend backend_{port}",
                    "",
                    f"backend backend_{port}",
                    f"    server host {backend_host}:{port}",
                ]
            )
        )

    return "\n\n".join(
        [
            "global",
            "    log stdout format raw local0",
            "    maxconn 256",
            "",
            "defaults",
            "    mode tcp",
            "    log global",
            "    timeout connect 5s",
            "    timeout client 1m",
            "    timeout server 1m",
            "",
            *port_sections,
        ]
    )


def get_configuration(
    configuration: DockerConfiguration,
) -> HAProxyConfiguration:
    """Return validated HAProxy sidecar settings."""
    if _HAPROXY_CAPABILITY not in configuration.enabled_capabilities:
        raise ValueError("HAProxy sidecar requires the haproxy capability.")
    if configuration.haproxy is None:
        raise ValueError("HAProxy sidecar configuration is not configured.")
    if not configuration.haproxy.ports:
        raise ValueError("HAProxy sidecar requires at least one port.")

    return configuration.haproxy


def start(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Start HAProxy and connect it to the internal sandbox network."""
    if not should_start(configuration):
        return None

    if network_name is None or haproxy_sidecar_container_name is None:
        raise RuntimeError("HAProxy sidecar requires an internal network.")

    run_command = build_run_command(run_directory, haproxy_sidecar_container_name)
    network_connect_command = build_network_connect_command(
        network_name,
        haproxy_sidecar_container_name,
    )
    result = _run_recorded_command(run_command)
    network_connect_result = _run_recorded_command(network_connect_command)
    write_start_results(run_directory, [result, network_connect_result])
    return [run_command, network_connect_command]


def wait_until_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    haproxy_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _HAPROXY_READINESS_INTERVALS_SECONDS,
) -> None:
    """Wait for HAProxy process and configuration readiness checks."""
    if not should_start(configuration):
        return

    if haproxy_sidecar_container_name is None:
        raise RuntimeError("HAProxy sidecar readiness check requires a container.")

    process_phase = run_readiness_phase(
        "process",
        build_process_probe_command(haproxy_sidecar_container_name),
        intervals_seconds,
    )
    phases = [process_phase]
    if bool(process_phase["success"]):
        phases.append(
            run_readiness_phase(
                "configuration",
                build_config_probe_command(haproxy_sidecar_container_name),
                intervals_seconds,
            )
        )

    ready = all(bool(phase["success"]) for phase in phases)
    result = {
        "container_name": haproxy_sidecar_container_name,
        "configuration_path": _HAPROXY_CONFIGURATION_PATH,
        "ready": ready,
        "phases": phases,
    }
    write_readiness_results(run_directory, result)
    if not ready:
        raise RuntimeError("HAProxy sidecar did not become ready.")


def run_readiness_phase(
    phase_name: str,
    command: list[str],
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    """Run one HAProxy readiness phase with retry intervals."""
    attempts = []
    for attempt_index, interval_seconds in enumerate(intervals_seconds, start=1):
        if interval_seconds > 0:
            time.sleep(interval_seconds)

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


def build_process_probe_command(
    haproxy_sidecar_container_name: str,
) -> list[str]:
    """Build the HAProxy process readiness probe command."""
    return [
        DOCKER_EXECUTABLE,
        "exec",
        haproxy_sidecar_container_name,
        "pidof",
        "haproxy",
    ]


def build_config_probe_command(
    haproxy_sidecar_container_name: str,
) -> list[str]:
    """Build the HAProxy configuration readiness probe command."""
    return [
        DOCKER_EXECUTABLE,
        "exec",
        haproxy_sidecar_container_name,
        "haproxy",
        "-c",
        "-f",
        _HAPROXY_CONFIGURATION_PATH,
    ]


def build_run_command(
    run_directory: Path,
    haproxy_sidecar_container_name: str,
) -> list[str]:
    """Build the Docker run command for the HAProxy sidecar."""
    config_path = run_directory / _HAPROXY_CONFIGURATION_FILE_NAME
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        haproxy_sidecar_container_name,
        "--network",
        "bridge",
        "--add-host",
        "host.docker.internal:host-gateway",
        "--mount",
        (
            f"type=bind,source={config_path},"
            f"target={_HAPROXY_CONFIGURATION_PATH},readonly"
        ),
        _HAPROXY_IMAGE_NAME,
    ]


def build_network_connect_command(
    network_name: str,
    haproxy_sidecar_container_name: str,
) -> list[str]:
    """Build the command that connects HAProxy to the internal network."""
    return [
        DOCKER_EXECUTABLE,
        "network",
        "connect",
        "--alias",
        _HAPROXY_SIDECAR_ALIAS,
        network_name,
        haproxy_sidecar_container_name,
    ]


def write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    """Write HAProxy startup results."""
    results_path = run_directory / _HAPROXY_SIDECAR_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)


def write_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    """Write HAProxy readiness results."""
    results_path = run_directory / _HAPROXY_SIDECAR_READINESS_RESULTS_FILE_NAME
    write_json_artifact(results_path, result)


def write_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    haproxy_sidecar_container_name: str | None,
) -> None:
    """Write HAProxy Docker logs for the sandbox run."""
    if not should_start(configuration):
        return

    if haproxy_sidecar_container_name is None:
        return

    completed = capture_docker_logs(haproxy_sidecar_container_name, DOCKER_EXECUTABLE)
    haproxy = get_configuration(configuration)
    metadata = {
        "container_name": haproxy_sidecar_container_name,
        "image_name": _HAPROXY_IMAGE_NAME,
        "backend_host": haproxy.backend_host,
        "ports": list(haproxy.ports),
    }
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_HAPROXY_SIDECAR_LOG_FILE_NAME,
        stdout_file_name=_HAPROXY_SIDECAR_STDOUT_FILE_NAME,
        stderr_file_name=_HAPROXY_SIDECAR_STDERR_FILE_NAME,
        metadata_file_name=_HAPROXY_SIDECAR_METADATA_FILE_NAME,
        metadata=metadata,
    )


def build_cleanup_commands(
    configuration: DockerConfiguration,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the HAProxy sidecar."""
    if not should_start(configuration):
        return None

    if haproxy_sidecar_container_name is None:
        return None

    return [[DOCKER_EXECUTABLE, "rm", "--force", haproxy_sidecar_container_name]]


def alias() -> str:
    """Return the HAProxy sidecar network alias."""
    return _HAPROXY_SIDECAR_ALIAS


def _run_recorded_command(command: list[str]) -> dict[str, object]:
    completed = run_captured_command(command, encoding="utf-8", errors="replace")
    return command_result_data(command, completed)
