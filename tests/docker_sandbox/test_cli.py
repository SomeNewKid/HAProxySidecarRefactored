"""Tests for Docker sandbox CLI configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

from docker_sandbox.cli import _configuration_from_arguments
from docker_sandbox.sandbox_spec import resolve_ollama_image_name


def test_haproxy_configuration_is_carried_into_docker_configuration(
    tmp_path: Path,
) -> None:
    """Verify HAProxy settings flow from spec into Docker configuration."""
    spec_path = tmp_path / "sandbox_spec.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'capabilities = ["network", "haproxy"]',
                "[squid_proxy]",
                "allowed_domains = []",
                "allowed_ip_addresses = []",
                "",
                "[haproxy]",
                'backend_host = "host.docker.internal"',
                "ports = [3306, 5432]",
            ]
        ),
        encoding="utf-8",
    )
    arguments = argparse.Namespace(
        base_directory=tmp_path / "docker",
        guest_user="sandbox",
        sandbox_spec=spec_path,
        test_sandbox=False,
    )

    configuration = _configuration_from_arguments(arguments)

    assert configuration.haproxy is not None
    assert configuration.haproxy.backend_host == "host.docker.internal"
    assert configuration.haproxy.ports == (3306, 5432)
    assert configuration.resolved_spec is not None
    assert configuration.resolved_spec["haproxy"] == {
        "backend_host": "host.docker.internal",
        "ports": [3306, 5432],
    }


def test_ollama_configuration_is_carried_into_docker_configuration(
    tmp_path: Path,
) -> None:
    """Verify CLI configuration plumbing preserves Ollama sidecar data."""
    spec_path = tmp_path / "sandbox_spec.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'capabilities = ["network", "ollama"]',
                "[squid_proxy]",
                "allowed_domains = []",
                "allowed_ip_addresses = []",
                "",
                "[ollama_sidecar]",
                'models = ["qwen3:4b", "phi4-mini:latest"]',
            ]
        ),
        encoding="utf-8",
    )
    arguments = argparse.Namespace(
        base_directory=tmp_path / "sandbox",
        guest_user="sandbox",
        sandbox_spec=spec_path,
        test_sandbox=False,
    )

    configuration = _configuration_from_arguments(arguments)

    assert configuration.ollama_models == ("phi4-mini:latest", "qwen3:4b")
    assert configuration.ollama_image_name == resolve_ollama_image_name(
        ("qwen3:4b", "phi4-mini:latest"),
    )
    assert configuration.resolved_spec is not None
    assert configuration.resolved_spec["ollama_image_name"] == (
        configuration.ollama_image_name
    )
