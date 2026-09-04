"""Tests for ollama."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    mcp,
    ollama,
)


def test_ollama_sidecar_cleanup_removes_sidecar_before_network_cleanup(
    tmp_path: Path,
) -> None:
    """Verify Ollama sidecar cleanup removes the sidecar container."""
    configuration = _create_ollama_configuration(tmp_path)

    cleanup_commands = ollama.build_cleanup_commands(
        configuration,
        "ollama-sidecar-1",
    )

    assert cleanup_commands == [["docker", "rm", "--force", "ollama-sidecar-1"]]


def test_ollama_sidecar_dockerfile_pulls_declared_models() -> None:
    """Verify the generated Ollama Dockerfile bakes each model into the image."""
    dockerfile = ollama.generate_dockerfile(
        ("phi4-mini:latest", "qwen3:4b"),
    )

    assert "FROM ollama/ollama:latest" in dockerfile
    assert "ENV OLLAMA_HOST=0.0.0.0:11434" in dockerfile
    assert "EXPOSE 11434" in dockerfile
    assert "ollama serve > /tmp/ollama-build.log 2>&1" in dockerfile
    assert "ollama pull phi4-mini:latest;" in dockerfile
    assert "ollama pull qwen3:4b;" in dockerfile
    assert 'kill "$server_pid";' in dockerfile


def test_ollama_sidecar_dockerfile_quotes_model_names() -> None:
    """Verify shell-sensitive model names are safely quoted in Dockerfile output."""
    dockerfile = ollama.generate_dockerfile(("custom model:latest",))

    assert "ollama pull 'custom model:latest';" in dockerfile


def test_ollama_sidecar_image_commands_use_generated_dockerfile(
    tmp_path: Path,
) -> None:
    """Verify Ollama image commands target the generated model Dockerfile."""
    configuration = _create_ollama_configuration(tmp_path)
    image_name = resolve_ollama_image_name(
        ("qwen3:4b", "phi4-mini:latest"),
    )

    inspect_command = ollama.build_image_inspect_command(configuration)
    build_command = ollama.build_image_build_command(configuration)

    dockerfile_path = (
        tmp_path
        / "generated"
        / "ollama-sidecar"
        / image_name.rsplit(":", 1)[-1]
        / "Dockerfile"
    )
    assert inspect_command == ["docker", "image", "inspect", image_name]
    assert build_command == [
        "docker",
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        image_name,
        ".",
    ]
    assert dockerfile_path.exists()


def test_ollama_sidecar_probe_scripts_target_service_and_models() -> None:
    """Verify Ollama readiness probes target TCP and declared models."""
    tcp_script = ollama.build_tcp_probe_script()
    models_script = ollama.build_models_probe_script(
        ("phi4-mini:latest", "qwen3:4b"),
    )

    assert "socket.create_connection(('ollama-sidecar', 11434), timeout=5)" in (
        tcp_script
    )
    assert "http://ollama-sidecar:11434/api/tags" in models_script
    assert "expected_models = ['phi4-mini:latest', 'qwen3:4b']" in models_script
    assert "missing_models" in models_script
    assert "model.get('name') or model.get('model')" in models_script


def test_ollama_sidecar_run_command_uses_internal_network(
    tmp_path: Path,
) -> None:
    """Verify the Ollama sidecar starts on the internal Docker network."""
    configuration = _create_ollama_configuration(tmp_path)
    assert configuration.ollama_image_name is not None

    command = ollama.build_run_command(
        configuration,
        "sandbox-agent-net-1",
        "ollama-sidecar-1",
    )

    assert command[:4] == ["docker", "run", "--detach", "--init"]
    assert "ollama-sidecar-1" in command
    assert _option_value(command, "--network") == "sandbox-agent-net-1"
    assert _option_value(command, "--network-alias") == "ollama-sidecar"
    assert "OLLAMA_HOST=0.0.0.0:11434" in _option_values(command, "--env")
    assert command[-1] == configuration.ollama_image_name


def test_ollama_start_builds_missing_image_and_persists_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Ollama startup records inspect, build, and run command results."""
    configuration = _create_ollama_configuration(tmp_path)
    calls = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        assert encoding == "utf-8"
        assert errors == "replace"
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="missing image\n",
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    commands = ollama.start(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "ollama-sidecar-1",
    )

    start_results = json.loads(
        (tmp_path / "ollama-sidecar-start-results.json").read_text()
    )
    assert commands is not None
    assert commands == [
        ollama.build_image_inspect_command(configuration),
        ollama.build_image_build_command(configuration),
        ollama.build_run_command(
            configuration,
            "sandbox-agent-net-1",
            "ollama-sidecar-1",
        ),
    ]
    assert start_results == [
        {
            "command": commands[0],
            "returncode": 1,
            "stdout": "",
            "stderr": "missing image\n",
        },
        {
            "command": commands[1],
            "returncode": 0,
            "stdout": "ok\n",
            "stderr": "",
        },
        {
            "command": commands[2],
            "returncode": 0,
            "stdout": "ok\n",
            "stderr": "",
        },
    ]


