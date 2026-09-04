"""Tests for sandbox spec validation rules."""

from __future__ import annotations

import pytest

from docker_sandbox import spec_validation


def test_validate_top_level_keys_rejects_unknown_keys() -> None:
    """Verify unsupported top-level spec keys fail closed."""
    data: dict[str, object] = {"schema_version": 1, "allowed_domains": []}

    with pytest.raises(ValueError, match="Unsupported sandbox spec key"):
        spec_validation.validate_top_level_keys(data)


def test_validate_supported_capabilities_rejects_unknown_capability() -> None:
    """Verify unsupported capability names fail closed."""
    with pytest.raises(ValueError, match="Unsupported sandbox capability"):
        spec_validation.validate_supported_capabilities(("network", "frobnicate"))


def test_validate_network_settings_requires_network_for_provider_capability() -> None:
    """Verify provider capabilities cannot silently enable networking."""
    with pytest.raises(ValueError, match="requires the network capability"):
        spec_validation.validate_network_settings(
            ("openai_agents",),
            (),
            (),
        )


def test_validate_network_settings_rejects_url_allowlist_entries() -> None:
    """Verify domain allowlist entries must be hostnames."""
    with pytest.raises(ValueError, match="host names, not URLs or paths"):
        spec_validation.validate_network_settings(
            ("network",),
            ("https://www.example.com",),
            (),
        )


def test_validate_mcp_sidecar_settings_requires_code_execution_capability() -> None:
    """Verify the Python execution MCP tool requires its code sidecar."""
    with pytest.raises(ValueError, match="requires code_execution"):
        spec_validation.validate_mcp_sidecar_settings(
            ("network", "mcp_client"),
            ("run_python_script",),
        )
