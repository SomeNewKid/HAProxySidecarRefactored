"""Tests for squid gateway."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

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
    squid_gateway,
)
from docker_sandbox.sidecars.squid_gateway import build_allowed_domains


def test_start_network_gateway_raises_when_squid_check_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify gateway startup stops when Squid rejects its configuration."""
    configuration = _create_network_configuration()

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        if command[1] == "inspect":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="172.18.0.2\n",
                stderr="",
            )
        if command[1] == "exec":
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="squid.conf is invalid\n",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Squid gateway readiness check failed"):
        squid_gateway.start_gateway(
            configuration,
            tmp_path,
            "sandbox-agent-net-1",
            "sandbox-agent-gateway-1",
        )

    start_results = json.loads((tmp_path / "gateway-start-results.json").read_text())
    assert start_results[-2]["returncode"] == 1
    assert start_results[-2]["stderr"] == "squid.conf is invalid\n"
    assert start_results[-1]["gateway_ip_address"] == "172.18.0.2"


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


def test_gateway_domains_use_only_configured_allowlist() -> None:
    """Verify legacy fixture metadata does not widen the network allowlist."""
    domains = build_allowed_domains(
        (".example.com",),
        {
            "allowed_domain": "ignored.test",
            "git_remote_url": "https://github.com/example/project.git",
        },
    )

    assert domains == (".example.com",)
