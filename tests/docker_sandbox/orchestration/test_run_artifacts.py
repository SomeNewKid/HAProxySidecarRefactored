"""Tests for Docker sandbox initial run artifact writing."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening
from docker_sandbox.models import (
    DockerConfiguration,
    HAProxyConfiguration,
    NetworkGatewayProfile,
)
from docker_sandbox.orchestration import environment, run_artifacts


def test_write_initial_persists_run_and_sidecar_configuration_artifacts(
    tmp_path: Path,
) -> None:
    """Verify initial sandbox run artifacts are written together."""
    configuration = _create_configuration(tmp_path)
    run_context = environment.create_run_context(
        configuration,
        "2026-07-20-16-00-00",
    )
    run_context.run_directory.mkdir(parents=True)

    config_data = run_artifacts.write_initial(configuration, run_context)

    assert (run_context.run_directory / "Dockerfile").read_text() == "FROM scratch\n"
    assert json.loads(
        (run_context.run_directory / "sandbox-spec.json").read_text()
    ) == {
        "schema_version": 1,
    }
    assert (run_context.run_directory / "resolved-profile.json").is_file()
    assert json.loads((run_context.run_directory / "config.json").read_text()) == (
        config_data
    )
    assert config_data["working_directory"] == run_context.remote_run_directory
    assert "http_port 3128" in (run_context.run_directory / "squid.conf").read_text()
    assert json.loads(
        (run_context.run_directory / "mcp-sidecar-exposure.json").read_text()
    ) == {
        "tools": ["jina_read_url"],
        "resources": ["answer_format"],
    }
    assert (
        "server host host.docker.internal:3306"
        in (run_context.run_directory / "haproxy.cfg").read_text()
    )


def _create_configuration(base_directory: Path) -> DockerConfiguration:
    profile = hardening.base_locked_down_profile()
    profile = replace(
        profile,
        network_gateway=NetworkGatewayProfile(
            image_name="ubuntu/squid:latest",
            proxy_host="egress-gateway",
            proxy_port=3128,
            allowed_domains=(".example.com",),
        ),
    )
    return DockerConfiguration(
        base_directory=base_directory,
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
        generated_dockerfile="FROM scratch",
        resolved_spec={"schema_version": 1},
        enabled_capabilities=frozenset({"haproxy"}),
        mcp_sidecar_tools=("jina_read_url",),
        mcp_sidecar_resources=("answer_format",),
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=(3306,),
        ),
    )
