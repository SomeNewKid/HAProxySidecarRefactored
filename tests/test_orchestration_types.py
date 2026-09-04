"""Tests for shared Docker sandbox orchestration types."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from docker_sandbox.models import (
    DockerConfiguration,
    DockerProfile,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.orchestration.artifacts import (
    command_result_data,
    write_docker_log_artifacts,
    write_json_artifact,
)
from docker_sandbox.orchestration.docker import (
    build_docker_remove_command,
    capture_docker_logs,
    run_captured_command,
)
from docker_sandbox.orchestration.types import CommandResult, RunContext, SidecarPlan


def test_command_result_captures_process_output() -> None:
    """Verify command results have the same shape as captured process output."""
    result = CommandResult(
        returncode=7,
        stdout="out\n",
        stderr="err\n",
    )

    assert result.returncode == 7
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


def test_run_context_groups_run_paths_and_names() -> None:
    """Verify run context groups the names needed throughout a run."""
    context = RunContext(
        timestamp="2026-07-20-16-00-00",
        run_id="run-2026-07-20-16-00-00",
        run_directory=Path(".docker_sandbox/runs/run-2026-07-20-16-00-00"),
        container_name="sandbox-agent-run-2026-07-20-16-00-00",
        remote_run_directory="/sandbox-work/run-2026-07-20-16-00-00",
        allowed_directory="/sandbox-work/run-2026-07-20-16-00-00/allowed",
        denied_directory="/sandbox-denied",
        network_name="sandbox-agent-net-2026-07-20-16-00-00",
        gateway_container_name="sandbox-agent-gateway-2026-07-20-16-00-00",
    )

    assert context.network_name == "sandbox-agent-net-2026-07-20-16-00-00"
    assert context.gateway_container_name == (
        "sandbox-agent-gateway-2026-07-20-16-00-00"
    )


def test_sidecar_plan_groups_commands_and_artifacts() -> None:
    """Verify sidecar plans can describe start, readiness, cleanup, and logs."""
    plan = SidecarPlan(
        name="example",
        container_name="example-sidecar-1",
        start_commands=(("docker", "run", "example"),),
        cleanup_commands=(("docker", "rm", "--force", "example-sidecar-1"),),
        readiness_results_file_name="example-readiness-results.json",
        log_file_names=("example-stdout.txt", "example-stderr.txt"),
    )

    assert plan.name == "example"
    assert plan.start_commands == (("docker", "run", "example"),)
    assert plan.cleanup_commands == (("docker", "rm", "--force", "example-sidecar-1"),)
    assert plan.readiness_results_file_name == "example-readiness-results.json"
    assert plan.log_file_names == ("example-stdout.txt", "example-stderr.txt")


def test_write_json_artifact_serializes_paths(tmp_path: Path) -> None:
    """Verify JSON artifacts serialize common orchestration values."""
    path = tmp_path / "artifact.json"

    write_json_artifact(path, {"path": tmp_path / "child", "items": ("a", "b")})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "path": str(tmp_path / "child"),
        "items": ["a", "b"],
    }


def test_command_result_data_includes_command() -> None:
    """Verify command result data preserves command and captured output."""
    result = CommandResult(
        returncode=1,
        stdout="out",
        stderr="err",
        command=("ignored",),
    )

    assert command_result_data(["docker", "ps"], result) == {
        "command": ["docker", "ps"],
        "returncode": 1,
        "stdout": "out",
        "stderr": "err",
    }


def test_write_docker_log_artifacts_writes_standard_files(tmp_path: Path) -> None:
    """Verify Docker log artifact writing is shared across sidecars."""
    result = CommandResult(
        returncode=0,
        stdout="container stdout\n",
        stderr="container stderr\n",
        command=("docker", "logs", "sidecar-1"),
    )

    write_docker_log_artifacts(
        run_directory=tmp_path,
        log_result=result,
        log_file_name="sidecar-logs.json",
        stdout_file_name="sidecar-stdout.txt",
        stderr_file_name="sidecar-stderr.txt",
        metadata_file_name="sidecar-metadata.json",
        metadata={"container_name": "sidecar-1"},
    )

    assert (tmp_path / "sidecar-stdout.txt").read_text() == "container stdout\n"
    assert (tmp_path / "sidecar-stderr.txt").read_text() == "container stderr\n"
    assert '"returncode": 0' in (tmp_path / "sidecar-logs.json").read_text()
    metadata = (tmp_path / "sidecar-metadata.json").read_text()
    assert '"container_name": "sidecar-1"' in metadata
    assert '"log_command": [' in metadata
    assert '"log_returncode": 0' in metadata


def test_build_docker_remove_command() -> None:
    """Verify Docker remove command construction is shared."""
    command = build_docker_remove_command("container-1")

    assert command == ["docker", "rm", "--force", "container-1"]


def test_run_captured_command_returns_shared_result(monkeypatch) -> None:
    """Verify captured command execution returns a shared command result."""

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "version"]
        assert check is False
        assert capture_output is True
        assert text is True
        assert kwargs == {"encoding": "utf-8", "errors": "replace"}
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_captured_command(
        ["docker", "version"],
        encoding="utf-8",
        errors="replace",
    )

    assert result == CommandResult(
        returncode=0,
        stdout="ok\n",
        stderr="",
        command=("docker", "version"),
    )


def test_capture_docker_logs_uses_docker_logs_command(monkeypatch) -> None:
    """Verify Docker log capture uses the expected command."""
    commands = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="logs\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = capture_docker_logs("sidecar-1")

    assert commands == [["docker", "logs", "sidecar-1"]]
    assert result.stdout == "logs\n"


def test_wiring_orders_enabled_sidecars() -> None:
    """Verify sidecar startup order is centralized in wiring."""
    configuration = _create_wired_configuration()

    assert wiring.ordered_sidecars(configuration) == (
        wiring.SQUID_GATEWAY,
        wiring.JINA_READER,
        wiring.CODE_EXECUTION,
        wiring.HAPROXY,
        wiring.OLLAMA,
        wiring.MCP,
    )


def test_wiring_omits_mcp_without_exposed_tools_or_resources() -> None:
    """Verify MCP is driven by exposure, not by a single sidecar capability."""
    configuration = _create_wired_configuration(mcp_sidecar_tools=())

    assert wiring.MCP not in wiring.ordered_sidecars(configuration)
    assert wiring.should_start_mcp_sidecar(configuration) is False


def test_wiring_documents_plain_sidecar_dependencies() -> None:
    """Verify sidecar dependencies are explicit plain code."""
    assert wiring.sidecar_dependencies(wiring.SQUID_GATEWAY) == ()
    assert wiring.sidecar_dependencies(wiring.JINA_READER) == (wiring.SQUID_GATEWAY,)
    assert wiring.sidecar_dependencies(wiring.OLLAMA) == (wiring.SQUID_GATEWAY,)
    assert wiring.sidecar_dependencies(wiring.MCP) == (
        wiring.SQUID_GATEWAY,
        wiring.JINA_READER,
        wiring.CODE_EXECUTION,
        wiring.HAPROXY,
    )


def test_wiring_builds_mcp_database_environment_options() -> None:
    """Verify MCP gets database settings through HAProxy wiring."""
    configuration = _create_wired_configuration()

    assert wiring.build_mcp_sidecar_database_environment_options(configuration) == [
        "--env",
        "MARIADB_HOST=haproxy-sidecar",
        "--env",
        "MARIADB_PORT=3306",
        "--env",
        "MARIADB_DATABASE=agent_allowed",
        "--env",
        "SANDBOX_TESTER_MARIADB_CREDENTIALS",
    ]


def test_wiring_applies_agent_sidecar_environment() -> None:
    """Verify agent sidecar environment is centralized in wiring."""
    configuration = _create_wired_configuration()
    environment = {"OPENAI_API_KEY": "host-secret", "MARIADB_HOST": "local"}

    wiring.apply_agent_sidecar_environment(
        environment,
        configuration,
        gateway_ip_address="172.18.0.2",
    )

    assert environment["HTTP_PROXY"] == "http://172.18.0.2:3128"
    assert environment["MCP_SIDECAR_URL"] == "http://mcp-sidecar:8000/mcp"
    assert environment["OLLAMA_BASE_URL"] == "http://ollama-sidecar:11434"
    assert environment["OLLAMA_MODEL"] == "qwen3:4b"
    assert "mcp-sidecar" in environment["NO_PROXY"].split(",")
    assert "ollama-sidecar" in environment["NO_PROXY"].split(",")
    assert "MARIADB_HOST" not in environment


def _create_wired_configuration(
    mcp_sidecar_tools: tuple[str, ...] = ("get_active_items",),
) -> DockerConfiguration:
    profile = DockerProfile(
        name="locked-down",
        description="Locked down test profile.",
        image_name="sandbox-agent/sandbox-agent:locked-down",
        network_gateway=NetworkGatewayProfile(
            image_name="ubuntu/squid:latest",
            proxy_host="egress-gateway",
            proxy_port=3128,
            allowed_domains=("example.com",),
            no_proxy_hosts=("localhost",),
        ),
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
        enabled_capabilities=frozenset(
            {
                "jina_reader",
                "code_execution",
                "haproxy",
                "ollama",
            }
        ),
        mcp_sidecar_tools=mcp_sidecar_tools,
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=(3306,),
        ),
        ollama_models=("qwen3:4b",),
        ollama_image_name="sandbox-agent/ollama-sidecar:test",
    )