def test_ollama_wait_until_ready_persists_model_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Ollama readiness writes TCP and model probe results."""
    configuration = _create_ollama_configuration(tmp_path)
    calls = []
    sleeps = []

    def fake_sleep(interval_seconds: float) -> None:
        sleeps.append(interval_seconds)

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="connection refused",
            )

        if len(calls) == 3:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout='{"missing_models": ["qwen3:4b"]}\n',
                stderr="",
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ready\n",
            stderr="",
        )

    monkeypatch.setattr("docker_sandbox.sidecars.jina_reader.time.sleep", fake_sleep)
    monkeypatch.setattr(subprocess, "run", fake_run)

    ollama.wait_until_ready(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "ollama-sidecar-1",
        intervals_seconds=(0.0, 1.0),
    )

    readiness_results = json.loads(
        (tmp_path / "ollama-sidecar-readiness-results.json").read_text()
    )
    assert sleeps == [1.0, 1.0]
    assert readiness_results["container_name"] == "ollama-sidecar-1"
    assert readiness_results["ollama_url"] == "http://ollama-sidecar:11434"
    assert readiness_results["models"] == ["phi4-mini:latest", "qwen3:4b"]
    assert readiness_results["ready"] is True
    assert [phase["name"] for phase in readiness_results["phases"]] == [
        "tcp",
        "models",
    ]
    assert readiness_results["phases"][0]["success"] is True
    assert readiness_results["phases"][0]["attempts"][0]["success"] is False
    assert readiness_results["phases"][0]["attempts"][1]["success"] is True
    assert readiness_results["phases"][1]["success"] is True
    assert readiness_results["phases"][1]["attempts"][0]["success"] is False
    assert readiness_results["phases"][1]["attempts"][1]["success"] is True
    assert len(calls) == 4
    assert all(
        command[:5] == ["docker", "run", "--rm", "--network", "sandbox-agent-net-1"]
        for command in calls
    )
    assert all(
        "sandbox-agent/sandbox-agent:locked-down" in command for command in calls
    )


def test_ollama_wait_until_ready_raises_when_models_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Ollama readiness fails when declared models are unavailable."""
    configuration = _create_ollama_configuration(tmp_path)

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        if "socket.create_connection" in command[-1]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="ready\n",
                stderr="",
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout='{"missing_models": ["qwen3:4b"]}\n',
            stderr="",
        )

    monkeypatch.setattr(
        "docker_sandbox.sidecars.jina_reader.time.sleep", lambda _: None
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        ollama.wait_until_ready(
            configuration,
            tmp_path,
            "sandbox-agent-net-1",
            "ollama-sidecar-1",
            intervals_seconds=(0.0,),
        )
    except RuntimeError as error:
        assert str(error) == "Ollama sidecar did not become ready."
    else:
        raise AssertionError("Expected Ollama readiness failure.")

    readiness_results = json.loads(
        (tmp_path / "ollama-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["ready"] is False
    assert readiness_results["phases"][0]["success"] is True
    assert readiness_results["phases"][1]["success"] is False


def test_ollama_write_dockerfile_uses_image_tag_directory(
    tmp_path: Path,
) -> None:
    """Verify generated Ollama Dockerfiles are isolated by image tag."""
    configuration = _create_ollama_configuration(tmp_path)
    assert configuration.ollama_image_name is not None
    image_tag = configuration.ollama_image_name.rsplit(":", 1)[-1]

    dockerfile_path = ollama.write_dockerfile(configuration)

    assert dockerfile_path == (
        tmp_path / "generated" / "ollama-sidecar" / image_tag / "Dockerfile"
    )
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    assert "ollama pull phi4-mini:latest;" in dockerfile
    assert "ollama pull qwen3:4b;" in dockerfile


def test_ollama_write_logs_persists_debug_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Ollama sidecar logs are persisted as text and metadata artifacts."""
    configuration = _create_ollama_configuration(tmp_path)
    assert configuration.ollama_image_name is not None

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "logs", "ollama-sidecar-1"]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ollama stdout\n",
            stderr="ollama stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ollama.write_logs(configuration, tmp_path, "ollama-sidecar-1")

    metadata = json.loads((tmp_path / "ollama-sidecar-metadata.json").read_text())
    assert (tmp_path / "ollama-sidecar-stdout.txt").read_text() == "ollama stdout\n"
    assert (tmp_path / "ollama-sidecar-stderr.txt").read_text() == "ollama stderr\n"
    assert metadata == {
        "container_name": "ollama-sidecar-1",
        "image_name": configuration.ollama_image_name,
        "models": ["phi4-mini:latest", "qwen3:4b"],
        "log_command": ["docker", "logs", "ollama-sidecar-1"],
        "log_returncode": 0,
    }


def _build_expected_mcp_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    container_name: str,
) -> list[str]:
    no_proxy_hosts = wiring.build_mcp_sidecar_no_proxy_hosts(configuration)
    database_options = wiring.build_mcp_sidecar_database_environment_options(
        configuration
    )
    return mcp.build_run_command(
        configuration,
        run_directory,
        network_name,
        container_name,
        no_proxy_hosts,
        database_options,
    )


def _create_code_execution_configuration() -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"code_execution"}),
    )


def _create_haproxy_configuration(
    ports: tuple[int, ...] = (3306,),
) -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"haproxy"}),
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=ports,
        ),
    )


def _create_jina_reader_configuration() -> DockerConfiguration:
    configuration = _create_network_configuration()
    return replace(
        configuration,
        enabled_capabilities=frozenset({"jina_reader"}),
    )


def _create_locked_down_configuration() -> DockerConfiguration:
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=hardening.base_locked_down_profile(),
    )


def _create_network_configuration() -> DockerConfiguration:
    profile = hardening.base_locked_down_profile()
    network_gateway = NetworkGatewayProfile(
        image_name="ubuntu/squid:latest",
        proxy_host="egress-gateway",
        proxy_port=3128,
    )
    profile = replace(
        profile,
        network_gateway=network_gateway,
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
        mcp_sidecar_tools=("get_active_items",),
    )


def _create_ollama_configuration(base_directory: Path) -> DockerConfiguration:
    configuration = _create_network_configuration()
    models = ("phi4-mini:latest", "qwen3:4b")
    profile = replace(
        configuration.profile,
        environment=tuple(
            policy
            for policy in configuration.profile.environment
            if policy.name != "OPENAI_API_KEY"
        ),
    )
    return replace(
        configuration,
        base_directory=base_directory,
        enabled_capabilities=frozenset({"openai_agents", "ollama"}),
        profile=profile,
        ollama_models=models,
        ollama_image_name=resolve_ollama_image_name(models),
    )


def _option_value(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def _option_values(command: list[str], option: str) -> list[str]:
    return [
        value
        for index, value in enumerate(command)
        if index > 0 and command[index - 1] == option
    ]
