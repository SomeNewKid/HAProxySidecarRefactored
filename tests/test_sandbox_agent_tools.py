"""Tests for Sandbox Agent tools."""

from __future__ import annotations

import json

import pytest

from sandbox_agent.tools import (
    capture_site_screenshot,
    get_active_items,
    get_answer_format,
    get_html_element_name,
    inject_code_sidecar_section,
    inject_jina_reader_section,
    inject_ollama_sidecar_section,
    inject_squid_proxy_section,
    jina_read_url,
    microsoft_code_sample_search,
    microsoft_docs_fetch,
    microsoft_docs_search,
    run_python_script,
    save_answer,
    save_html_document,
    validate_html5_element,
)


def test_validate_html5_element_accepts_element_name() -> None:
    """Verify HTML5 element validation accepts a plain element name."""
    result = validate_html5_element("main")

    assert result == {
        "element": "main",
        "is_html5": True,
    }


def test_validate_html5_element_normalizes_angle_brackets() -> None:
    """Verify HTML5 element validation accepts bracketed element names."""
    result = validate_html5_element("<IMG />")

    assert result == {
        "element": "img",
        "is_html5": True,
    }


def test_validate_html5_element_rejects_unknown_name() -> None:
    """Verify HTML5 element validation rejects unknown element names."""
    result = validate_html5_element("sparkle-box")

    assert result == {
        "element": "sparkle-box",
        "is_html5": False,
    }


