"""Tests for haproxy."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.profiles import LOCKED_DOWN_PROFILE_NAME, get_docker_profile
from docker_sandbox.sandbox_spec import resolve_ollama_image_name
from docker_sandbox.sidecars import (
    haproxy,
    mcp,
)


def test_haproxy_configuration_proxies_declared_ports() -> None:
    """Verify HAProxy config maps each listen port to the same backend port."""
    config = haproxy.generate_configuration(
        "host.docker.internal",
        (3306, 5432),
    )

    assert "mode tcp" in config
    assert "frontend tcp_3306" in config
    assert "bind *:3306" in config
    assert "default_backend backend_3306" in config
    assert "server host host.docker.internal:3306" in config
    assert "frontend tcp_5432" in config
    assert "bind *:5432" in config
    assert "server host host.docker.internal:5432" in config


def test_haproxy_sidecar_cleanup_removes_sidecar_before_network_cleanup() -> None:
    """Verify HAProxy sidecar cleanup removes the sidecar container."""
    configuration = _create_haproxy_configuration()

    cleanup_commands = haproxy.build_cleanup_commands(
        configuration,
        "haproxy-sidecar-1",
    )

    assert cleanup_commands == [["docker", "rm", "--force", "haproxy-sidecar-1"]]


def test_haproxy_sidecar_config_probe_command_checks_mounted_config() -> None:
    """Verify HAProxy config readiness checks the mounted runtime config."""
    command = haproxy.build_config_probe_command("haproxy-sidecar-1")

    assert command == [
        "docker",
        "exec",
        "haproxy-sidecar-1",
        "haproxy",
        "-c",
        "-f",
        "/usr/local/etc/haproxy/haproxy.cfg",
    ]


def test_haproxy_sidecar_container_name_is_created_for_agent_network_runs() -> None:
    """Verify haproxy runs get an HAProxy sidecar container."""
    configuration = _create_haproxy_configuration()

    container_name = haproxy.build_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name == "haproxy-sidecar-2026-07-20-16-00-00"


def test_haproxy_sidecar_container_name_is_omitted_without_capability() -> None:
    """Verify network access alone does not get an HAProxy sidecar container."""
    configuration = _create_network_configuration()

    container_name = haproxy.build_container_name(
        configuration,
        "2026-07-20-16-00-00",
    )

    assert container_name is None


def test_haproxy_sidecar_network_connect_command_adds_internal_alias() -> None:
    """Verify HAProxy joins the internal network under the sidecar alias."""
    command = haproxy.build_network_connect_command(
        "sandbox-agent-net-1",
        "haproxy-sidecar-1",
    )

    assert command == [
        "docker",
        "network",
        "connect",
        "--alias",
        "haproxy-sidecar",
        "sandbox-agent-net-1",
        "haproxy-sidecar-1",
    ]


def test_haproxy_sidecar_process_probe_command_uses_pidof() -> None:
    """Verify HAProxy process readiness uses a self-contained container command."""
    command = haproxy.build_process_probe_command("haproxy-sidecar-1")

    assert command == [
        "docker",
        "exec",
        "haproxy-sidecar-1",
        "pidof",
        "haproxy",
    ]


def test_haproxy_sidecar_run_command_uses_internal_network(
    tmp_path: Path,
) -> None:
    """Verify HAProxy starts on the internal Docker network with a mounted config."""
    command = haproxy.build_run_command(
        tmp_path,
        "haproxy-sidecar-1",
    )

    assert command[:4] == ["docker", "run", "--detach", "--name"]
    assert "haproxy-sidecar-1" in command
    assert _option_value(command, "--network") == "bridge"
    assert _option_value(command, "--add-host") == "host.docker.internal:host-gateway"
    assert _option_values(command, "--mount") == [
        (
            f"type=bind,source={tmp_path / 'haproxy.cfg'},"
            "target=/usr/local/etc/haproxy/haproxy.cfg,readonly"
        )
    ]
    assert command[-1] == "haproxy:latest"
    assert "--publish" not in command
    assert "-p" not in command


def test_haproxy_start_persists_start_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify HAProxy startup command results are persisted for debugging."""
    configuration = _create_haproxy_configuration()
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
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="haproxy started\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    commands = haproxy.start(
        configuration,
        tmp_path,
        "sandbox-agent-net-1",
        "haproxy-sidecar-1",
    )

    start_results = json.loads(
        (tmp_path / "haproxy-sidecar-start-results.json").read_text()
    )
    assert commands is not None
    assert commands == [
        haproxy.build_run_command(
            tmp_path,
            "haproxy-sidecar-1",
        ),
        haproxy.build_network_connect_command(
            "sandbox-agent-net-1",
            "haproxy-sidecar-1",
        ),
    ]
    assert calls == commands
    assert start_results == [
        {
            "command": commands[0],
            "returncode": 0,
            "stdout": "haproxy started\n",
            "stderr": "",
        },
        {
            "command": commands[1],
            "returncode": 0,
            "stdout": "haproxy started\n",
            "stderr": "",
        },
    ]


