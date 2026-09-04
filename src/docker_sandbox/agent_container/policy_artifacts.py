"""Policy artifact writers for the AI agent container."""

from __future__ import annotations

from pathlib import Path

from docker_sandbox.agent_container import run as agent_run
from docker_sandbox.models import DockerConfiguration, SeccompProfile
from docker_sandbox.orchestration.artifacts import write_json_artifact

_LANDLOCK_POLICY_FILE_NAME = "landlock-policy.json"


def write(configuration: DockerConfiguration, run_directory: Path) -> None:
    """Write configured agent container policy artifacts for a sandbox run."""
    _write_landlock_policy(configuration, run_directory)
    _write_seccomp_profile(configuration, run_directory)


def build_seccomp_profile_data(seccomp_profile: SeccompProfile) -> dict[str, object]:
    """Build JSON-safe seccomp profile data for Docker."""
    return {
        "defaultAction": seccomp_profile.default_action,
        "syscalls": [
            {
                "names": list(seccomp_profile.denied_syscalls),
                "action": seccomp_profile.action,
            },
        ],
    }


def _write_landlock_policy(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.landlock_rules:
        return

    policy = {
        "rules": [
            {
                "path": rule.path,
                "access": rule.access,
            }
            for rule in configuration.profile.landlock_rules
        ],
    }
    policy_path = run_directory / _LANDLOCK_POLICY_FILE_NAME
    write_json_artifact(policy_path, policy)


def _write_seccomp_profile(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    seccomp_profile = configuration.profile.seccomp_profile
    if seccomp_profile is None:
        return

    profile_data = build_seccomp_profile_data(seccomp_profile)
    profile_path = run_directory / agent_run.SECCOMP_PROFILE_FILE_NAME
    write_json_artifact(profile_path, profile_data)