def test_get_html_element_name_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify the HTML element tool calls the configured MCP sidecar."""
    called_urls = []

    def fake_call_mcp_html_element_tool(sidecar_url: str) -> str:
        called_urls.append(sidecar_url)
        return "<div>"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr(
        "sandbox_agent.tools._call_mcp_html_element_tool",
        fake_call_mcp_html_element_tool,
    )

    element_name = get_html_element_name()

    assert element_name == "<div>"
    assert called_urls == ["http://mcp-sidecar:8000/mcp"]


def test_get_html_element_name_requires_mcp_sidecar_url(monkeypatch) -> None:
    """Verify the HTML element tool requires MCP sidecar connection info."""
    monkeypatch.delenv("MCP_SIDECAR_URL", raising=False)

    with pytest.raises(RuntimeError, match="MCP_SIDECAR_URL"):
        get_html_element_name()


def test_get_active_items_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify active item lookups call the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, object]) -> str:
        calls.append((tool_name, arguments))
        return '[{"id": 2, "status": "active"}]'

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert get_active_items() == '[{"id": 2, "status": "active"}]'
    assert calls == [("get_active_items", {})]


def test_microsoft_docs_search_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft docs search calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "search result"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_docs_search("MCP tool calling") == "search result"
    assert calls == [("microsoft_docs_search", {"query": "MCP tool calling"})]


def test_microsoft_docs_fetch_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft docs fetch calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "markdown"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_docs_fetch("https://learn.microsoft.com/test") == "markdown"
    assert calls == [
        ("microsoft_docs_fetch", {"url": "https://learn.microsoft.com/test"})
    ]


def test_microsoft_code_sample_search_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft code sample search calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "code"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_code_sample_search("agent framework", "python") == "code"
    assert calls == [
        (
            "microsoft_code_sample_search",
            {"query": "agent framework", "language": "python"},
        )
    ]


def test_jina_read_url_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Jina Reader calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "markdown"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert jina_read_url("https://www.nibblon.com/movies/10") == "markdown"
    assert calls == [("jina_read_url", {"url": "https://www.nibblon.com/movies/10"})]


def test_run_python_script_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Python execution calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, object]) -> str:
        calls.append((tool_name, arguments))
        return '{"exit_code": 0, "stdout": "42\\n"}'

    script = "def main(argv):\n    print(42)\n    return 0\n"
    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    result = run_python_script(script, args=["x"], timeout_seconds=5)

    assert result == '{"exit_code": 0, "stdout": "42\\n"}'
    assert calls == [
        (
            "run_python_script",
            {
                "script": script,
                "args": ["x"],
                "timeout_seconds": 5,
            },
        )
    ]


def test_get_answer_format_reads_mcp_sidecar_resource(monkeypatch) -> None:
    """Verify answer format reads the configured MCP sidecar resource."""
    calls = []

    def fake_call(sidecar_url: str, resource_uri: str) -> str:
        calls.append((sidecar_url, resource_uri))
        return "## Recommended Approach"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_resource", fake_call)

    assert get_answer_format() == "## Recommended Approach"
    assert calls == [
        (
            "http://mcp-sidecar:8000/mcp",
            "mcp-sidecar://instructions/answer-format.md",
        )
    ]


def test_save_answer_writes_answer_file(tmp_path, monkeypatch) -> None:
    """Verify answer text is saved to the sandbox output directory."""
    answer_path = tmp_path / "answer.txt"
    monkeypatch.setattr("sandbox_agent.tools._ANSWER_FILE_PATH", answer_path)

    result = save_answer("Answer text")

    assert result == {
        "success": True,
        "message": "Created answer.txt",
    }
    assert answer_path.read_text(encoding="utf-8") == "Answer text"


def test_save_html_document_writes_site_file(tmp_path, monkeypatch) -> None:
    """Verify HTML documents are saved under the static site directory."""
    site_directory = tmp_path / "site"
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)

    result = save_html_document("index.html", "<h1>Hello</h1>")

    assert result == {
        "success": True,
        "message": "Created index.html",
    }
    assert (site_directory / "index.html").read_text(encoding="utf-8") == (
        "<h1>Hello</h1>"
    )


def test_capture_site_screenshot_serves_site_and_writes_output_png(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify screenshots are captured through a localhost static site server."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    (site_directory / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    captured_urls = []

    def fake_capture(url: str, screenshot_path) -> None:
        captured_urls.append(url)
        screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr("sandbox_agent.tools._OUTPUT_DIRECTORY", tmp_path)
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr("sandbox_agent.tools._capture_site_screenshot", fake_capture)

    result = capture_site_screenshot()

    assert result == {
        "success": True,
        "message": "Created site-screenshot.png",
    }
    assert (tmp_path / "site-screenshot.png").read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert len(captured_urls) == 1
    assert captured_urls[0].startswith("http://127.0.0.1:")
    assert captured_urls[0].endswith("/index.html")


def test_capture_site_screenshot_rejects_nested_output_path(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify screenshot output stays in the run directory."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    (site_directory / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._OUTPUT_DIRECTORY", tmp_path)
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)

    result = capture_site_screenshot(screenshot_file_name="site/nested.png")

    assert result == {
        "success": False,
        "message": "Failed to capture screenshot for `index.html",
    }


def test_capture_site_screenshot_reports_missing_html(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify screenshot capture requires an existing site entry point."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    monkeypatch.setattr("sandbox_agent.tools._OUTPUT_DIRECTORY", tmp_path)
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)

    result = capture_site_screenshot()

    assert result == {
        "success": False,
        "message": "Failed to screenshot missing HTML file `index.html",
    }


def test_inject_squid_proxy_section_inserts_heading_before_body_close(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the Squid section is inserted into generated HTML."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body><h1>Items</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_example_heading_text",
        lambda: "Example Domain",
    )

    result = inject_squid_proxy_section()

    assert result == {
        "success": True,
        "message": "Updated index.html",
    }
    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Squid Proxy</h2>" in html
    assert "<p>Example Domain</p>" in html
    assert html.index("<h2>Squid Proxy</h2>") < html.index("</body>")


def test_inject_squid_proxy_section_escapes_example_heading(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify fetched content is escaped before being inserted into HTML."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_example_heading_text",
        lambda: "<script>alert(1)</script>",
    )

    inject_squid_proxy_section()

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_path.read_text(
        encoding="utf-8"
    )


def test_inject_squid_proxy_section_appends_when_body_close_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify malformed generated HTML still receives the Squid section."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<h1>Items</h1>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_example_heading_text",
        lambda: "Example Domain",
    )

    inject_squid_proxy_section()

    assert html_path.read_text(encoding="utf-8").endswith("</div>\n")


def test_inject_code_sidecar_section_inserts_result_before_body_close(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the code sidecar section is inserted into generated HTML."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body><h1>Items</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._run_code_sidecar_multiply_demo",
        lambda: "3 x 7 = 21",
    )

    result = inject_code_sidecar_section()

    assert result == {
        "success": True,
        "message": "Updated index.html",
    }
    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Code sidecar</h2>" in html
    assert "<p>3 x 7 = 21</p>" in html
    assert html.index("<h2>Code sidecar</h2>") < html.index("</body>")


def test_inject_code_sidecar_section_escapes_result_text(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify code sidecar output is escaped before insertion."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._run_code_sidecar_multiply_demo",
        lambda: "<bad>",
    )

    inject_code_sidecar_section()

    assert "<p>&lt;bad&gt;</p>" in html_path.read_text(encoding="utf-8")


def test_inject_code_sidecar_section_uses_multiply_demo_result(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the code sidecar demo calls run_python_script with random inputs."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")
    calls = []

    def fake_randint(left: int, right: int) -> int:
        calls.append(("randint", left, right))
        return 4 if len(calls) == 1 else 8

    def fake_run_python_script(
        script: str, args: list[str], timeout_seconds: int
    ) -> str:
        calls.append(("run", script, args, timeout_seconds))
        return json.dumps({"exit_code": 0, "stdout": "4 x 8 = 32\n", "stderr": ""})

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr("sandbox_agent.tools.random.randint", fake_randint)
    monkeypatch.setattr("sandbox_agent.tools.run_python_script", fake_run_python_script)

    inject_code_sidecar_section()

    html = html_path.read_text(encoding="utf-8")
    assert "<p>4 x 8 = 32</p>" in html
    assert calls[0] == ("randint", 1, 9)
    assert calls[1] == ("randint", 1, 9)
    assert calls[2][2] == ["4", "8"]
    assert calls[2][3] == 5
    assert "def multiply(left, right):" in calls[2][1]


def test_inject_code_sidecar_section_uses_exception_message(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify code sidecar invocation failures are inserted into the page."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")

    def fake_run_python_script(
        script: str,
        args: list[str],
        timeout_seconds: int,
    ) -> str:
        _ = script
        _ = args
        _ = timeout_seconds
        raise RuntimeError("code sidecar unavailable")

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr("sandbox_agent.tools.random.randint", lambda left, right: 2)
    monkeypatch.setattr("sandbox_agent.tools.run_python_script", fake_run_python_script)

    inject_code_sidecar_section()

    assert "<p>code sidecar unavailable</p>" in html_path.read_text(encoding="utf-8")


def test_inject_jina_reader_section_inserts_result_before_body_close(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the Jina Reader section is inserted into generated HTML."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body><h1>Items</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_jina_reader_example_text",
        lambda: "Title\nLine 2",
    )

    result = inject_jina_reader_section()

    assert result == {
        "success": True,
        "message": "Updated index.html",
    }
    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Jina Reader</h2>" in html
    assert "<p>Title<br/>Line 2</p>" in html
    assert html.index("<h2>Jina Reader</h2>") < html.index("</body>")


def test_inject_jina_reader_section_escapes_result_text(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Jina Reader output is escaped while preserving line breaks."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_jina_reader_example_text",
        lambda: "<b>Title</b>\r\nNext",
    )

    inject_jina_reader_section()

    html = html_path.read_text(encoding="utf-8")
    assert "<p>&lt;b&gt;Title&lt;/b&gt;<br/>Next</p>" in html


def test_inject_jina_reader_section_uses_exception_message(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Jina Reader invocation failures are inserted into the page."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")

    def fake_jina_read_url(url: str) -> str:
        assert url == "https://www.example.com"
        raise RuntimeError("jina reader unavailable")

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr("sandbox_agent.tools.jina_read_url", fake_jina_read_url)

    inject_jina_reader_section()

    assert "<p>jina reader unavailable</p>" in html_path.read_text(encoding="utf-8")


def test_inject_ollama_sidecar_section_inserts_result_before_body_close(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the Ollama section is inserted into generated HTML."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body><h1>Items</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_ollama_child_friendly_joke",
        lambda: "Why did the cookie go to school?\nTo become a smart cookie!",
    )

    result = inject_ollama_sidecar_section()

    assert result == {
        "success": True,
        "message": "Updated index.html",
    }
    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Ollama sidecar</h2>" in html
    assert (
        "<p>Why did the cookie go to school?<br/>To become a smart cookie!</p>" in html
    )
    assert html.index("<h2>Ollama sidecar</h2>") < html.index("</body>")


def test_inject_ollama_sidecar_section_escapes_result_text(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Ollama output is escaped while preserving line breaks."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._read_ollama_child_friendly_joke",
        lambda: "<script>nope</script>\r\nA joke",
    )

    inject_ollama_sidecar_section()

    html = html_path.read_text(encoding="utf-8")
    assert "<p>&lt;script&gt;nope&lt;/script&gt;<br/>A joke</p>" in html


def test_inject_ollama_sidecar_section_uses_exception_message(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Ollama invocation failures are inserted into the page."""
    site_directory = tmp_path / "site"
    site_directory.mkdir()
    html_path = site_directory / "index.html"
    html_path.write_text("<html><body></body></html>", encoding="utf-8")

    def fake_request_ollama_child_friendly_joke() -> str:
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_directory)
    monkeypatch.setattr(
        "sandbox_agent.tools._request_ollama_child_friendly_joke",
        fake_request_ollama_child_friendly_joke,
    )

    inject_ollama_sidecar_section()

    assert "<p>ollama unavailable</p>" in html_path.read_text(encoding="utf-8")


