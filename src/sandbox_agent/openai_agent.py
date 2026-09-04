"""AI agent that builds a simple HTML document through declared tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_OUTPUT_DIRECTORY = Path("/sandbox-output")
_SITE_DIRECTORY = _OUTPUT_DIRECTORY / "site"
_DEFAULT_MODEL = "gpt-4.1-mini"
_AGENT_PROMPT = """
Create a single basic-style HTML document named index.html that lists the active
items returned by the get_active_items tool.

Use the get_active_items tool first. Treat its response as a JSON array of item
records. Build a friendly, self-contained page that summarizes the active items
and shows their id, item_key, title, status, notes, quantity, created_at, and
updated_at values. Use embedded CSS in a <style> block so the page is readable
and pleasant, but keep the design simple.

Save the document with the save_html_document tool. After saving index.html,
return a short status message that says which file was created and how many
active items it lists.
"""


def create_openai_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Sandbox Agent HTML document generator."""
    from agents import Agent

    from .openai_tools import (
        get_active_items_tool,
        save_html_document_tool,
    )

    return Agent(
        name="Active Items Document Generator",
        model=model,
        instructions=(
            "You are a careful web page builder. Use the provided tools to "
            "retrieve the active item records, save exactly one HTML file, "
            "and return the final status message. Do not finish until both "
            "tool calls have succeeded."
        ),
        tools=[
            get_active_items_tool,
            save_html_document_tool,
        ],
    )


def run_html_element_agent(model: str = _DEFAULT_MODEL) -> str:
    """Run the HTML element agent and save its final response."""
    from agents import Runner

    from .tools import (
        capture_site_screenshot,
        inject_code_sidecar_section,
        inject_jina_reader_section,
        inject_ollama_sidecar_section,
        inject_squid_proxy_section,
        save_answer,
    )

    _SITE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result = Runner.run_sync(
        create_openai_agent(model),
        _AGENT_PROMPT,
        max_turns=10,
    )
    inject_result = inject_squid_proxy_section()
    code_inject_result = inject_code_sidecar_section()
    jina_inject_result = inject_jina_reader_section()
    ollama_inject_result = inject_ollama_sidecar_section()
    screenshot_result = capture_site_screenshot()
    final_output = _build_final_output(
        str(result.final_output),
        inject_result,
        code_inject_result,
        jina_inject_result,
        ollama_inject_result,
        screenshot_result,
    )
    save_answer(final_output)
    return final_output


def _build_final_output(
    agent_output: str,
    inject_result: dict[str, bool | str],
    code_inject_result: dict[str, bool | str],
    jina_inject_result: dict[str, bool | str],
    ollama_inject_result: dict[str, bool | str],
    screenshot_result: dict[str, bool | str],
) -> str:
    return (
        f"{agent_output} "
        f"Squid Proxy section: {inject_result['message']}. "
        f"Code sidecar section: {code_inject_result['message']}. "
        f"Jina Reader section: {jina_inject_result['message']}. "
        f"Ollama sidecar section: {ollama_inject_result['message']}. "
        f"Screenshot: {screenshot_result['message']}."
    )
