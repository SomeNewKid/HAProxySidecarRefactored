"""Tests for server."""

from __future__ import annotations

from typing import Any, cast

import anyio
import pytest

from mcp_sidecar.resources import ANSWER_FORMAT_RESOURCE_URI
from mcp_sidecar.server import create_mcp_server

pytestmark = pytest.mark.anyio


def test_mcp_server_omits_get_active_items_when_not_declared() -> None:
    """Verify active item access is not exposed unless configured."""
    server = create_mcp_server(tool_names=("get_html_element_name",))

    tools = anyio.run(server.list_tools)
    tool_names = {tool.name for tool in tools}

    assert "get_html_element_name" in tool_names
    assert "get_active_items" not in tool_names


def test_mcp_server_exposes_jina_reader_tool() -> None:
    """Verify the sidecar exposes the Jina Reader wrapper tool."""
    server = create_mcp_server(tool_names=("jina_read_url",))

    tools = anyio.run(server.list_tools)
    tool_names = {tool.name for tool in tools}

    assert "jina_read_url" in tool_names


def test_mcp_server_exposes_code_execution_tool() -> None:
    """Verify the sidecar exposes the Python execution wrapper tool."""
    server = create_mcp_server(tool_names=("run_python_script",))

    tools = anyio.run(server.list_tools)
    tool_names = {tool.name for tool in tools}

    assert "run_python_script" in tool_names


def test_mcp_server_exposes_health_route() -> None:
    """Verify the sidecar exposes a generic HTTP health route."""
    server = create_mcp_server()
    app = server.streamable_http_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/health" in route_paths


def test_mcp_server_exposes_microsoft_learn_wrapper_tools() -> None:
    """Verify the sidecar exposes Microsoft Learn proxy wrapper tools."""
    server = create_mcp_server(
        tool_names=(
            "microsoft_docs_search",
            "microsoft_docs_fetch",
            "microsoft_code_sample_search",
        )
    )

    tools = anyio.run(server.list_tools)
    tool_names = {tool.name for tool in tools}

    assert "microsoft_docs_search" in tool_names
    assert "microsoft_docs_fetch" in tool_names
    assert "microsoft_code_sample_search" in tool_names


def test_mcp_server_exposes_get_active_items_tool() -> None:
    """Verify the sidecar can expose the active items database tool."""
    server = create_mcp_server(tool_names=("get_active_items",))

    tools = anyio.run(server.list_tools)
    tool_names = {tool.name for tool in tools}

    assert "get_active_items" in tool_names


def test_mcp_server_exposes_nothing_by_default(monkeypatch) -> None:
    """Verify MCP tools and resources are disabled unless explicitly configured."""
    monkeypatch.delenv("MCP_SIDECAR_EXPOSURE_PATH", raising=False)
    server = create_mcp_server()

    tools = anyio.run(server.list_tools)
    resources = anyio.run(server.list_resources)

    assert tools == []
    assert resources == []


def test_mcp_server_rejects_unknown_resource() -> None:
    """Verify unknown MCP resource names fail closed."""
    with pytest.raises(RuntimeError, match="Unknown MCP sidecar resource"):
        create_mcp_server(resource_names=("missing_resource",))


def test_mcp_server_rejects_unknown_tool() -> None:
    """Verify unknown MCP tool names fail closed."""
    with pytest.raises(RuntimeError, match="Unknown MCP sidecar tool"):
        create_mcp_server(tool_names=("missing_tool",))


async def test_mcp_server_exposes_html_element_tool() -> None:
    """Verify the MCP server exposes and runs the HTML element tool."""
    server = create_mcp_server(tool_names=("get_html_element_name",))

    tools = await server.list_tools()
    tool_names = {tool.name for tool in tools}
    result = await server.call_tool("get_html_element_name", {})
    content_blocks, structured_content = cast(tuple[list[Any], dict[str, str]], result)

    assert "get_html_element_name" in tool_names
    assert content_blocks[0].text == "<table>"
    assert structured_content == {"result": "<table>"}


async def test_mcp_server_exposes_answer_format_resource() -> None:
    """Verify the MCP server exposes and reads the answer format resource."""
    server = create_mcp_server(resource_names=("answer_format",))

    resources = await server.list_resources()
    resource_uris = {str(resource.uri) for resource in resources}
    result = await server.read_resource(ANSWER_FORMAT_RESOURCE_URI)
    contents = list(result)
    content = contents[0].content

    assert ANSWER_FORMAT_RESOURCE_URI in resource_uris
    assert isinstance(content, str)
    assert "## Recommended Approach" in content
    assert contents[0].mime_type == "text/markdown"