def test_ollama_joke_request_uses_configured_sidecar(monkeypatch) -> None:
    """Verify Ollama requests use the TOML-derived environment settings."""
    calls = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            _ = exc_type
            _ = exc_value
            _ = traceback

        def read(self) -> bytes:
            return (
                b'{"message": {"content": "Thinking first.\\n'
                b'FINAL_JOKE: A small joke for everyone."}}'
            )

    def fake_urlopen(request, timeout: int) -> _FakeResponse:
        calls.append((request, timeout))
        return _FakeResponse()

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama-sidecar:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.setattr("sandbox_agent.tools.urlopen", fake_urlopen)

    result = inject_ollama_sidecar_section.__globals__[
        "_request_ollama_child_friendly_joke"
    ]()

    request, timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert result == "A small joke for everyone."
    assert request.full_url == "http://ollama-sidecar:11434/api/chat"
    assert payload == {
        "model": "qwen3:4b",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Tell one short, child-friendly joke. End with one line that "
                    "starts with FINAL_JOKE: followed by the actual joke. Do not "
                    "use placeholders, angle brackets, or labels after that line."
                ),
            },
        ],
        "stream": False,
        "think": False,
        "options": {
            "num_predict": 240,
        },
    }
    assert timeout == 300


def test_ollama_empty_response_returns_clear_message() -> None:
    """Verify empty Ollama responses do not insert raw metadata."""
    result = inject_ollama_sidecar_section.__globals__["_read_ollama_response_text"](
        '{"response": "", "thinking": "still thinking"}'
    )

    assert result == "Ollama returned no response text."


