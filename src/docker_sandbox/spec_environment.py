"""Runtime environment resolution for sandbox specs."""

from __future__ import annotations

from . import capabilities as sandbox_capabilities
from .spec_models import SandboxSpec

_OPENAI_API_KEY_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"
_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE = "ANTHROPIC_API_KEY"


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
        sandbox_capabilities.has_openai_family_capability(spec)
        and _OPENAI_API_KEY_ENVIRONMENT_VARIABLE not in variable_names
    ):
        variables.append((_OPENAI_API_KEY_ENVIRONMENT_VARIABLE, "[local]"))
    if (
        sandbox_capabilities.has_anthropic_family_capability(spec)
        and _ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE not in variable_names
    ):
        variables.append((_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE, "[local]"))

    return tuple(variables)


def resolve_local_environment_variable_names(spec: SandboxSpec) -> frozenset[str]:
    """Return environment variable names copied from the host."""
    names = {
        variable.name for variable in spec.environment_variables if variable.from_host
    }
    if sandbox_capabilities.has_openai_family_capability(spec):
        names.add(_OPENAI_API_KEY_ENVIRONMENT_VARIABLE)
    if sandbox_capabilities.has_anthropic_family_capability(spec):
        names.add(_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE)
    return frozenset(names)
