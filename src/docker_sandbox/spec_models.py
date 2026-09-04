"""Normalized sandbox specification data models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import capabilities as sandbox_capabilities
from .models import HAProxyConfiguration

_IMAGE_REPOSITORY = "sandbox-agent/sandbox-agent"
_OLLAMA_IMAGE_REPOSITORY = "sandbox-agent/ollama-sidecar"
_HASH_LENGTH = 16


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
        """Return the generated agent image tag."""
        return f"{self.schema_version}-{self.agent_image_hash}"

    @property
    def image_name(self) -> str:
        """Return the generated agent image name."""
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
        """Return the generated agent image hash."""
        return self.agent_image_hash

    @property
    def agent_image_hash(self) -> str:
        """Return the stable hash for the agent image configuration."""
        digest = hashlib.sha256(self.normalized_json.encode("utf-8")).hexdigest()
        return digest[:_HASH_LENGTH]

    @property
    def ollama_image_hash(self) -> str:
        """Return the stable hash for the Ollama sidecar configuration."""
        digest = hashlib.sha256(self.ollama_normalized_json.encode("utf-8")).hexdigest()
        return digest[:_HASH_LENGTH]

    @property
    def normalized_json(self) -> str:
        """Return the normalized agent image configuration as JSON."""
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
        """Return a JSON-safe normalized dictionary representation."""
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

    def to_agent_image_dict(self) -> dict[str, object]:
        """Return normalized data that affects only the agent container image."""
        data = self.to_dict()
        capabilities = [
            capability
            for capability in self.capabilities
            if capability not in sandbox_capabilities.AGENT_IMAGE_EXCLUDED
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
        """Return whether a capability is declared."""
        return capability in self.capabilities

    def _haproxy_to_dict(self) -> dict[str, object]:
        if self.haproxy is None:
            return {}

        return {
            "backend_host": self.haproxy.backend_host,
            "ports": list(self.haproxy.ports),
        }


@dataclass(frozen=True)
class SandboxEnvironmentVariable:
    """Environment variable declaration from the sandbox spec."""

    name: str
    value: str | None = None
    from_host: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe normalized dictionary representation."""
        data: dict[str, object] = {"name": self.name}
        if self.from_host:
            data["from_host"] = True
        else:
            data["value"] = self.value if self.value is not None else ""
        return data