def test_ollama_final_joke_marker_is_extracted() -> None:
    """Verify marked Ollama final answers are extracted from surrounding text."""
    result = inject_ollama_sidecar_section.__globals__["_read_ollama_response_text"](
        json.dumps(
            {
                "message": {
                    "content": (
                        "I will think first.\n"
                        "FINAL_JOKE: Why did the banana go to school? "
                        "To learn split-second math!\n"
                        "extra text"
                    )
                }
            }
        )
    )

    assert result == "Why did the banana go to school? To learn split-second math!"


def test_ollama_final_joke_marker_ignores_instruction_mentions() -> None:
    """Verify marker extraction only accepts a line that starts with the marker."""
    response_text = (
        "The instruction says to use FINAL_JOKE: <joke>.\n"
        "FINAL_JOKE: Why did the pencil smile? It felt sharp!"
    )

    result = inject_ollama_sidecar_section.__globals__["_extract_ollama_final_joke"](
        response_text
    )

    assert result == "Why did the pencil smile? It felt sharp!"


def test_ollama_final_joke_placeholder_returns_clear_message() -> None:
    """Verify placeholder Ollama answers are not treated as jokes."""
    result = inject_ollama_sidecar_section.__globals__["_extract_ollama_final_joke"](
        "FINAL_JOKE: <joke>"
    )

    assert result == "Ollama returned a placeholder instead of a joke."
