"""Ollama sidecar orchestration helpers."""

from __future__ import annotations

import shlex
import time
from pathlib import Path

from docker_sandbox.models import DockerConfiguration
from docker_sandbox.orchestration import network
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

_OLLAMA_SIDECAR_START_RESULTS_FILE_NAME = "ollama-sidecar-start-results.json"
_OLLAMA_SIDECAR_LOG_FILE_NAME = "ollama-sidecar-logs.json"
_OLLAMA_SIDECAR_STDOUT_FILE_NAME = "ollama-sidecar-stdout.txt"
_OLLAMA_SIDECAR_STDERR_FILE_NAME = "ollama-sidecar-stderr.txt"
_OLLAMA_SIDECAR_METADATA_FILE_NAME = "ollama-sidecar-metadata.json"
_OLLAMA_SIDECAR_READINESS_RESULTS_FILE_NAME = "ollama-sidecar-readiness-results.json"
_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENVIRONMENT_VARIABLE = "OLLAMA_MODEL"
_OLLAMA_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_OLLAMA_BASE_IMAGE_NAME = "ollama/ollama:latest"
_OLLAMA_GENERATED_DIRECTORY = "ollama-sidecar"


def apply_agent_environment(
    container_environment: dict[str, str],
    configuration: DockerConfiguration,
) -> None:
    """Add Ollama environment variables for the AI agent container."""
    ollama_base_url = network.http_url(
        network.OLLAMA_SIDECAR_ALIAS,
        network.OLLAMA_SIDECAR_PORT,
    )
    container_environment[_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE] = ollama_base_url
    container_environment[_OLLAMA_MODEL_ENVIRONMENT_VARIABLE] = (
        configuration.ollama_models[0]
    )


def build_image_inspect_command(configuration: DockerConfiguration) -> list[str]:
    """Build the Docker image inspect command for the Ollama sidecar image."""
    return [
        DOCKER_EXECUTABLE,
        "image",
        "inspect",
        get_image_name(configuration),
    ]


def build_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    """Build the Docker image build command for the Ollama sidecar image."""
    dockerfile_path = write_dockerfile(configuration)
    return [
        DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        get_image_name(configuration),
        str(configuration.build_context),
    ]


def write_dockerfile(configuration: DockerConfiguration) -> Path:
    """Write the generated Dockerfile for the configured Ollama models."""
    image_name = get_image_name(configuration)
    image_tag = image_name.rsplit(":", 1)[-1]
    dockerfile_path = (
        configuration.base_directory
        / "generated"
        / _OLLAMA_GENERATED_DIRECTORY
        / image_tag
        / "Dockerfile"
    )
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile = generate_dockerfile(configuration.ollama_models)
    dockerfile_path.write_text(f"{dockerfile.rstrip()}\n", encoding="utf-8")
    return dockerfile_path


def generate_dockerfile(models: tuple[str, ...]) -> str:
    """Generate a Dockerfile which pre-pulls the configured Ollama models."""
    if not models:
        raise ValueError("Ollama sidecar Dockerfile requires at least one model.")

    pull_commands = _build_model_pull_commands(models)
    return f"""FROM {_OLLAMA_BASE_IMAGE_NAME}

ENV OLLAMA_HOST={network.ANY_IPV4_ADDRESS}:{network.OLLAMA_SIDECAR_PORT}
EXPOSE {network.OLLAMA_SIDECAR_PORT}

RUN ollama serve > /tmp/ollama-build.log 2>&1 & \\
    server_pid=$!; \\
    for attempt in 1 2 3 4 5 6 7 8 9 10; do \\
        if ollama list >/dev/null 2>&1; then \\
            break; \\
        fi; \\
        sleep 1; \\
    done; \\
    ollama list >/dev/null; \\
{pull_commands} \\
    kill "$server_pid"; \\
    wait "$server_pid" || true
"""


def get_image_name(configuration: DockerConfiguration) -> str:
    """Return the configured deterministic Ollama sidecar image name."""
    if configuration.ollama_image_name is None:
        raise ValueError("Ollama sidecar image name is not configured.")
    if not configuration.ollama_models:
        raise ValueError("Ollama sidecar image requires at least one model.")

    return configuration.ollama_image_name


