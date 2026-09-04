"""Tests for AI agent container policy artifact writers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from docker_sandbox.agent_container import hardening, policy_artifacts, run
from docker_sandbox.models import DockerConfiguration, LandlockPathRule, SeccompProfile


def test_write_creates_landlock_and_seccomp_policy_artifacts(tmp_path: Path) -> None:
    """Verify configured policy files are written to the run directory."""
    configuration = _create_policy_configuration()

    policy_artifacts.write(configuration, tmp_path)

    landlock_policy = json.loads((tmp_path / "landlock-policy.json").read_text())
    seccomp_profile = json.loads((tmp_path / run.SECCOMP_PROFILE_FILE_NAME).read_text())

    assert landlock_policy == {
        "rules": [
            {
                "path": "/sandbox-output",
                "access": "rw",
            },
        ],
    }
    assert seccomp_profile == {
        "defaultAction": "SCMP_ACT_ALLOW",
        "syscalls": [
            {
                "names": ["mount", "umount2"],
                "action": "SCMP_ACT_ERRNO",
            },
        ],
    }


def test_write_omits_unconfigured_policy_artifacts(tmp_path: Path) -> None:
    """Verify policy files are not written when no policy is configured."""
    configuration = _create_policy_configuration()
    profile = replace(
        configuration.profile,
        landlock_rules=(),
        seccomp_profile=None,
    )
    configuration = replace(configuration, profile=profile)

    policy_artifacts.write(configuration, tmp_path)

    assert not (tmp_path / "landlock-policy.json").exists()
    assert not (tmp_path / run.SECCOMP_PROFILE_FILE_NAME).exists()


def test_build_seccomp_profile_data_preserves_actions_and_syscalls() -> None:
    """Verify seccomp policy data is converted to JSON-safe values."""
    seccomp_profile = SeccompProfile(
        denied_syscalls=("ptrace",),
        action="SCMP_ACT_TRACE",
        default_action="SCMP_ACT_ALLOW",
    )

    data = policy_artifacts.build_seccomp_profile_data(seccomp_profile)

    assert data == {
        "defaultAction": "SCMP_ACT_ALLOW",
        "syscalls": [
            {
                "names": ["ptrace"],
                "action": "SCMP_ACT_TRACE",
            },
        ],
    }


def _create_policy_configuration() -> DockerConfiguration:
    profile = replace(
        hardening.base_locked_down_profile(),
        landlock_rules=(LandlockPathRule("/sandbox-output", "rw"),),
        seccomp_profile=SeccompProfile(denied_syscalls=("mount", "umount2")),
    )
    return DockerConfiguration(
        base_directory=Path(".docker_sandbox"),
        dockerfile_path=Path("Dockerfile"),
        build_context=Path("."),
        guest_user="sandbox",
        profile=profile,
    )