def test_haproxy_wait_until_ready_persists_readiness_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify HAProxy readiness records process and config validation results."""
    configuration = _create_haproxy_configuration()
    calls = []

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
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="1\n" if command[-2:] == ["pidof", "haproxy"] else "",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    haproxy.wait_until_ready(
        configuration,
        tmp_path,
        "haproxy-sidecar-1",
    )

    readiness_results = json.loads(
        (tmp_path / "haproxy-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["container_name"] == "haproxy-sidecar-1"
    assert (
        readiness_results["configuration_path"] == "/usr/local/etc/haproxy/haproxy.cfg"
    )
    assert readiness_results["ready"] is True
    assert [phase["name"] for phase in readiness_results["phases"]] == [
        "process",
        "configuration",
    ]
    assert [phase["attempts"][0]["command"] for phase in readiness_results["phases"]]
    assert calls == [
        haproxy.build_process_probe_command("haproxy-sidecar-1"),
        haproxy.build_config_probe_command("haproxy-sidecar-1"),
    ]


def test_haproxy_wait_until_ready_raises_when_config_check_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify HAProxy readiness stops when config validation fails."""
    configuration = _create_haproxy_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        _ = capture_output
        _ = text
        returncode = 0
        stderr = ""
        if command[3] == "haproxy":
            returncode = 1
            stderr = "Fatal errors found in configuration.\n"

        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout="1\n" if command[3] == "pidof" else "",
            stderr=stderr,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="HAProxy sidecar did not become ready"):
        haproxy.wait_until_ready(
            configuration,
            tmp_path,
            "haproxy-sidecar-1",
            intervals_seconds=(0.0,),
        )

    readiness_results = json.loads(
        (tmp_path / "haproxy-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["ready"] is False
    assert [phase["name"] for phase in readiness_results["phases"]] == [
        "process",
        "configuration",
    ]
    assert readiness_results["phases"][1]["attempts"][0]["stderr"] == (
        "Fatal errors found in configuration.\n"
    )


def test_haproxy_wait_until_ready_raises_when_process_check_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify HAProxy readiness stops when the process is not running."""
    configuration = _create_haproxy_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        _ = capture_output
        _ = text
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="HAProxy sidecar did not become ready"):
        haproxy.wait_until_ready(
            configuration,
            tmp_path,
            "haproxy-sidecar-1",
            intervals_seconds=(0.0,),
        )

    readiness_results = json.loads(
        (tmp_path / "haproxy-sidecar-readiness-results.json").read_text()
    )
    assert readiness_results["ready"] is False
    assert [phase["name"] for phase in readiness_results["phases"]] == ["process"]


def test_haproxy_write_configuration_writes_run_artifact(tmp_path: Path) -> None:
    """Verify HAProxy config is generated inside the run directory."""
    configuration = _create_haproxy_configuration()

    haproxy.write_configuration(configuration, tmp_path)

    config = (tmp_path / "haproxy.cfg").read_text(encoding="utf-8")
    assert "bind *:3306" in config
    assert "server host host.docker.internal:3306" in config


def test_haproxy_write_logs_persists_debug_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify HAProxy logs are persisted as text and metadata artifacts."""
    configuration = _create_haproxy_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "logs", "haproxy-sidecar-1"]
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="haproxy stdout\n",
            stderr="haproxy stderr\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    haproxy.write_logs(configuration, tmp_path, "haproxy-sidecar-1")

    metadata = json.loads((tmp_path / "haproxy-sidecar-metadata.json").read_text())
    assert (tmp_path / "haproxy-sidecar-stdout.txt").read_text() == ("haproxy stdout\n")
    assert (tmp_path / "haproxy-sidecar-stderr.txt").read_text() == ("haproxy stderr\n")
    assert metadata == {
        "container_name": "haproxy-sidecar-1",
        "image_name": "haproxy:latest",
        "backend_host": "host.docker.internal",
        "ports": [3306],
        "log_command": ["docker", "logs", "haproxy-sidecar-1"],
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
        profile=get_docker_profile(LOCKED_DOWN_PROFILE_NAME),
    )


def _create_network_configuration() -> DockerConfiguration:
    profile = get_docker_profile(LOCKED_DOWN_PROFILE_NAME)
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
