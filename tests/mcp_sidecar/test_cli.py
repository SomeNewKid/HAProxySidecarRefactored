"""Tests for cli."""

from __future__ import annotations

from mcp_sidecar.cli import _parse_arguments


def test_parse_arguments_defaults_to_streamable_http() -> None:
    """Verify the sidecar defaults to an HTTP transport for containers."""
    arguments = _parse_arguments([])

    assert arguments.transport == "streamable-http"
    assert arguments.host == "0.0.0.0"
    assert arguments.port == 8000
