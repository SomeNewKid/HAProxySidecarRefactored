"""Tests for resources."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_sidecar.resources import ANSWER_FORMAT_RESOURCE_URI, get_answer_format


def test_get_answer_format_writes_audit_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify sidecar resource reads are written to the audit log."""
    audit_log_path = tmp_path / "mcp-sidecar-tool-calls.jsonl"
    monkeypatch.setenv("MCP_SIDECAR_AUDIT_LOG_PATH", str(audit_log_path))

    answer_format = get_answer_format()

    records = _read_jsonl(audit_log_path)
    assert "## Recommended Approach" in answer_format
    assert records[0]["type"] == "resource"
    assert records[0]["resource"] == ANSWER_FORMAT_RESOURCE_URI
    assert records[0]["arguments"] == {}
    assert records[0]["success"] is True
    assert "## Recommended Approach" in str(records[0]["result_preview"])


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
