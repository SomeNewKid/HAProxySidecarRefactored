"""Shared sandbox capability names and capability family helpers."""

from __future__ import annotations

from typing import Protocol

NETWORK = "network"
MCP_CLIENT = "mcp_client"
JINA_READER = "jina_reader"
CODE_EXECUTION = "code_execution"
HAPROXY = "haproxy"
OLLAMA = "ollama"
OPENAI = "openai"
OPENAI_AGENTS = "openai_agents"
ANTHROPIC_CLAUDE = "anthropic_claude"
ANTHROPIC_PYTHON = "anthropic_python"
BEEAI = "ibm_beeai"
GOOGLE_ADK = "google_adk"
LANGCHAIN = "langchain"
LANGGRAPH = "langgraph"
MICROSOFT_AGENT = "microsoft_agent"
CREWAI = "crewai"
OTTO_AGENT = "otto_agent"
PLAYWRIGHT_CHROMIUM = "playwright_chromium"
SHELL_ACCESS = "shell_access"

OPENAI_FAMILY = (
    OPENAI,
    OPENAI_AGENTS,
    BEEAI,
    GOOGLE_ADK,
    LANGCHAIN,
    LANGGRAPH,
    MICROSOFT_AGENT,
    CREWAI,
    OTTO_AGENT,
)
ANTHROPIC_FAMILY = (
    ANTHROPIC_CLAUDE,
    ANTHROPIC_PYTHON,
)
NETWORK_REQUIRED = (
    MCP_CLIENT,
    JINA_READER,
    HAPROXY,
    OLLAMA,
    *OPENAI_FAMILY,
    *ANTHROPIC_FAMILY,
)
AGENT_IMAGE_EXCLUDED = (
    HAPROXY,
    OLLAMA,
)
SUPPORTED = (
    NETWORK,
    MCP_CLIENT,
    JINA_READER,
    CODE_EXECUTION,
    HAPROXY,
    OLLAMA,
    OPENAI,
    OPENAI_AGENTS,
    ANTHROPIC_CLAUDE,
    ANTHROPIC_PYTHON,
    BEEAI,
    GOOGLE_ADK,
    LANGCHAIN,
    LANGGRAPH,
    MICROSOFT_AGENT,
    CREWAI,
    OTTO_AGENT,
    PLAYWRIGHT_CHROMIUM,
    SHELL_ACCESS,
)


class CapabilitySpec(Protocol):
    """Capability membership query used by spec-derived objects."""

    def has_capability(self, capability: str) -> bool:
        """Return whether a capability is declared."""
        ...


def has_openai_family_capability(spec: CapabilitySpec) -> bool:
    """Return whether a spec includes an OpenAI-family capability."""
    return any(spec.has_capability(capability) for capability in OPENAI_FAMILY)


def has_anthropic_family_capability(spec: CapabilitySpec) -> bool:
    """Return whether a spec includes an Anthropic-family capability."""
    return any(spec.has_capability(capability) for capability in ANTHROPIC_FAMILY)
