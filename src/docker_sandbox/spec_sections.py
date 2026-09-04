"""Sandbox spec TOML section readers."""

from __future__ import annotations

import tomllib
from collections.abc import Hashable
from pathlib import Path
from typing import TypeVar

from . import capabilities as sandbox_capabilities
from .models import HAProxyConfiguration
from .orchestration import network
from .spec_models import SandboxEnvironmentVariable

_T = TypeVar("_T", bound=Hashable)

_HAPROXY_KEYS = {
    "backend_host",
    "ports",
}
_MCP_SIDECAR_KEYS = {
    "tools",
    "resources",
}
_SQUID_PROXY_KEYS = {
    "allowed_domains",
    "allowed_ip_addresses",
}
_OLLAMA_SIDECAR_KEYS = {
    "models",
}
_DEFAULT_HAPROXY_BACKEND_HOST = network.DOCKER_HOST_GATEWAY_HOSTNAME


def read_toml(path: Path) -> dict[str, object]:
    """Read a sandbox spec TOML file."""
    if not path.exists():
        raise ValueError(f"Sandbox spec was not found: {path}")

    with path.open("rb") as file:
        return tomllib.load(file)


def read_schema_version(data: dict[str, object], default: int) -> object:
    """Read the sandbox spec schema version."""
    return data.get("schema_version", default)


def read_capabilities(data: dict[str, object]) -> tuple[str, ...]:
    """Read declared sandbox capabilities from TOML data."""
    return read_string_tuple(data, "capabilities")


def read_string_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
    """Read a TOML list of strings as a tuple."""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Sandbox spec key must be a list of strings: {key}")
    return tuple(value)


def read_environment_variables(
    data: dict[str, object],
) -> tuple[SandboxEnvironmentVariable, ...]:
    """Read environment variable declarations from TOML data."""
    entries = data.get("environment_variables", [])
    if not isinstance(entries, list):
        raise ValueError("environment_variables must be an array of tables.")

    variables = []
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("environment_variables entries must be tables.")

        variable = read_environment_variable(entry)
        if variable.name in names:
            raise ValueError(f"Duplicate environment variable: {variable.name}")

        names.add(variable.name)
        variables.append(variable)

    return tuple(variables)


def read_environment_variable(
    entry: dict[str, object],
) -> SandboxEnvironmentVariable:
    """Read one environment variable declaration from TOML data."""
    allowed_keys = {"name", "value", "from_host"}
    unknown_keys = set(entry) - allowed_keys
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported environment variable key: {names}")

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("environment_variables entries require a non-empty name.")

    has_value = "value" in entry
    has_from_host = "from_host" in entry
    if has_value == has_from_host:
        raise ValueError(
            "environment_variables entries require exactly one of value or from_host."
        )

    if has_value:
        value = entry["value"]
        if not isinstance(value, str):
            raise ValueError("environment_variables value must be a string.")
        return SandboxEnvironmentVariable(name=name, value=value)

    from_host = entry["from_host"]
    if from_host is not True:
        raise ValueError("environment_variables from_host must be true.")

    return SandboxEnvironmentVariable(name=name, from_host=True)


