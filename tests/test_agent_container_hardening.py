"""Tests for AI agent container hardening helpers."""

from __future__ import annotations

from dataclasses import dataclass

from docker_sandbox.agent_container import hardening


@dataclass(frozen=True)
class _ProfileSpec:
    capabilities: tuple[str, ...]
    allowed_domains: tuple[str, ...] = ()
    allowed_ip_addresses: tuple[str, ...] = ()

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


def test_base_locked_down_profile_disables_network_and_shell() -> None:
    """Verify the base profile starts from the locked-down posture."""
    profile = hardening.base_locked_down_profile()
    policies = {policy.name: policy.value for policy in profile.environment}

    assert profile.name == hardening.LOCKED_DOWN_PROFILE_NAME
    assert profile.network_gateway is None
    assert "--network" in profile.container_run_options
    assert policies["OPENAI_API_KEY"] is None
    assert policies["SANDBOX_DENY_PROCESS_SPAWN"] == "1"


def test_apply_network_capability_adds_gateway_and_removes_network_none() -> None:
    """Verify network capability moves egress through the Squid gateway."""
    profile = hardening.apply_network_capability(
        hardening.base_locked_down_profile(),
        allowed_domains=(".example.com",),
        allowed_ip_addresses=("203.0.113.0/24",),
    )

    assert profile.network_gateway is not None
    assert profile.network_gateway.allowed_domains == (".example.com",)
    assert profile.network_gateway.allowed_ip_addresses == ("203.0.113.0/24",)
    assert "--network" not in profile.container_run_options
    assert profile.network_dns_policy is not None


def test_apply_openai_capability_allows_openai_key() -> None:
    """Verify OpenAI capability removes the deny policy for OPENAI_API_KEY."""
    profile = hardening.apply_openai_capability(hardening.base_locked_down_profile())
    policies = {policy.name: policy.value for policy in profile.environment}

    assert "OPENAI_API_KEY" not in policies


def test_apply_shell_access_capability_allows_process_spawn() -> None:
    """Verify shell access flips the process-spawn policy."""
    profile = hardening.apply_shell_access_capability(
        hardening.base_locked_down_profile()
    )
    policies = {policy.name: policy.value for policy in profile.environment}

    assert policies["SANDBOX_DENY_PROCESS_SPAWN"] == "0"


def test_apply_playwright_capability_expands_browser_resources() -> None:
    """Verify Playwright capability widens only the browser runtime needs."""
    profile = hardening.apply_playwright_capability(
        hardening.base_locked_down_profile()
    )
    policies = {policy.name: policy.value for policy in profile.environment}

    assert profile.browser_surface is not None
    assert policies["PLAYWRIGHT_BROWSERS_PATH"] == "/ms-playwright"
    assert profile.memory == "2g"
    assert profile.shm_size == "1g"
    assert any(rule.path == "/ms-playwright" for rule in profile.landlock_rules)


def test_apply_crewai_capability_adds_runtime_tmpfs_and_disables_tracing() -> None:
    """Verify CrewAI capability adds its explicit runtime relaxations."""
    profile = hardening.apply_crewai_capability(hardening.base_locked_down_profile())
    policies = {policy.name: policy.value for policy in profile.environment}

    assert policies["CREWAI_TRACING_ENABLED"] == "false"
    assert policies["OTEL_SDK_DISABLED"] == "true"
    assert "/tmp/sandbox-home:rw,nosuid,nodev,noexec,size=64m" in (
        " ".join(profile.container_run_options)
    )


def test_resolve_profile_applies_capabilities_and_generated_identity() -> None:
    """Verify hardening owns complete profile resolution."""
    spec = _ProfileSpec(
        capabilities=("network", "openai_agents", "shell_access"),
        allowed_domains=("example.com",),
    )

    profile = hardening.resolve_profile(
        spec,
        image_name="sandbox-agent/sandbox-agent:test",
        image_tag="1-test",
    )
    policies = {policy.name: policy.value for policy in profile.environment}

    assert profile.name == "sandbox-spec-1-test"
    assert profile.image_name == "sandbox-agent/sandbox-agent:test"
    assert profile.network_gateway is not None
    assert profile.network_gateway.allowed_domains == ("example.com", ".openai.com")
    assert "OPENAI_API_KEY" not in policies
    assert policies["SANDBOX_DENY_PROCESS_SPAWN"] == "0"
