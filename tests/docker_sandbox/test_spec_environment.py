"""Tests for sandbox spec runtime environment resolution."""

from __future__ import annotations

from docker_sandbox import spec_environment
from docker_sandbox.spec_models import SandboxEnvironmentVariable, SandboxSpec


def test_resolve_environment_variables_includes_declared_values() -> None:
    """Verify explicit and host-sourced variables are preserved."""
    spec = SandboxSpec(
        schema_version=1,
        environment_variables=(
            SandboxEnvironmentVariable("API_BASE_URL", value="https://example.com"),
            SandboxEnvironmentVariable("LOCAL_SECRET", from_host=True),
        ),
    )

    assert spec_environment.resolve_environment_variables(spec) == (
        ("API_BASE_URL", "https://example.com"),
        ("LOCAL_SECRET", "[local]"),
    )
    assert spec_environment.resolve_local_environment_variable_names(spec) == frozenset(
        {"LOCAL_SECRET"}
    )


def test_resolve_environment_variables_adds_openai_provider_key() -> None:
    """Verify OpenAI-family capabilities add the host OpenAI API key."""
    spec = SandboxSpec(schema_version=1, capabilities=("openai_agents",))

    assert spec_environment.resolve_environment_variables(spec) == (
        ("OPENAI_API_KEY", "[local]"),
    )
    assert spec_environment.resolve_local_environment_variable_names(spec) == frozenset(
        {"OPENAI_API_KEY"}
    )


def test_resolve_environment_variables_adds_anthropic_provider_key() -> None:
    """Verify Anthropic-family capabilities add the host Anthropic API key."""
    spec = SandboxSpec(schema_version=1, capabilities=("anthropic_python",))

    assert spec_environment.resolve_environment_variables(spec) == (
        ("ANTHROPIC_API_KEY", "[local]"),
    )
    assert spec_environment.resolve_local_environment_variable_names(spec) == frozenset(
        {"ANTHROPIC_API_KEY"}
    )


def test_resolve_environment_variables_does_not_duplicate_provider_key() -> None:
    """Verify explicitly declared provider keys are not appended twice."""
    spec = SandboxSpec(
        schema_version=1,
        capabilities=("openai",),
        environment_variables=(
            SandboxEnvironmentVariable("OPENAI_API_KEY", from_host=True),
        ),
    )

    assert spec_environment.resolve_environment_variables(spec) == (
        ("OPENAI_API_KEY", "[local]"),
    )