def read_mcp_sidecar(
    data: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read MCP sidecar exposure settings from TOML data."""
    value = data.get("mcp_sidecar", {})
    if not isinstance(value, dict):
        raise ValueError("mcp_sidecar must be a table.")

    unknown_keys = set(value) - _MCP_SIDECAR_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported mcp_sidecar key: {names}")

    tools = read_string_tuple(value, "tools")
    resources = read_string_tuple(value, "resources")
    return tools, resources


def read_haproxy(
    data: dict[str, object],
    capabilities: tuple[str, ...],
) -> HAProxyConfiguration | None:
    """Read HAProxy sidecar settings from TOML data."""
    value = data.get("haproxy")
    has_haproxy_capability = sandbox_capabilities.HAPROXY in capabilities
    if value is None:
        if has_haproxy_capability:
            raise ValueError("The haproxy capability requires [haproxy].")

        return None

    if not has_haproxy_capability:
        raise ValueError("[haproxy] requires the haproxy capability.")

    if not isinstance(value, dict):
        raise ValueError("haproxy must be a table.")

    unknown_keys = set(value) - _HAPROXY_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported haproxy key: {names}")

    backend_host = read_haproxy_backend_host(value)
    ports = read_haproxy_ports(value)
    return HAProxyConfiguration(backend_host=backend_host, ports=ports)


def read_haproxy_backend_host(data: dict[str, object]) -> str:
    """Read the HAProxy backend host from TOML data."""
    value = data.get("backend_host", _DEFAULT_HAPROXY_BACKEND_HOST)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("haproxy backend_host must be a non-empty string.")

    return value.strip()


def read_haproxy_ports(data: dict[str, object]) -> tuple[int, ...]:
    """Read and validate HAProxy TCP ports from TOML data."""
    value = data.get("ports")
    if not isinstance(value, list):
        raise ValueError("haproxy ports must be a non-empty list of TCP ports.")

    ports = []
    for port in value:
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError("haproxy ports must contain only integer TCP ports.")
        if port < 1 or port > 65535:
            raise ValueError("haproxy ports must be between 1 and 65535.")
        ports.append(port)

    if not ports:
        raise ValueError("haproxy ports must be a non-empty list of TCP ports.")

    duplicate_ports = _find_duplicate_values(tuple(ports))
    if duplicate_ports:
        names = ", ".join(str(port) for port in duplicate_ports)
        raise ValueError(f"Duplicate haproxy port: {names}")

    return tuple(ports)


def read_ollama_sidecar(
    data: dict[str, object],
    capabilities: tuple[str, ...],
) -> tuple[str, ...]:
    """Read Ollama sidecar settings from TOML data."""
    value = data.get("ollama_sidecar")
    has_ollama_capability = sandbox_capabilities.OLLAMA in capabilities
    if value is None:
        if has_ollama_capability:
            raise ValueError("The ollama capability requires [ollama_sidecar].")

        return ()

    if not isinstance(value, dict):
        raise ValueError("ollama_sidecar must be a table.")

    unknown_keys = set(value) - _OLLAMA_SIDECAR_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported ollama_sidecar key: {names}")

    models = read_string_tuple(value, "models")
    if not has_ollama_capability:
        if models:
            raise ValueError("[ollama_sidecar].models requires the ollama capability.")

        return ()

    if not models:
        raise ValueError("The ollama capability requires [ollama_sidecar].models.")

    return normalize_ollama_models(models)


def read_squid_proxy(
    data: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read Squid proxy allowlists from TOML data."""
    value = data.get("squid_proxy", {})
    if not isinstance(value, dict):
        raise ValueError("squid_proxy must be a table.")

    unknown_keys = set(value) - _SQUID_PROXY_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported squid_proxy key: {names}")

    allowed_domains = read_string_tuple(value, "allowed_domains")
    allowed_ip_addresses = read_string_tuple(value, "allowed_ip_addresses")
    return allowed_domains, allowed_ip_addresses


def normalize_ollama_models(models: tuple[str, ...]) -> tuple[str, ...]:
    """Return normalized unique Ollama model names."""
    normalized_models = tuple(sorted(model.strip() for model in models))
    if any(not model for model in normalized_models):
        raise ValueError("[ollama_sidecar].models entries must not be empty.")

    duplicate_models = _find_duplicate_values(normalized_models)
    if duplicate_models:
        names = ", ".join(duplicate_models)
        raise ValueError(f"Duplicate Ollama model: {names}")

    return normalized_models


def _find_duplicate_values(values: tuple[_T, ...]) -> tuple[_T, ...]:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
            continue

        seen.add(value)

    return tuple(duplicates)
