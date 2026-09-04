"""Tests for shared sandbox capability helpers."""

from __future__ import annotations

from dataclasses import dataclass

from docker_sandbox import capabilities


@dataclass(frozen=True)
class _CapabilitySpec:
    declared_capabilities: tuple[str, ...]

    def has_capability(self, capability: str) -> bool:
        return capability in self.declared_capabilities


def test_supported_capabilities_include_declared_capability_families() -> None:
    """Verify capability family constants stay within the supported set."""
    supported = set(capabilities.SUPPORTED)

    assert set(capabilities.OPENAI_FAMILY) <= supported
    assert set(capabilities.ANTHROPIC_FAMILY) <= supported
    assert set(capabilities.NETWORK_REQUIRED) <= supported
    assert set(capabilities.AGENT_IMAGE_EXCLUDED) <= supported


def test_has_openai_family_capability_detects_openai_family_members() -> None:
    """Verify OpenAI-family membership is resolved through has_capability."""
    spec = _CapabilitySpec((capabilities.LANGCHAIN,))

    assert capabilities.has_openai_family_capability(spec)
    assert not capabilities.has_anthropic_family_capability(spec)


def test_has_anthropic_family_capability_detects_anthropic_family_members() -> None:
    """Verify Anthropic-family membership is resolved through has_capability."""
    spec = _CapabilitySpec((capabilities.ANTHROPIC_PYTHON,))

    assert capabilities.has_anthropic_family_capability(spec)
    assert not capabilities.has_openai_family_capability(spec)
