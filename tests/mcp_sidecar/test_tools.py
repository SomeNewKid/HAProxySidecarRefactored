"""Tests for tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_sidecar.tools import (
    get_active_items,
    get_html_element_name,
    jina_read_url,
    microsoft_code_sample_search,
    microsoft_docs_fetch,
    microsoft_docs_search,
    run_python_script,
)

pytestmark = pytest.mark.anyio


async def test_microsoft_docs_search_writes_audit_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Microsoft wrapper calls are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    async def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        _ = tool_name
        _ = arguments
        return "search result"

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setattr("mcp_sidecar.tools._call_microsoft_learn_tool", fake_call)

    assert await microsoft_docs_search("azure functions") == "search result"

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "microsoft_docs_search"
    assert records[0]["arguments"] == {"query": "azure functions"}
    assert records[0]["success"] is True
    assert records[0]["result_preview"] == "search result"


async def test_get_active_items_rejects_malformed_credentials(monkeypatch) -> None:
    """Verify credentials must use the shared sandbox tester format."""
    monkeypatch.setenv("SANDBOX_TESTER_MARIADB_CREDENTIALS", "sandbox_tester.secret")

    with pytest.raises(RuntimeError, match="username,password"):
        await get_active_items()


async def test_microsoft_docs_search_audits_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify failed Microsoft wrapper calls are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    async def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        _ = tool_name
        _ = arguments
        raise RuntimeError("upstream failed")

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setattr("mcp_sidecar.tools._call_microsoft_learn_tool", fake_call)

    with pytest.raises(RuntimeError, match="upstream failed"):
        await microsoft_docs_search("azure functions")

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "microsoft_docs_search"
    assert records[0]["arguments"] == {"query": "azure functions"}
    assert records[0]["success"] is False
    assert records[0]["error_type"] == "RuntimeError"
    assert records[0]["error"] == "upstream failed"


async def test_jina_read_url_raises_clear_error_for_non_success(monkeypatch) -> None:
    """Verify non-2xx Reader responses produce clear errors."""

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def getcode(self) -> int:
            return 502

        def read(self) -> bytes:
            return b"bad gateway"

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        _ = url
        _ = timeout
        return FakeResponse()

    monkeypatch.setattr("mcp_sidecar.tools.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Jina Reader returned HTTP 502"):
        await jina_read_url("https://example.com")


async def test_microsoft_docs_search_calls_upstream_tool(monkeypatch) -> None:
    """Verify Microsoft docs search forwards to the upstream MCP tool."""
    calls = []

    async def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "search result"

    monkeypatch.setattr("mcp_sidecar.tools._call_microsoft_learn_tool", fake_call)

    assert await microsoft_docs_search("azure functions") == "search result"
    assert calls == [("microsoft_docs_search", {"query": "azure functions"})]


def test_get_html_element_name_writes_audit_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify local sidecar tool calls are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"
    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))

    assert get_html_element_name() == "<table>"

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "get_html_element_name"
    assert records[0]["arguments"] == {}
    assert records[0]["success"] is True
    assert records[0]["result_preview"] == "<table>"


async def test_get_active_items_queries_mariadb_and_returns_json(
    monkeypatch,
) -> None:
    """Verify active items are fetched from MariaDB through configured env."""
    connections = []

    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def execute(self, query: str) -> None:
            connections.append({"query": query})

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {
                    "id": 2,
                    "item_key": "bravo",
                    "title": "Bravo test item",
                    "status": "active",
                    "notes": "Seed record for update tests.",
                    "quantity": 2,
                    "created_at": "2026-07-07 16:08:35",
                    "updated_at": "2026-07-07 16:08:35",
                }
            ]

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            connections.append({"closed": True})

    def fake_connect(settings: dict[str, object]) -> FakeConnection:
        connections.append(settings)
        return FakeConnection()

    monkeypatch.setenv("MARIADB_HOST", "haproxy-sidecar")
    monkeypatch.setenv("MARIADB_PORT", "3306")
    monkeypatch.setenv("MARIADB_DATABASE", "agent_allowed")
    monkeypatch.setenv(
        "SANDBOX_TESTER_MARIADB_CREDENTIALS",
        "sandbox_tester,secret",
    )
    monkeypatch.setattr("mcp_sidecar.tools._connect_to_mariadb", fake_connect)

    result = await get_active_items()

    assert json.loads(result) == [
        {
            "id": 2,
            "item_key": "bravo",
            "title": "Bravo test item",
            "status": "active",
            "notes": "Seed record for update tests.",
            "quantity": 2,
            "created_at": "2026-07-07 16:08:35",
            "updated_at": "2026-07-07 16:08:35",
        }
    ]
    assert connections[0] == {
        "host": "haproxy-sidecar",
        "port": 3306,
        "user": "sandbox_tester",
        "password": "secret",
        "database": "agent_allowed",
    }
    assert "WHERE status = 'active'" in str(connections[1]["query"])
    assert "ORDER BY id" in str(connections[1]["query"])
    assert connections[2] == {"closed": True}


async def test_get_active_items_rejects_invalid_port(monkeypatch) -> None:
    """Verify MariaDB port values are validated before connection."""
    monkeypatch.setenv("SANDBOX_TESTER_MARIADB_CREDENTIALS", "sandbox_tester,secret")
    monkeypatch.setenv("MARIADB_PORT", "not-a-port")

    with pytest.raises(RuntimeError, match="MARIADB_PORT"):
        await get_active_items()


async def test_run_python_script_audits_metadata_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify MCP audit logs omit submitted source code."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    def fake_run(script: str, args: list[str], timeout_seconds: int | None):
        _ = script
        _ = args
        _ = timeout_seconds
        return {
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "timed_out": False,
            "duration_ms": 10,
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setattr("mcp_sidecar.tools._run_python_script_sync", fake_run)

    await run_python_script("def main(argv):\n    print('secret')\n", ["a"], 5)

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "run_python_script"
    assert records[0]["arguments"] == {
        "script_length": 36,
        "args_count": 1,
        "timeout_seconds": 5,
        "script_exit_code": 0,
    }
    assert "secret" not in json.dumps(records[0])


async def test_jina_read_url_audits_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify failed Jina Reader tool calls are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def getcode(self) -> int:
            return 502

        def read(self) -> bytes:
            return b"bad gateway"

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        _ = url
        _ = timeout
        return FakeResponse()

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setattr("mcp_sidecar.tools.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Jina Reader returned HTTP 502"):
        await jina_read_url("https://example.com")

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "jina_read_url"
    assert records[0]["arguments"] == {"url": "https://example.com"}
    assert records[0]["success"] is False
    assert records[0]["error_type"] == "RuntimeError"
    assert records[0]["error"] == (
        "Jina Reader returned HTTP 502 for URL: https://example.com"
    )


async def test_jina_read_url_rejects_relative_urls() -> None:
    """Verify Jina Reader rejects URLs without a host."""
    with pytest.raises(ValueError, match="fully-qualified HTTP or HTTPS"):
        await jina_read_url("/docs/page")


async def test_run_python_script_calls_code_sidecar(monkeypatch) -> None:
    """Verify Python execution requests are forwarded to the code sidecar."""
    requested_payloads = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return (
                b'{"exit_code": 0, "stdout": "42\\n", "stderr": "", '
                b'"timed_out": false, "duration_ms": 10, '
                b'"stdout_truncated": false, "stderr_truncated": false}'
            )

    def fake_urlopen(request, timeout: float) -> FakeResponse:
        requested_payloads.append((request.full_url, request.data, timeout))
        return FakeResponse()

    monkeypatch.setenv("CODE_SIDECAR_URL", "http://code-sidecar:8090")
    monkeypatch.setattr("mcp_sidecar.tools.urlopen", fake_urlopen)

    result = await run_python_script(
        "def main(argv):\n    print(42)\n    return 0\n",
        args=["x"],
        timeout_seconds=3,
    )

    assert result["exit_code"] == 0
    assert result["stdout"] == "42\n"
    assert requested_payloads[0][0] == "http://code-sidecar:8090/run"
    assert json.loads(requested_payloads[0][1]) == {
        "script": "def main(argv):\n    print(42)\n    return 0\n",
        "args": ["x"],
        "timeout_seconds": 3,
    }
    assert requested_payloads[0][2] == 5.0


async def test_jina_read_url_rejects_non_http_urls() -> None:
    """Verify Jina Reader only accepts fully-qualified HTTP or HTTPS URLs."""
    with pytest.raises(ValueError, match="fully-qualified HTTP or HTTPS"):
        await jina_read_url("file:///etc/passwd")


async def test_get_active_items_writes_audit_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify active item reads are audited without credentials."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    def fake_get_active_items_sync() -> str:
        return '[{"id": 2, "status": "active"}]'

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setenv("MARIADB_HOST", "haproxy-sidecar")
    monkeypatch.setenv("MARIADB_PORT", "3306")
    monkeypatch.setenv("MARIADB_DATABASE", "agent_allowed")
    monkeypatch.setenv(
        "SANDBOX_TESTER_MARIADB_CREDENTIALS",
        "sandbox_tester,secret",
    )
    monkeypatch.setattr(
        "mcp_sidecar.tools._get_active_items_sync",
        fake_get_active_items_sync,
    )

    assert await get_active_items() == '[{"id": 2, "status": "active"}]'

    records = _read_jsonl(audit_log_path)
    assert records[0]["tool"] == "get_active_items"
    assert records[0]["arguments"] == {
        "host": "haproxy-sidecar",
        "port": "3306",
        "database": "agent_allowed",
    }
    assert records[0]["success"] is True
    assert "secret" not in json.dumps(records[0])


async def test_jina_read_url_calls_local_reader_endpoint(monkeypatch) -> None:
    """Verify Jina Reader receives the fully-qualified URL through its prefix route."""
    requested_urls = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return b"# Example\n\nReader output."

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        requested_urls.append((url, timeout))
        return FakeResponse()

    monkeypatch.setenv("JINA_READER_URL", "http://jina-reader:8081")
    monkeypatch.setattr("mcp_sidecar.tools.urlopen", fake_urlopen)

    result = await jina_read_url("https://example.com/docs?q=hello world#section")

    assert result == "# Example\n\nReader output."
    assert requested_urls == [
        (
            "http://jina-reader:8081/"
            "https://example.com/docs?q=hello%20world%23section",
            60.0,
        )
    ]


async def test_get_active_items_requires_credentials(monkeypatch) -> None:
    """Verify MariaDB credentials must be supplied by the host environment."""
    monkeypatch.delenv("SANDBOX_TESTER_MARIADB_CREDENTIALS", raising=False)

    with pytest.raises(RuntimeError, match="is not configured"):
        await get_active_items()


async def test_microsoft_docs_fetch_calls_upstream_tool(monkeypatch) -> None:
    """Verify Microsoft docs fetch forwards to the upstream MCP tool."""
    calls = []

    async def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "markdown"

    monkeypatch.setattr("mcp_sidecar.tools._call_microsoft_learn_tool", fake_call)

    result = await microsoft_docs_fetch("https://learn.microsoft.com/test")

    assert result == "markdown"
    assert calls == [
        ("microsoft_docs_fetch", {"url": "https://learn.microsoft.com/test"})
    ]


async def test_jina_read_url_writes_audit_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify Jina Reader tool calls are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return b"# Example\n\nReader output."

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        _ = url
        _ = timeout
        return FakeResponse()

    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setattr("mcp_sidecar.tools.urlopen", fake_urlopen)

    result = await jina_read_url("https://example.com")

    records = _read_jsonl(audit_log_path)
    assert result == "# Example\n\nReader output."
    assert records[0]["tool"] == "jina_read_url"
    assert records[0]["arguments"] == {"url": "https://example.com"}
    assert records[0]["success"] is True
    assert records[0]["result_length"] == len(result)
    assert records[0]["result_preview"] == "# Example\n\nReader output."


def test_get_html_element_name_returns_table() -> None:
    """Verify the initial MCP tool returns the expected element."""
    assert get_html_element_name() == "<table>"


async def test_microsoft_code_sample_search_calls_upstream_tool(monkeypatch) -> None:
    """Verify Microsoft code search forwards query and language upstream."""
    calls = []

    async def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "code result"

    monkeypatch.setattr("mcp_sidecar.tools._call_microsoft_learn_tool", fake_call)

    result = await microsoft_code_sample_search("blob storage", "python")

    assert result == "code result"
    assert calls == [
        (
            "microsoft_code_sample_search",
            {"query": "blob storage", "language": "python"},
        )
    ]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
