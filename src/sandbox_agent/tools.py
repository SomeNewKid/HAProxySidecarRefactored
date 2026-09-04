"""Tools used by the Sandbox Agent."""

from __future__ import annotations

import json
import os
import random
from collections.abc import Mapping
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

_OUTPUT_DIRECTORY = Path("/sandbox-output")
_SITE_DIRECTORY = _OUTPUT_DIRECTORY / "site"
_ANSWER_FILE_PATH = _OUTPUT_DIRECTORY / "answer.txt"
_DEFAULT_SCREENSHOT_FILE_NAME = "site-screenshot.png"
_EXAMPLE_URL = "https://www.example.com"
_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENVIRONMENT_VARIABLE = "OLLAMA_MODEL"
_OLLAMA_JOKE_PROMPT = (
    "Tell one short, child-friendly joke. End with one line that starts with "
    "FINAL_JOKE: followed by the actual joke. Do not use placeholders, angle "
    "brackets, or labels after that line."
)
_OLLAMA_REQUEST_TIMEOUT_SECONDS = 300
_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_URL"
_MCP_ACTIVE_ITEMS_TOOL_NAME = "get_active_items"
_MCP_HTML_ELEMENT_TOOL_NAME = "get_html_element_name"
_MCP_MICROSOFT_DOCS_SEARCH_TOOL_NAME = "microsoft_docs_search"
_MCP_MICROSOFT_DOCS_FETCH_TOOL_NAME = "microsoft_docs_fetch"
_MCP_MICROSOFT_CODE_SAMPLE_SEARCH_TOOL_NAME = "microsoft_code_sample_search"
_MCP_JINA_READ_URL_TOOL_NAME = "jina_read_url"
_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME = "run_python_script"
_MCP_ANSWER_FORMAT_RESOURCE_URI = "mcp-sidecar://instructions/answer-format.md"
_HTML5_ELEMENTS = frozenset(
    {
        "a",
        "abbr",
        "address",
        "area",
        "article",
        "aside",
        "audio",
        "b",
        "base",
        "bdi",
        "bdo",
        "blockquote",
        "body",
        "br",
        "button",
        "canvas",
        "caption",
        "cite",
        "code",
        "col",
        "colgroup",
        "data",
        "datalist",
        "dd",
        "del",
        "details",
        "dfn",
        "dialog",
        "div",
        "dl",
        "dt",
        "em",
        "embed",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hgroup",
        "hr",
        "html",
        "i",
        "iframe",
        "img",
        "input",
        "ins",
        "kbd",
        "label",
        "legend",
        "li",
        "link",
        "main",
        "map",
        "mark",
        "menu",
        "meta",
        "meter",
        "nav",
        "noscript",
        "object",
        "ol",
        "optgroup",
        "option",
        "output",
        "p",
        "picture",
        "pre",
        "progress",
        "q",
        "rp",
        "rt",
        "ruby",
        "s",
        "samp",
        "script",
        "search",
        "section",
        "select",
        "slot",
        "small",
        "source",
        "span",
        "strong",
        "style",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "template",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "time",
        "title",
        "tr",
        "track",
        "u",
        "ul",
        "var",
        "video",
        "wbr",
    }
)


def get_html_element_name() -> str:
    """Return the HTML element name provided by the MCP sidecar."""
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_html_element_tool(sidecar_url)


def get_active_items() -> str:
    """Return active item records provided by the MCP sidecar."""
    return _call_mcp_sidecar_tool(_MCP_ACTIVE_ITEMS_TOOL_NAME, {})


def microsoft_docs_search(query: str) -> str:
    """Search Microsoft Learn documentation through the MCP sidecar."""
    return _call_mcp_sidecar_tool(
        _MCP_MICROSOFT_DOCS_SEARCH_TOOL_NAME,
        {"query": query},
    )


