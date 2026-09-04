"""Declarative sandbox specification support."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from . import capabilities as sandbox_capabilities
from . import spec_sections, spec_validation
from .agent_container import hardening, image
from .models import DockerProfile
from .spec_environment import (
    resolve_environment_variables,
    resolve_local_environment_variable_names,
)
from .spec_models import (
    SandboxEnvironmentVariable as SandboxEnvironmentVariable,
)
from .spec_models import SandboxSpec as SandboxSpec

__all__ = [
    "SandboxEnvironmentVariable",
    "SandboxSpec",
    "generate_dockerfile",
    "load_sandbox_spec",
    "resolve_environment_variables",
    "resolve_local_environment_variable_names",
    "resolve_ollama_image_name",
    "resolve_profile",
    "resolved_profile_data",
]

_SUPPORTED_SCHEMA_VERSION = 1


def load_sandbox_spec(path: Path) -> SandboxSpec:
    """Load and validate a sandbox spec TOML file."""
    data = spec_sections.read_toml(path)
    spec_validation.validate_top_level_keys(data)

    schema_version_value = spec_sections.read_schema_version(
        data,
        _SUPPORTED_SCHEMA_VERSION,
    )
    spec_validation.validate_schema_version(
        schema_version_value,
        _SUPPORTED_SCHEMA_VERSION,
    )
    schema_version = cast(int, schema_version_value)

    capabilities = spec_sections.read_capabilities(data)
    spec_validation.validate_supported_capabilities(capabilities)

    allowed_domains, allowed_ip_addresses = spec_sections.read_squid_proxy(data)
    environment_variables = spec_sections.read_environment_variables(data)
    mcp_sidecar_tools, mcp_sidecar_resources = spec_sections.read_mcp_sidecar(data)
    haproxy = spec_sections.read_haproxy(data, capabilities)
    ollama_models = spec_sections.read_ollama_sidecar(data, capabilities)
    spec_validation.validate_spec_settings(
        capabilities,
        allowed_domains,
        allowed_ip_addresses,
        mcp_sidecar_tools,
    )

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
    normalized_models = spec_sections.normalize_ollama_models(models)
    spec = SandboxSpec(
        schema_version=_SUPPORTED_SCHEMA_VERSION,
        capabilities=(sandbox_capabilities.OLLAMA,),
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