def start(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Inspect/build/start the Ollama sidecar and persist startup results."""
    if network_name is None or ollama_sidecar_container_name is None:
        raise RuntimeError("Ollama sidecar requires an internal network.")

    inspect_command = build_image_inspect_command(configuration)
    build_command = build_image_build_command(configuration)
    run_command = build_run_command(
        configuration,
        network_name,
        ollama_sidecar_container_name,
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


def build_run_command(
    configuration: DockerConfiguration,
    network_name: str,
    ollama_sidecar_container_name: str,
) -> list[str]:
    """Build the Docker run command for the Ollama sidecar."""
    return [
        DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--init",
        "--name",
        ollama_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        network.OLLAMA_SIDECAR_ALIAS,
        "--env",
        f"OLLAMA_HOST={network.ANY_IPV4_ADDRESS}:{network.OLLAMA_SIDECAR_PORT}",
        get_image_name(configuration),
    ]


def write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    """Write Ollama sidecar startup results."""
    results_path = run_directory / _OLLAMA_SIDECAR_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)


def write_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    ollama_sidecar_container_name: str | None,
) -> None:
    """Write Ollama sidecar Docker logs for the sandbox run."""
    if ollama_sidecar_container_name is None:
        return

    completed = capture_docker_logs(ollama_sidecar_container_name, DOCKER_EXECUTABLE)
    metadata = {
        "container_name": ollama_sidecar_container_name,
        "image_name": get_image_name(configuration),
        "models": list(configuration.ollama_models),
    }
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_OLLAMA_SIDECAR_LOG_FILE_NAME,
        stdout_file_name=_OLLAMA_SIDECAR_STDOUT_FILE_NAME,
        stderr_file_name=_OLLAMA_SIDECAR_STDERR_FILE_NAME,
        metadata_file_name=_OLLAMA_SIDECAR_METADATA_FILE_NAME,
        metadata=metadata,
    )


def wait_until_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _OLLAMA_READINESS_INTERVALS_SECONDS,
) -> None:
    """Wait for the Ollama TCP and model availability checks to pass."""
    if network_name is None or ollama_sidecar_container_name is None:
        raise RuntimeError(
            "Ollama sidecar readiness check requires an internal network."
        )

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
            "models",
            build_models_probe_script(configuration.ollama_models),
            intervals_seconds,
        ),
    ]
    ready = all(bool(phase["success"]) for phase in phases)
    result = {
        "container_name": ollama_sidecar_container_name,
        "ollama_url": network.http_url(
            network.OLLAMA_SIDECAR_ALIAS,
            network.OLLAMA_SIDECAR_PORT,
        ),
        "models": list(configuration.ollama_models),
        "ready": ready,
        "phases": phases,
    }
    write_readiness_results(run_directory, result)
    if not ready:
        raise RuntimeError("Ollama sidecar did not become ready.")


def build_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    """Build a one-shot Docker command used for an Ollama readiness probe."""
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
    """Build the Ollama TCP readiness probe script."""
    return (
        "import socket\n"
        f"with socket.create_connection(('{network.OLLAMA_SIDECAR_ALIAS}', "
        f"{network.OLLAMA_SIDECAR_PORT}), timeout=5):\n"
        "    print('ready')\n"
    )


def build_models_probe_script(models: tuple[str, ...]) -> str:
    """Build the Ollama model availability readiness probe script."""
    url = network.http_url(
        network.OLLAMA_SIDECAR_ALIAS,
        network.OLLAMA_SIDECAR_PORT,
        "/api/tags",
    )
    return (
        "import json\n"
        "from urllib.request import urlopen\n"
        f"expected_models = {list(models)!r}\n"
        f"with urlopen({url!r}, timeout=30) as response:\n"
        "    status = response.status\n"
        "    body = response.read()\n"
        "if status < 200 or status >= 300:\n"
        "    raise SystemExit(status)\n"
        "data = json.loads(body.decode('utf-8'))\n"
        "available_models = {\n"
        "    model.get('name') or model.get('model')\n"
        "    for model in data.get('models', [])\n"
        "    if isinstance(model, dict)\n"
        "}\n"
        "missing_models = [\n"
        "    model for model in expected_models if model not in available_models\n"
        "]\n"
        "if missing_models:\n"
        "    print(json.dumps({'missing_models': missing_models}, sort_keys=True))\n"
        "    raise SystemExit(1)\n"
        "print(json.dumps({'models': sorted(available_models)}, sort_keys=True))\n"
    )


def write_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    """Write Ollama sidecar readiness results."""
    results_path = run_directory / _OLLAMA_SIDECAR_READINESS_RESULTS_FILE_NAME
    write_json_artifact(results_path, result)


def build_cleanup_commands(
    configuration: DockerConfiguration,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the Ollama sidecar."""
    _ = configuration
    if ollama_sidecar_container_name is None:
        return None

    return [[DOCKER_EXECUTABLE, "rm", "--force", ollama_sidecar_container_name]]


def _build_model_pull_commands(models: tuple[str, ...]) -> str:
    lines = []
    for model in models:
        lines.append(f"    ollama pull {shlex.quote(model)};")

    return " \\\n".join(lines)


def _run_recorded_command(command: list[str]) -> dict[str, object]:
    completed = run_captured_command(command, encoding="utf-8", errors="replace")
    return command_result_data(command, completed)


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

        command = build_probe_command(
            configuration,
            network_name,
            script,
        )
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
