"""Declarative sandbox specification support."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_container import hardening, image
from .models import DockerProfile, HAProxyConfiguration

_IMAGE_REPOSITORY = "sandbox-agent/sandbox-agent"
_OLLAMA_IMAGE_REPOSITORY = "sandbox-agent/ollama-sidecar"
_SUPPORTED_SCHEMA_VERSION = 1
_NETWORK_CAPABILITY = "network"
_MCP_CLIENT_CAPABILITY = "mcp_client"
_JINA_READER_CAPABILITY = "jina_reader"
_CODE_EXECUTION_CAPABILITY = "code_execution"
_HAPROXY_CAPABILITY = "haproxy"
_OLLAMA_CAPABILITY = "ollama"
_OPENAI_CAPABILITY = "openai"
_OPENAI_AGENTS_CAPABILITY = "openai_agents"
_ANTHROPIC_CLAUDE_CAPABILITY = "anthropic_claude"
_ANTHROPIC_PYTHON_CAPABILITY = "anthropic_python"
_BEEAI_CAPABILITY = "ibm_beeai"
_GOOGLE_ADK_CAPABILITY = "google_adk"
_LANGCHAIN_CAPABILITY = "langchain"
_LANGGRAPH_CAPABILITY = "langgraph"
_MICROSOFT_AGENT_CAPABILITY = "microsoft_agent"
_CREWAI_CAPABILITY = "crewai"
_OTTO_AGENT_CAPABILITY = "otto_agent"
_PLAYWRIGHT_CHROMIUM_CAPABILITY = "playwright_chromium"
_SHELL_ACCESS_CAPABILITY = "shell_access"
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
_SUPPORTED_CAPABILITIES = {
    _NETWORK_CAPABILITY,
    _MCP_CLIENT_CAPABILITY,
    _JINA_READER_CAPABILITY,
    _CODE_EXECUTION_CAPABILITY,
    _HAPROXY_CAPABILITY,
    _OLLAMA_CAPABILITY,
    _OPENAI_CAPABILITY,
    _OPENAI_AGENTS_CAPABILITY,
    _ANTHROPIC_CLAUDE_CAPABILITY,
    _ANTHROPIC_PYTHON_CAPABILITY,
    _BEEAI_CAPABILITY,
    _GOOGLE_ADK_CAPABILITY,
    _LANGCHAIN_CAPABILITY,
    _LANGGRAPH_CAPABILITY,
    _MICROSOFT_AGENT_CAPABILITY,
    _CREWAI_CAPABILITY,
    _OTTO_AGENT_CAPABILITY,
    _PLAYWRIGHT_CHROMIUM_CAPABILITY,
    _SHELL_ACCESS_CAPABILITY,
}
_HASH_LENGTH = 16
_OPENAI_API_KEY_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"
_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE = "ANTHROPIC_API_KEY"
_DEFAULT_HAPROXY_BACKEND_HOST = "host.docker.internal"


@dataclass(frozen=True)
class SandboxSpec:
    """Normalized declarative description of the hosted workload."""

    schema_version: int
    capabilities: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    allowed_ip_addresses: tuple[str, ...] = ()
    environment_variables: tuple[SandboxEnvironmentVariable, ...] = ()
    mcp_sidecar_tools: tuple[str, ...] = ()
    mcp_sidecar_resources: tuple[str, ...] = ()
    haproxy: HAProxyConfiguration | None = None
    ollama_models: tuple[str, ...] = ()

    @property
    def image_tag(self) -> str:
        return f"{self.schema_version}-{self.agent_image_hash}"

    @property
    def image_name(self) -> str:
        return f"{_IMAGE_REPOSITORY}:{self.image_tag}"

    @property
    def ollama_image_tag(self) -> str | None:
        """Return the hash tag for the Ollama sidecar image when configured."""
        if not self.ollama_models:
            return None

        return f"{self.schema_version}-{self.ollama_image_hash}"

    @property
    def ollama_image_name(self) -> str | None:
        """Return the Ollama sidecar image name when configured."""
        tag = self.ollama_image_tag
        if tag is None:
            return None

        return f"{_OLLAMA_IMAGE_REPOSITORY}:{tag}"

    @property
    def normalized_hash(self) -> str:
        return self.agent_image_hash

    @property
    def agent_image_hash(self) -> str:
        digest = hashlib.sha256(self.normalized_json.encode("utf-8")).hexdigest()
        return digest[:_HASH_LENGTH]

    @property
    def ollama_image_hash(self) -> str:
        """Return the stable hash for the Ollama sidecar configuration."""
        digest = hashlib.sha256(self.ollama_normalized_json.encode("utf-8")).hexdigest()
        return digest[:_HASH_LENGTH]

    @property
    def normalized_json(self) -> str:
        return json.dumps(
            self.to_agent_image_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def ollama_normalized_json(self) -> str:
        """Return the normalized Ollama sidecar configuration as JSON."""
        return json.dumps(
            self.to_ollama_image_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capabilities": list(self.capabilities),
            "environment_variables": [
                variable.to_dict()
                for variable in sorted(
                    self.environment_variables,
                    key=lambda variable: variable.name,
                )
            ],
            "squid_proxy": {
                "allowed_domains": list(self.allowed_domains),
                "allowed_ip_addresses": list(self.allowed_ip_addresses),
            },
            "mcp_sidecar": {
                "tools": list(self.mcp_sidecar_tools),
                "resources": list(self.mcp_sidecar_resources),
            },
            "haproxy": self._haproxy_to_dict(),
            "ollama_sidecar": {
                "models": list(self.ollama_models),
            },
        }

    def _haproxy_to_dict(self) -> dict[str, object]:
        if self.haproxy is None:
            return {}

        return {
            "backend_host": self.haproxy.backend_host,
            "ports": list(self.haproxy.ports),
        }

    def to_agent_image_dict(self) -> dict[str, object]:
        """Return normalized data that affects only the agent container image."""
        data = self.to_dict()
        capabilities = [
            capability
            for capability in self.capabilities
            if capability not in {_HAPROXY_CAPABILITY, _OLLAMA_CAPABILITY}
        ]
        data["capabilities"] = capabilities
        data.pop("haproxy")
        data.pop("ollama_sidecar")
        return data

    def to_ollama_image_dict(self) -> dict[str, object]:
        """Return normalized data that affects only the Ollama sidecar image."""
        return {
            "schema_version": self.schema_version,
            "ollama_sidecar": {
                "models": list(self.ollama_models),
            },
        }

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class SandboxEnvironmentVariable:
    """Environment variable declaration from the sandbox spec."""

    name: str
    value: str | None = None
    from_host: bool = False

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"name": self.name}
        if self.from_host:
            data["from_host"] = True
        else:
            data["value"] = self.value if self.value is not None else ""
        return data


def load_sandbox_spec(path: Path) -> SandboxSpec:
    """Load and validate a sandbox spec TOML file."""
    if not path.exists():
        raise ValueError(f"Sandbox spec was not found: {path}")

    with path.open("rb") as file:
        data = tomllib.load(file)

    unknown_keys = set(data) - _SUPPORTED_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported sandbox spec key: {names}")

    schema_version = data.get("schema_version", _SUPPORTED_SCHEMA_VERSION)
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"Unsupported sandbox spec schema_version: {schema_version}")

    capabilities = _read_string_tuple(data, "capabilities")
    unsupported_capabilities = set(capabilities) - _SUPPORTED_CAPABILITIES
    if unsupported_capabilities:
        names = ", ".join(sorted(unsupported_capabilities))
        raise ValueError(f"Unsupported sandbox capability: {names}")

    allowed_domains, allowed_ip_addresses = _read_squid_proxy(data)
    environment_variables = _read_environment_variables(data)
    mcp_sidecar_tools, mcp_sidecar_resources = _read_mcp_sidecar(data)
    haproxy = _read_haproxy(data, capabilities)
    ollama_models = _read_ollama_sidecar(data, capabilities)
    _validate_network_settings(capabilities, allowed_domains, allowed_ip_addresses)
    _validate_mcp_sidecar_settings(capabilities, mcp_sidecar_tools)

    return SandboxSpec(
        schema_version=schema_version,
        capabilities=capabilities,
        allowed_domains=allowed_domains,
        allowed_ip_addresses=allowed_ip_addresses,
        environment_variables=environment_variables,
        mcp_sidecar_tools=mcp_sidecar_tools,
        mcp_sidecar_resources=mcp_sidecar_resources,
        haproxy=haproxy,
        ollama_models=ollama_models,
    )


def resolve_ollama_image_name(models: tuple[str, ...]) -> str:
    """Return the deterministic Ollama sidecar image name for model names."""
    normalized_models = _normalize_ollama_models(models)
    spec = SandboxSpec(
        schema_version=_SUPPORTED_SCHEMA_VERSION,
        capabilities=(_OLLAMA_CAPABILITY,),
        ollama_models=normalized_models,
    )
    image_name = spec.ollama_image_name
    if image_name is None:
        raise ValueError("Ollama sidecar image requires at least one model.")

    return image_name


def resolve_profile(spec: SandboxSpec) -> DockerProfile:
    """Resolve a low-level Docker profile from a high-level sandbox spec."""
    return hardening.resolve_profile(
        spec,
        image_name=spec.image_name,
        image_tag=spec.image_tag,
    )


def generate_dockerfile(
    spec: SandboxSpec,
    include_probe_dependencies: bool = False,
) -> str:
    """Generate the Dockerfile needed by the sandbox spec."""
    return image.generate_dockerfile(
        spec,
        include_probe_dependencies=include_probe_dependencies,
    )


def resolved_profile_data(profile: DockerProfile) -> dict[str, Any]:
    """Convert a resolved profile to JSON-safe diagnostic data."""
    return hardening.resolved_profile_data(profile)


def _read_string_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Sandbox spec key must be a list of strings: {key}")
    return tuple(value)


def resolve_environment_variables(
    spec: SandboxSpec,
) -> tuple[tuple[str, str], ...]:
    """Return profile-style environment variable declarations."""
    variables: list[tuple[str, str]] = []
    variable_names = {variable.name for variable in spec.environment_variables}
    for variable in spec.environment_variables:
        if variable.from_host:
            variables.append((variable.name, "[local]"))
            continue

        variables.append((variable.name, variable.value or ""))

    if (
        hardening.has_openai_family_capability(spec)
        and _OPENAI_API_KEY_ENVIRONMENT_VARIABLE not in variable_names
    ):
        variables.append((_OPENAI_API_KEY_ENVIRONMENT_VARIABLE, "[local]"))
    if (
        hardening.has_anthropic_family_capability(spec)
        and _ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE not in variable_names
    ):
        variables.append((_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE, "[local]"))

    return tuple(variables)


def resolve_local_environment_variable_names(spec: SandboxSpec) -> frozenset[str]:
    """Return environment variable names copied from the host."""
    names = {
        variable.name for variable in spec.environment_variables if variable.from_host
    }
    if hardening.has_openai_family_capability(spec):
        names.add(_OPENAI_API_KEY_ENVIRONMENT_VARIABLE)
    if hardening.has_anthropic_family_capability(spec):
        names.add(_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE)
    return frozenset(names)


def _read_environment_variables(
    data: dict[str, object],
) -> tuple[SandboxEnvironmentVariable, ...]:
    entries = data.get("environment_variables", [])
    if not isinstance(entries, list):
        raise ValueError("environment_variables must be an array of tables.")

    variables = []
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("environment_variables entries must be tables.")

        variable = _read_environment_variable(entry)
        if variable.name in names:
            raise ValueError(f"Duplicate environment variable: {variable.name}")

        names.add(variable.name)
        variables.append(variable)

    return tuple(variables)


def _read_mcp_sidecar(
    data: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    value = data.get("mcp_sidecar", {})
    if not isinstance(value, dict):
        raise ValueError("mcp_sidecar must be a table.")

    unknown_keys = set(value) - _MCP_SIDECAR_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported mcp_sidecar key: {names}")

    tools = _read_string_tuple(value, "tools")
    resources = _read_string_tuple(value, "resources")
    return tools, resources


def _read_haproxy(
    data: dict[str, object],
    capabilities: tuple[str, ...],
) -> HAProxyConfiguration | None:
    value = data.get("haproxy")
    has_haproxy_capability = _HAPROXY_CAPABILITY in capabilities
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

    backend_host = _read_haproxy_backend_host(value)
    ports = _read_haproxy_ports(value)
    return HAProxyConfiguration(backend_host=backend_host, ports=ports)


def _read_haproxy_backend_host(data: dict[str, object]) -> str:
    value = data.get("backend_host", _DEFAULT_HAPROXY_BACKEND_HOST)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("haproxy backend_host must be a non-empty string.")

    return value.strip()


def _read_haproxy_ports(data: dict[str, object]) -> tuple[int, ...]:
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

    duplicate_ports = _find_duplicate_ports(tuple(ports))
    if duplicate_ports:
        names = ", ".join(str(port) for port in duplicate_ports)
        raise ValueError(f"Duplicate haproxy port: {names}")

    return tuple(ports)


def _read_ollama_sidecar(
    data: dict[str, object],
    capabilities: tuple[str, ...],
) -> tuple[str, ...]:
    value = data.get("ollama_sidecar")
    has_ollama_capability = _OLLAMA_CAPABILITY in capabilities
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

    models = _read_string_tuple(value, "models")
    if not has_ollama_capability:
        if models:
            raise ValueError("[ollama_sidecar].models requires the ollama capability.")

        return ()

    if not models:
        raise ValueError("The ollama capability requires [ollama_sidecar].models.")

    return _normalize_ollama_models(models)


def _read_squid_proxy(
    data: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    value = data.get("squid_proxy", {})
    if not isinstance(value, dict):
        raise ValueError("squid_proxy must be a table.")

    unknown_keys = set(value) - _SQUID_PROXY_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported squid_proxy key: {names}")

    allowed_domains = _read_string_tuple(value, "allowed_domains")
    allowed_ip_addresses = _read_string_tuple(value, "allowed_ip_addresses")
    return allowed_domains, allowed_ip_addresses


def _read_environment_variable(
    entry: dict[str, object],
) -> SandboxEnvironmentVariable:
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


def _validate_network_settings(
    capabilities: tuple[str, ...],
    allowed_domains: tuple[str, ...],
    allowed_ip_addresses: tuple[str, ...],
) -> None:
    has_network = _NETWORK_CAPABILITY in capabilities
    openai_capabilities = {
        _OPENAI_CAPABILITY,
        _OPENAI_AGENTS_CAPABILITY,
        _BEEAI_CAPABILITY,
        _GOOGLE_ADK_CAPABILITY,
        _LANGCHAIN_CAPABILITY,
        _LANGGRAPH_CAPABILITY,
        _MICROSOFT_AGENT_CAPABILITY,
        _CREWAI_CAPABILITY,
        _OTTO_AGENT_CAPABILITY,
    }.intersection(capabilities)
    if openai_capabilities and not has_network:
        names = ", ".join(sorted(openai_capabilities))
        raise ValueError(f"The {names} capability requires the network capability.")
    anthropic_capabilities = {
        _ANTHROPIC_CLAUDE_CAPABILITY,
        _ANTHROPIC_PYTHON_CAPABILITY,
    }.intersection(capabilities)
    if anthropic_capabilities and not has_network:
        names = ", ".join(sorted(anthropic_capabilities))
        raise ValueError(f"The {names} capability requires the network capability.")

    if (allowed_domains or allowed_ip_addresses) and not has_network:
        raise ValueError(
            "allowed_domains and allowed_ip_addresses require the network capability."
        )
    if _MCP_CLIENT_CAPABILITY in capabilities and not has_network:
        raise ValueError("The mcp_client capability requires the network capability.")
    if _JINA_READER_CAPABILITY in capabilities and not has_network:
        raise ValueError("The jina_reader capability requires the network capability.")
    if _HAPROXY_CAPABILITY in capabilities and not has_network:
        raise ValueError("The haproxy capability requires the network capability.")
    if _OLLAMA_CAPABILITY in capabilities and not has_network:
        raise ValueError("The ollama capability requires the network capability.")

    for domain in allowed_domains:
        _validate_domain_allowlist_entry(domain)

    for ip_address in allowed_ip_addresses:
        ipaddress.ip_network(ip_address.strip().strip("[]"), strict=False)


def _validate_mcp_sidecar_settings(
    capabilities: tuple[str, ...],
    mcp_sidecar_tools: tuple[str, ...],
) -> None:
    if _RUN_PYTHON_SCRIPT_TOOL not in mcp_sidecar_tools:
        return

    if _MCP_CLIENT_CAPABILITY not in capabilities:
        raise ValueError("The run_python_script MCP tool requires mcp_client.")
    if _CODE_EXECUTION_CAPABILITY not in capabilities:
        raise ValueError("The run_python_script MCP tool requires code_execution.")


def _validate_domain_allowlist_entry(domain: str) -> None:
    normalized_domain = domain.strip().lower()
    if not normalized_domain:
        raise ValueError("allowed_domains entries must not be empty.")

    if "://" in normalized_domain or "/" in normalized_domain:
        raise ValueError(
            "allowed_domains entries must be host names, not URLs or paths."
        )


def _normalize_ollama_models(models: tuple[str, ...]) -> tuple[str, ...]:
    normalized_models = tuple(sorted(model.strip() for model in models))
    if any(not model for model in normalized_models):
        raise ValueError("[ollama_sidecar].models entries must not be empty.")

    duplicate_models = _find_duplicate_ollama_models(normalized_models)
    if duplicate_models:
        names = ", ".join(duplicate_models)
        raise ValueError(f"Duplicate Ollama model: {names}")

    return normalized_models


def _find_duplicate_ollama_models(models: tuple[str, ...]) -> tuple[str, ...]:
    seen = set()
    duplicates = []
    for model in models:
        if model in seen and model not in duplicates:
            duplicates.append(model)
            continue

        seen.add(model)

    return tuple(duplicates)


def _find_duplicate_ports(ports: tuple[int, ...]) -> tuple[int, ...]:
    seen = set()
    duplicates = []
    for port in ports:
        if port in seen and port not in duplicates:
            duplicates.append(port)
            continue

        seen.add(port)

    return tuple(duplicates)