def microsoft_docs_fetch(url: str) -> str:
    """Fetch a Microsoft Learn documentation page through the MCP sidecar."""
    return _call_mcp_sidecar_tool(_MCP_MICROSOFT_DOCS_FETCH_TOOL_NAME, {"url": url})


def microsoft_code_sample_search(query: str, language: str | None = None) -> str:
    """Search Microsoft Learn code samples through the MCP sidecar."""
    arguments = {"query": query}
    if language:
        arguments["language"] = language

    return _call_mcp_sidecar_tool(
        _MCP_MICROSOFT_CODE_SAMPLE_SEARCH_TOOL_NAME,
        arguments,
    )


def jina_read_url(url: str) -> str:
    """Read a fully-qualified URL through the Jina Reader sidecar."""
    return _call_mcp_sidecar_tool(_MCP_JINA_READ_URL_TOOL_NAME, {"url": url})


def run_python_script(
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Run a small Python script through the MCP code-execution sidecar tool."""
    arguments: dict[str, object] = {"script": script}
    if args is not None:
        arguments["args"] = args
    if timeout_seconds is not None:
        arguments["timeout_seconds"] = timeout_seconds

    return _call_mcp_sidecar_tool(_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME, arguments)


def get_answer_format() -> str:
    """Read the required answer format resource from the MCP sidecar."""
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_resource(sidecar_url, _MCP_ANSWER_FORMAT_RESOURCE_URI)


def validate_html5_element(element_name: str) -> dict[str, bool | str]:
    """Return whether a user-supplied name is a known HTML5 element."""
    normalized_name = _normalize_html_element_name(element_name)
    return {
        "element": normalized_name,
        "is_html5": normalized_name in _HTML5_ELEMENTS,
    }


def save_html_document(file_name: str, file_contents: str) -> dict[str, bool | str]:
    """Save an HTML document into the sandbox web root."""
    try:
        file_path = _resolve_site_path(file_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_contents, encoding="utf-8")
    except OSError:
        return _failure("create", file_name)

    if not file_path.exists():
        return _failure("create", file_name)

    return {
        "success": True,
        "message": f"Created {file_name}",
    }


def capture_site_screenshot(
    html_file_name: str = "index.html",
    screenshot_file_name: str = _DEFAULT_SCREENSHOT_FILE_NAME,
) -> dict[str, bool | str]:
    """Capture a PNG screenshot of the generated static site."""
    try:
        html_path = _resolve_site_path(html_file_name)
        screenshot_path = _resolve_output_file_path(screenshot_file_name)
        if not html_path.exists():
            return _failure("screenshot missing HTML file", html_file_name)

        screenshot_path.unlink(missing_ok=True)
        server, thread = _start_static_site_server(_SITE_DIRECTORY)
        try:
            url = _build_static_site_url(server, html_path)
            _capture_site_screenshot(url, screenshot_path)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    except OSError:
        return _failure("capture screenshot for", html_file_name)
    except Exception as error:
        return {
            "success": False,
            "message": f"Failed to capture screenshot: {type(error).__name__}",
        }

    if not screenshot_path.exists():
        return _failure("capture screenshot for", html_file_name)

    return {
        "success": True,
        "message": f"Created {screenshot_path.name}",
    }


def inject_squid_proxy_section(
    html_file_name: str = "index.html",
) -> dict[str, bool | str]:
    """Insert a Squid Proxy demonstration section into a generated HTML document."""
    try:
        html_path = _resolve_site_path(html_file_name)
        html = html_path.read_text(encoding="utf-8")
        heading_text = _read_example_heading_text()
        updated_html = _insert_before_closing_body(
            html,
            _build_squid_proxy_section(heading_text),
        )
        html_path.write_text(updated_html, encoding="utf-8")
    except OSError:
        return _failure("update", html_file_name)

    return {
        "success": True,
        "message": f"Updated {html_file_name}",
    }


def inject_code_sidecar_section(
    html_file_name: str = "index.html",
) -> dict[str, bool | str]:
    """Insert a code sidecar demonstration section into generated HTML."""
    try:
        html_path = _resolve_site_path(html_file_name)
        html = html_path.read_text(encoding="utf-8")
        result_text = _run_code_sidecar_multiply_demo()
        updated_html = _insert_before_closing_body(
            html,
            _build_code_sidecar_section(result_text),
        )
        html_path.write_text(updated_html, encoding="utf-8")
    except OSError:
        return _failure("update", html_file_name)

    return {
        "success": True,
        "message": f"Updated {html_file_name}",
    }


def inject_jina_reader_section(
    html_file_name: str = "index.html",
) -> dict[str, bool | str]:
    """Insert a Jina Reader demonstration section into generated HTML."""
    try:
        html_path = _resolve_site_path(html_file_name)
        html = html_path.read_text(encoding="utf-8")
        result_text = _read_jina_reader_example_text()
        updated_html = _insert_before_closing_body(
            html,
            _build_jina_reader_section(result_text),
        )
        html_path.write_text(updated_html, encoding="utf-8")
    except OSError:
        return _failure("update", html_file_name)

    return {
        "success": True,
        "message": f"Updated {html_file_name}",
    }


def inject_ollama_sidecar_section(
    html_file_name: str = "index.html",
) -> dict[str, bool | str]:
    """Insert an Ollama sidecar demonstration section into generated HTML."""
    try:
        html_path = _resolve_site_path(html_file_name)
        html = html_path.read_text(encoding="utf-8")
        result_text = _read_ollama_child_friendly_joke()
        updated_html = _insert_before_closing_body(
            html,
            _build_ollama_sidecar_section(result_text),
        )
        html_path.write_text(updated_html, encoding="utf-8")
    except OSError:
        return _failure("update", html_file_name)

    return {
        "success": True,
        "message": f"Updated {html_file_name}",
    }


def save_answer(answer: str) -> dict[str, bool | str]:
    """Save the generated answer into the sandbox output directory."""
    try:
        _ANSWER_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ANSWER_FILE_PATH.write_text(answer, encoding="utf-8")
    except OSError:
        return _failure("save", _ANSWER_FILE_PATH.name)

    if not _ANSWER_FILE_PATH.exists():
        return _failure("save", _ANSWER_FILE_PATH.name)

    return {
        "success": True,
        "message": f"Created {_ANSWER_FILE_PATH.name}",
    }


def _resolve_site_path(file_name: str) -> Path:
    return _resolve_child_path(_SITE_DIRECTORY, file_name)


def _resolve_output_file_path(file_name: str) -> Path:
    file_path = _resolve_child_path(_OUTPUT_DIRECTORY, file_name)
    output_directory = _OUTPUT_DIRECTORY.resolve(strict=False)
    if file_path.parent != output_directory:
        raise OSError(f"Refusing to write outside {output_directory}: {file_name}")

    return file_path


def _start_static_site_server(
    site_directory: Path,
) -> tuple[ThreadingHTTPServer, Thread]:
    handler = partial(_StaticSiteRequestHandler, directory=str(site_directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _build_static_site_url(server: ThreadingHTTPServer, html_path: Path) -> str:
    relative_path = html_path.relative_to(_SITE_DIRECTORY.resolve(strict=False))
    quoted_path = quote(relative_path.as_posix())
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}/{quoted_path}"


def _capture_site_screenshot(url: str, screenshot_path: Path) -> None:
    sync_playwright = import_module("playwright.sync_api").sync_playwright
    temporary_path = screenshot_path.with_suffix(f"{screenshot_path.suffix}.tmp")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(url, wait_until="load", timeout=30000)
                page.screenshot(path=str(temporary_path), type="png")
            finally:
                browser.close()

        temporary_path.replace(screenshot_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_example_heading_text() -> str:
    try:
        with urlopen(_EXAMPLE_URL, timeout=30) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except Exception as error:
        return str(error)

    return _extract_h1_text(response_text)


def _extract_h1_text(response_text: str) -> str:
    lower_response = response_text.lower()
    start_tag = "<h1>"
    end_tag = "</h1>"
    start_index = lower_response.find(start_tag)
    if start_index < 0:
        return "No heading found."

    content_start_index = start_index + len(start_tag)
    end_index = lower_response.find(end_tag, content_start_index)
    if end_index < 0:
        return "No heading found."

    heading_text = response_text[content_start_index:end_index].strip()
    if not heading_text:
        return "No heading found."

    return heading_text


def _build_squid_proxy_section(paragraph_text: str) -> str:
    return (
        f"\n<div>\n  <h2>Squid Proxy</h2>\n  <p>{escape(paragraph_text)}</p>\n</div>\n"
    )


def _run_code_sidecar_multiply_demo() -> str:
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    try:
        response_text = run_python_script(
            _build_multiply_script(),
            args=[str(left), str(right)],
            timeout_seconds=5,
        )
    except Exception as error:
        return str(error)

    return _read_code_sidecar_result_text(response_text)


def _build_multiply_script() -> str:
    return "\n".join(
        [
            "def multiply(left, right):",
            "    return left * right",
            "",
            "def main(argv):",
            "    left = int(argv[0])",
            "    right = int(argv[1])",
            "    product = multiply(left, right)",
            "    print(f'{left} x {right} = {product}')",
            "    return 0",
            "",
        ]
    )


def _read_code_sidecar_result_text(response_text: str) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text

    if not isinstance(data, dict):
        return response_text

    stdout = data.get("stdout")
    if data.get("exit_code") == 0 and isinstance(stdout, str) and stdout.strip():
        return stdout.strip()

    stderr = data.get("stderr")
    if isinstance(stderr, str) and stderr.strip():
        return stderr.strip()

    return response_text


def _build_code_sidecar_section(paragraph_text: str) -> str:
    return (
        f"\n<div>\n  <h2>Code sidecar</h2>\n  <p>{escape(paragraph_text)}</p>\n</div>\n"
    )


def _read_jina_reader_example_text() -> str:
    try:
        return jina_read_url(_EXAMPLE_URL)
    except Exception as error:
        return str(error)


def _build_jina_reader_section(paragraph_text: str) -> str:
    paragraph_html = _escape_text_with_line_breaks(paragraph_text)
    return f"\n<div>\n  <h2>Jina Reader</h2>\n  <p>{paragraph_html}</p>\n</div>\n"


def _read_ollama_child_friendly_joke() -> str:
    try:
        return _request_ollama_child_friendly_joke()
    except Exception as error:
        return str(error)


def _request_ollama_child_friendly_joke() -> str:
    base_url = _get_ollama_base_url()
    model = _get_ollama_model()
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": _OLLAMA_JOKE_PROMPT,
                },
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_predict": 240,
            },
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=_OLLAMA_REQUEST_TIMEOUT_SECONDS) as response:
        response_text = response.read().decode("utf-8", errors="replace")

    return _read_ollama_response_text(response_text)


def _get_ollama_base_url() -> str:
    base_url = os.environ.get(_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE)
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL is not configured.")

    return base_url


def _get_ollama_model() -> str:
    model = os.environ.get(_OLLAMA_MODEL_ENVIRONMENT_VARIABLE)
    if not model:
        raise RuntimeError("OLLAMA_MODEL is not configured.")

    return model


def _read_ollama_response_text(response_text: str) -> str:
    data = json.loads(response_text)
    if not isinstance(data, dict):
        return response_text

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return _extract_ollama_final_joke(content)

    generated_text = data.get("response")
    if isinstance(generated_text, str) and generated_text.strip():
        return _extract_ollama_final_joke(generated_text)

    error_text = data.get("error")
    if isinstance(error_text, str) and error_text.strip():
        return error_text.strip()

    return "Ollama returned no response text."


def _extract_ollama_final_joke(text: str) -> str:
    marker = "FINAL_JOKE:"
    for line in reversed(text.splitlines()):
        stripped_line = line.strip()
        if stripped_line.startswith(marker):
            joke = stripped_line.removeprefix(marker).strip()
            if joke.lower() in {"<joke>", "[joke]", "joke"}:
                return "Ollama returned a placeholder instead of a joke."
            return joke or text.strip()

    return text.strip()


def _build_ollama_sidecar_section(paragraph_text: str) -> str:
    paragraph_html = _escape_text_with_line_breaks(paragraph_text)
    return f"\n<div>\n  <h2>Ollama sidecar</h2>\n  <p>{paragraph_html}</p>\n</div>\n"


def _escape_text_with_line_breaks(text: str) -> str:
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    return escape(normalized_text).replace("\n", "<br/>")


def _insert_before_closing_body(html: str, insertion: str) -> str:
    closing_body_index = html.lower().rfind("</body>")
    if closing_body_index < 0:
        return f"{html}{insertion}"

    return f"{html[:closing_body_index]}{insertion}{html[closing_body_index:]}"


class _StaticSiteRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        _ = format
        _ = args


def _call_mcp_html_element_tool(sidecar_url: str) -> str:
    return _call_mcp_tool(sidecar_url, _MCP_HTML_ELEMENT_TOOL_NAME, {})


def _call_mcp_sidecar_tool(tool_name: str, arguments: Mapping[str, object]) -> str:
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_tool(sidecar_url, tool_name, arguments)


def _call_mcp_resource(sidecar_url: str, resource_uri: str) -> str:
    import anyio

    return anyio.run(_call_mcp_resource_async, sidecar_url, resource_uri)


def _get_mcp_sidecar_url() -> str:
    sidecar_url = os.environ.get(_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE)
    if not sidecar_url:
        raise RuntimeError("MCP_SIDECAR_URL is not configured.")

    return sidecar_url


def _call_mcp_tool(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    import anyio

    return anyio.run(_call_mcp_tool_async, sidecar_url, tool_name, arguments)


async def _call_mcp_tool_async(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(sidecar_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, dict(arguments))

    return _read_mcp_tool_text_result(result)


async def _call_mcp_resource_async(sidecar_url: str, resource_uri: str) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from pydantic import AnyUrl

    async with streamablehttp_client(sidecar_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.read_resource(AnyUrl(resource_uri))

    return _read_mcp_resource_text_result(result)


def _read_mcp_tool_text_result(result: Any) -> str:
    structured_content = getattr(result, "structuredContent", None)
    if isinstance(structured_content, dict):
        value = structured_content.get("result")
        if isinstance(value, str):
            return value
        if value is not None:
            return json.dumps(value, indent=2)
        return json.dumps(structured_content, indent=2)

    content_blocks = getattr(result, "content", ())
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text

    raise RuntimeError("MCP tool did not return a text result.")


def _read_mcp_resource_text_result(result: Any) -> str:
    contents = getattr(result, "contents", ())
    text_parts = [
        text
        for content in contents
        if isinstance((text := getattr(content, "text", None)), str)
    ]
    if text_parts:
        return "\n\n".join(text_parts)

    raise RuntimeError("MCP resource did not return text content.")


def _normalize_html_element_name(element_name: str) -> str:
    name = element_name.strip().lower()
    name = name.removeprefix("<")
    name = name.removeprefix("/")
    name = name.removesuffix(">")
    name = name.removesuffix("/")
    return name.strip()


def _resolve_child_path(parent: Path, child_name: str) -> Path:
    child_path = parent / child_name
    resolved_parent = parent.resolve(strict=False)
    resolved_child = child_path.resolve(strict=False)
    if not _is_relative_to(resolved_child, resolved_parent):
        raise OSError(f"Refusing to write outside {resolved_parent}: {child_name}")

    return resolved_child


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True


def _failure(action: str, file_name: str) -> dict[str, bool | str]:
    return {
        "success": False,
        "message": f"Failed to {action} `{file_name}",
    }
