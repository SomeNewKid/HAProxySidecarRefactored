"""Sandbox spec validation rules."""

from __future__ import annotations

import ipaddress

from . import capabilities as sandbox_capabilities

_RUN_PYTHON_SCRIPT_TOOL = "run_python_script"
_SUPPORTED_KEYS = {
    "schema_version",
    "capabilities",
    "environment_variables",
    "haproxy",
    "mcp_sidecar",
    "ollama_sidecar",
    "squid_proxy",
}


def validate_top_level_keys(data: dict[str, object]) -> None:
    """Validate top-level sandbox spec keys."""
    unknown_keys = set(data) - _SUPPORTED_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported sandbox spec key: {names}")


def validate_schema_version(schema_version: object, supported_version: int) -> None:
    """Validate the sandbox spec schema version."""
    if schema_version != supported_version:
        raise ValueError(f"Unsupported sandbox spec schema_version: {schema_version}")


def validate_supported_capabilities(capabilities: tuple[str, ...]) -> None:
    """Validate declared sandbox capabilities against the supported set."""
    unsupported_capabilities = set(capabilities) - set(sandbox_capabilities.SUPPORTED)
    if unsupported_capabilities:
        names = ", ".join(sorted(unsupported_capabilities))
        raise ValueError(f"Unsupported sandbox capability: {names}")


def validate_spec_settings(
    capabilities: tuple[str, ...],
    allowed_domains: tuple[str, ...],
    allowed_ip_addresses: tuple[str, ...],
    mcp_sidecar_tools: tuple[str, ...],
) -> None:
    """Validate cross-section sandbox spec settings."""
    validate_network_settings(
        capabilities,
        allowed_domains,
        allowed_ip_addresses,
    )
    validate_mcp_sidecar_settings(capabilities, mcp_sidecar_tools)


def validate_network_settings(
    capabilities: tuple[str, ...],
    allowed_domains: tuple[str, ...],
    allowed_ip_addresses: tuple[str, ...],
) -> None:
    """Validate network-related capability and allowlist settings."""
    has_network = sandbox_capabilities.NETWORK in capabilities
    openai_capabilities = set(sandbox_capabilities.OPENAI_FAMILY).intersection(
        capabilities
    )
    if openai_capabilities and not has_network:
        names = ", ".join(sorted(openai_capabilities))
        raise ValueError(f"The {names} capability requires the network capability.")
    anthropic_capabilities = set(sandbox_capabilities.ANTHROPIC_FAMILY).intersection(
        capabilities
    )
    if anthropic_capabilities and not has_network:
        names = ", ".join(sorted(anthropic_capabilities))
        raise ValueError(f"The {names} capability requires the network capability.")

    if (allowed_domains or allowed_ip_addresses) and not has_network:
        raise ValueError(
            "allowed_domains and allowed_ip_addresses require the network capability."
        )
    if sandbox_capabilities.MCP_CLIENT in capabilities and not has_network:
        raise ValueError("The mcp_client capability requires the network capability.")
    if sandbox_capabilities.JINA_READER in capabilities and not has_network:
        raise ValueError("The jina_reader capability requires the network capability.")
    if sandbox_capabilities.HAPROXY in capabilities and not has_network:
        raise ValueError("The haproxy capability requires the network capability.")
    if sandbox_capabilities.OLLAMA in capabilities and not has_network:
        raise ValueError("The ollama capability requires the network capability.")

    for domain in allowed_domains:
        validate_domain_allowlist_entry(domain)

    for ip_address in allowed_ip_addresses:
        ipaddress.ip_network(ip_address.strip().strip("[]"), strict=False)


def validate_mcp_sidecar_settings(
    capabilities: tuple[str, ...],
    mcp_sidecar_tools: tuple[str, ...],
) -> None:
    """Validate MCP sidecar exposure against declared capabilities."""
    if _RUN_PYTHON_SCRIPT_TOOL not in mcp_sidecar_tools:
        return

    if sandbox_capabilities.MCP_CLIENT not in capabilities:
        raise ValueError("The run_python_script MCP tool requires mcp_client.")
    if sandbox_capabilities.CODE_EXECUTION not in capabilities:
        raise ValueError("The run_python_script MCP tool requires code_execution.")


def validate_domain_allowlist_entry(domain: str) -> None:
    """Validate one Squid proxy domain allowlist entry."""
    normalized_domain = domain.strip().lower()
    if not normalized_domain:
        raise ValueError("allowed_domains entries must not be empty.")

    if "://" in normalized_domain or "/" in normalized_domain:
        raise ValueError(
            "allowed_domains entries must be host names, not URLs or paths."
        )
