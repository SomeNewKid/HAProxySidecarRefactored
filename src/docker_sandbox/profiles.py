"""Docker sandbox hardening profile registry."""

from __future__ import annotations

from .agent_container.hardening import (
    LOCKED_DOWN_IMAGE_NAME,
    LOCKED_DOWN_PROFILE_NAME,
    base_locked_down_profile,
)
from .models import DockerProfile

__all__ = [
    "LOCKED_DOWN_IMAGE_NAME",
    "LOCKED_DOWN_PROFILE_NAME",
    "SUPPORTED_PROFILE_NAMES",
    "get_docker_profile",
]

_PROFILES: dict[str, DockerProfile] = {
    LOCKED_DOWN_PROFILE_NAME: base_locked_down_profile(),
}

SUPPORTED_PROFILE_NAMES = tuple(sorted(_PROFILES))


def get_docker_profile(name: str) -> DockerProfile:
    """Return the Docker hardening profile with the given name."""
    try:
        return _PROFILES[name]
    except KeyError as error:
        raise ValueError(f"Unsupported Docker sandbox profile: {name}") from error
