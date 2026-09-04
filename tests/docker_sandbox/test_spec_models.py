"""Tests for normalized sandbox specification models."""

from __future__ import annotations

from docker_sandbox.models import HAProxyConfiguration
from docker_sandbox.spec_models import SandboxEnvironmentVariable, SandboxSpec


def test_sandbox_spec_serializes_normalized_dictionary() -> None:
    """Verify normalized model data is JSON-safe and deterministically ordered."""
    spec = SandboxSpec(
        schema_version=1,
        capabilities=("network", "haproxy"),
        allowed_domains=(".example.com",),
        environment_variables=(
            SandboxEnvironmentVariable("Z_VAR", value="z"),
            SandboxEnvironmentVariable("A_VAR", from_host=True),
        ),
        mcp_sidecar_tools=("get_active_items",),
        haproxy=HAProxyConfiguration(
            backend_host="host.docker.internal",
            ports=(3306,),
        ),
    )

    data = spec.to_dict()

    assert data["environment_variables"] == [
        {"name": "A_VAR", "from_host": True},
        {"name": "Z_VAR", "value": "z"},
    ]
    assert data["haproxy"] == {
        "backend_host": "host.docker.internal",
        "ports": [3306],
    }


def test_agent_image_dict_excludes_sidecar_image_only_capabilities() -> None:
    """Verify sidecar-only image inputs do not affect the agent image data."""
    spec = SandboxSpec(
        schema_version=1,
        capabilities=("network", "haproxy", "ollama"),
        ollama_models=("qwen3:4b",),
    )

    data = spec.to_agent_image_dict()

    assert data["capabilities"] == ["network"]
    assert "haproxy" not in data
    assert "ollama_sidecar" not in data


def test_ollama_image_hash_is_independent_from_agent_image_hash() -> None:
    """Verify Ollama image data is hashed independently from agent image data."""
    first = SandboxSpec(
        schema_version=1,
        capabilities=("network", "ollama"),
        ollama_models=("qwen3:4b",),
    )
    second = SandboxSpec(
        schema_version=1,
        capabilities=("network", "openai", "ollama"),
        ollama_models=("qwen3:4b",),
    )

    assert first.agent_image_hash != second.agent_image_hash
    assert first.ollama_image_hash == second.ollama_image_hash
    assert first.ollama_image_name == second.ollama_image_name
