"""AI agent container hardening profile helpers."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Protocol

from docker_sandbox.models import (
    BrowserSurfaceProfile,
    DockerProfile,
    DockerSysctl,
    DockerUlimit,
    EnvironmentVariablePolicy,
    LandlockPathRule,
    NetworkDnsPolicy,
    NetworkGatewayProfile,
)

LOCKED_DOWN_PROFILE_NAME = "locked-down"
LOCKED_DOWN_IMAGE_NAME = "sandbox-agent/sandbox-agent:locked-down"

_GATEWAY_IMAGE_NAME = "ubuntu/squid:latest"
_GATEWAY_PROXY_HOST = "egress-gateway"
_GATEWAY_PROXY_PORT = 3128
_OPENAI_API_KEY_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"
_ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE = "ANTHROPIC_API_KEY"
_PROCESS_SPAWN_POLICY_ENVIRONMENT_VARIABLE = "SANDBOX_DENY_PROCESS_SPAWN"
_PLAYWRIGHT_BROWSERS_PATH = "/ms-playwright"
_OPENAI_ALLOWED_DOMAIN = ".openai.com"
_ANTHROPIC_ALLOWED_DOMAIN = ".anthropic.com"
_NO_PROXY_HOSTS = (
    "127.0.0.1",
    "localhost",
    "169.254.169.254",
    "metadata.google.internal",
)
_BLOCKED_HOSTNAMES = (
    "host.docker.internal",
    "gateway.docker.internal",
    "kubernetes.docker.internal",
    "metadata.google.internal",
)
_CREWAI_WRITABLE_TMPFS_OPTIONS = (
    "/tmp/sandbox-home:rw,nosuid,nodev,noexec,size=64m,uid=1000,gid=1000,mode=700",
    "/tmp/sandbox-cache:rw,nosuid,nodev,noexec,size=64m,uid=1000,gid=1000,mode=700",
    "/tmp/sandbox-config:rw,nosuid,nodev,noexec,size=64m,uid=1000,gid=1000,mode=700",
    "/tmp/sandbox-runtime:rw,nosuid,nodev,noexec,size=16m,uid=1000,gid=1000,mode=700",
)


class ProfileSpec(Protocol):
    """Capability data needed to resolve an agent container profile."""

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        """Return declared network allowed domains."""
        ...

    @property
    def allowed_ip_addresses(self) -> tuple[str, ...]:
        """Return declared network allowed IP addresses."""
        ...

    def has_capability(self, capability: str) -> bool:
        """Return whether a capability is declared."""
        ...


_NETWORK_CAPABILITY = "network"
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

_LOCKED_DOWN_PROFILE = DockerProfile(
    name=LOCKED_DOWN_PROFILE_NAME,
    description="Run Sandbox Agent with the locked-down Docker profile.",
    image_name=LOCKED_DOWN_IMAGE_NAME,
    image_build_arguments=(
        "--build-arg",
        "SANDBOX_MINIMIZE_IMAGE=true",
        "--build-arg",
        "SANDBOX_REMOVE_PYTHON_PACKAGING=true",
        "--build-arg",
        "SANDBOX_REMOVE_DESKTOP_AUTOMATION=true",
        "--build-arg",
        "SANDBOX_REMOVE_PACKAGE_METADATA=true",
    ),
    ipc_mode=None,
    shm_size=None,
    cgroupns_mode="private",
    pids_limit=64,
    memory="128m",
    memory_swap="128m",
    cpus="1",
    ulimits=(
        DockerUlimit("nofile", 256, 256),
        DockerUlimit("nproc", 64, 64),
        DockerUlimit("fsize", 1048576, 1048576),
    ),
    sysctls=(DockerSysctl("net.ipv4.ip_unprivileged_port_start", "1024"),),
    cap_drop=("ALL",),
    security_options=("no-new-privileges",),
    container_run_options=(
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/sandbox-work:rw,nosuid,nodev,noexec,size=1m",
        "--tmpfs",
        "/proc/acpi:rw,nosuid,nodev,noexec,size=1k",
        "--tmpfs",
        "/sys/firmware:rw,nosuid,nodev,noexec,size=1k",
        "--env",
        "HOME=/tmp/sandbox-home",
        "--env",
        "XDG_CACHE_HOME=/tmp/sandbox-cache",
        "--env",
        "XDG_CONFIG_HOME=/tmp/sandbox-config",
        "--env",
        "XDG_RUNTIME_DIR=/tmp/sandbox-runtime",
    ),
    remote_run_root="/sandbox-work",
    allowed_directory_template="{remote_run_directory}/allowed",
    denied_directory_template="/sandbox-denied",
    readonly_denied_mount_target="/sandbox-denied",
    landlock_rules=(
        LandlockPathRule("/bin", "rx"),
        LandlockPathRule("/etc", "r"),
        LandlockPathRule("/lib", "rx"),
        LandlockPathRule("/lib64", "rx"),
        LandlockPathRule("/opt/sandbox-agent", "rx"),
        LandlockPathRule("/sbin", "rx"),
        LandlockPathRule("/usr", "rx"),
        LandlockPathRule("/usr/local", "rx"),
        LandlockPathRule("/var", "r"),
        LandlockPathRule("/dev", "rw"),
        LandlockPathRule("/proc", "r"),
        LandlockPathRule("/sandbox-source", "r"),
        LandlockPathRule("/sandbox-output", "rw"),
        LandlockPathRule("/sandbox-work", "rw"),
        LandlockPathRule("/tmp", "rw"),
    ),
    network_gateway=None,
    network_dns_policy=None,
    readonly_persistence_directories=(
        "/tmp/sandbox-home/.config/autostart",
        "/tmp/sandbox-config/autostart",
        "/tmp/sandbox-home/.config/systemd/user",
        "/tmp/sandbox-config/systemd/user",
    ),
    browser_surface=None,
    environment=(
        EnvironmentVariablePolicy("OPENAI_API_KEY", None),
        EnvironmentVariablePolicy("SSH_AUTH_SOCK", None),
        EnvironmentVariablePolicy("GPG_AGENT_INFO", None),
        EnvironmentVariablePolicy("DBUS_SESSION_BUS_ADDRESS", None),
        EnvironmentVariablePolicy("DISPLAY", None),
        EnvironmentVariablePolicy("WAYLAND_DISPLAY", None),
        EnvironmentVariablePolicy("GNUPGHOME", "/tmp/sandbox-gnupg-empty"),
        EnvironmentVariablePolicy("SANDBOX_DENY_UDP", "1"),
        EnvironmentVariablePolicy("SANDBOX_DENY_METADATA_ENDPOINTS", "1"),
        EnvironmentVariablePolicy("SANDBOX_DENY_ALL_INTERFACE_BIND", "1"),
        EnvironmentVariablePolicy("SANDBOX_DENY_HARDWARE_DEVICE_ENUMERATION", "1"),
        EnvironmentVariablePolicy("SANDBOX_DENY_PROCESS_SPAWN", "1"),
    ),
    remove_desktop_automation_tools=True,
)


def base_locked_down_profile() -> DockerProfile:
    """Return the base locked-down AI agent container profile."""
    return _LOCKED_DOWN_PROFILE


def resolve_profile(
    spec: ProfileSpec,
    image_name: str,
    image_tag: str,
) -> DockerProfile:
    """Resolve a low-level Docker profile from a high-level sandbox spec."""
    profile = base_locked_down_profile()
    if spec.has_capability(_NETWORK_CAPABILITY):
        profile = apply_network_capability(
            profile,
            allowed_domains=resolve_allowed_domains(
                spec.allowed_domains,
                include_openai=has_openai_family_capability(spec),
                include_anthropic=has_anthropic_family_capability(spec),
            ),
            allowed_ip_addresses=spec.allowed_ip_addresses,
        )

    if has_openai_family_capability(spec):
        profile = apply_openai_capability(profile)
    if has_anthropic_family_capability(spec):
        profile = apply_anthropic_capability(profile)

    if spec.has_capability(_SHELL_ACCESS_CAPABILITY) or spec.has_capability(
        _ANTHROPIC_CLAUDE_CAPABILITY
    ):
        profile = apply_shell_access_capability(profile)

    if spec.has_capability(_CREWAI_CAPABILITY):
        profile = apply_crewai_capability(profile)

    if spec.has_capability(_PLAYWRIGHT_CHROMIUM_CAPABILITY):
        profile = apply_playwright_capability(profile)

    return with_generated_identity(
        profile,
        name=f"sandbox-spec-{image_tag}",
        image_name=image_name,
    )


def apply_network_capability(
    profile: DockerProfile,
    allowed_domains: tuple[str, ...],
    allowed_ip_addresses: tuple[str, ...] = (),
) -> DockerProfile:
    """Apply network capability hardening changes to an agent profile."""
    network_gateway = NetworkGatewayProfile(
        image_name=_GATEWAY_IMAGE_NAME,
        proxy_host=_GATEWAY_PROXY_HOST,
        proxy_port=_GATEWAY_PROXY_PORT,
        allowed_domains=allowed_domains,
        allowed_ip_addresses=allowed_ip_addresses,
        no_proxy_hosts=_NO_PROXY_HOSTS,
    )
    return replace(
        profile,
        network_gateway=network_gateway,
        network_dns_policy=NetworkDnsPolicy(blocked_hostnames=_BLOCKED_HOSTNAMES),
        container_run_options=_without_docker_network_none(
            profile.container_run_options
        ),
    )


def apply_openai_capability(profile: DockerProfile) -> DockerProfile:
    """Allow OpenAI credentials through the agent profile environment."""
    return replace(
        profile,
        environment=_without_environment_policy(
            profile.environment,
            _OPENAI_API_KEY_ENVIRONMENT_VARIABLE,
        ),
    )


def apply_shell_access_capability(profile: DockerProfile) -> DockerProfile:
    """Allow process spawning within the otherwise locked-down agent profile."""
    return replace(
        profile,
        environment=_replace_environment_policy(
            profile.environment,
            _PROCESS_SPAWN_POLICY_ENVIRONMENT_VARIABLE,
            "0",
        ),
    )


def apply_playwright_capability(profile: DockerProfile) -> DockerProfile:
    """Apply Playwright/Chromium runtime hardening changes."""
    container_run_options = _replace_tmpfs_option(
        profile.container_run_options,
        "/tmp",
        "/tmp:rw,nosuid,nodev,noexec,size=512m",
    )
    container_run_options = _replace_tmpfs_option(
        container_run_options,
        "/sandbox-work",
        "/sandbox-work:rw,nosuid,nodev,noexec,size=128m",
    )
    return replace(
        profile,
        browser_surface=BrowserSurfaceProfile(),
        environment=_append_environment_policy(
            profile.environment,
            "PLAYWRIGHT_BROWSERS_PATH",
            _PLAYWRIGHT_BROWSERS_PATH,
        ),
        landlock_rules=_append_landlock_rule(
            profile.landlock_rules,
            _PLAYWRIGHT_BROWSERS_PATH,
            "rx",
        ),
        container_run_options=container_run_options,
        pids_limit=512,
        memory="2g",
        memory_swap="2g",
        shm_size="1g",
        ulimits=(
            DockerUlimit("nofile", 4096, 4096),
            DockerUlimit("nproc", 512, 512),
            DockerUlimit("fsize", 52428800, 52428800),
        ),
    )


def apply_crewai_capability(profile: DockerProfile) -> DockerProfile:
    """Apply CrewAI runtime hardening changes."""
    environment = _append_environment_policy(
        profile.environment,
        "CREWAI_TRACING_ENABLED",
        "false",
    )
    environment = _append_environment_policy(
        environment,
        "OTEL_SDK_DISABLED",
        "true",
    )
    container_run_options = profile.container_run_options
    for tmpfs_option in _CREWAI_WRITABLE_TMPFS_OPTIONS:
        container_run_options = _append_tmpfs_option(
            container_run_options,
            tmpfs_option,
        )

    return replace(
        profile,
        environment=environment,
        container_run_options=container_run_options,
    )


def apply_anthropic_capability(profile: DockerProfile) -> DockerProfile:
    """Allow Anthropic credentials through the agent profile environment."""
    return replace(
        profile,
        environment=_without_environment_policy(
            profile.environment,
            _ANTHROPIC_API_KEY_ENVIRONMENT_VARIABLE,
        ),
    )


def with_generated_identity(
    profile: DockerProfile,
    name: str,
    image_name: str,
) -> DockerProfile:
    """Apply generated profile identity fields after capability hardening."""
    return replace(
        profile,
        name=name,
        description="Generated hardened profile for the sandbox spec.",
        image_name=image_name,
        image_build_arguments=(),
    )


def resolve_allowed_domains(
    allowed_domains: tuple[str, ...],
    include_openai: bool = False,
    include_anthropic: bool = False,
) -> tuple[str, ...]:
    """Return network domains widened by selected model-provider capabilities."""
    domains = list(allowed_domains)
    if include_openai:
        domains.append(_OPENAI_ALLOWED_DOMAIN)
    if include_anthropic:
        domains.append(_ANTHROPIC_ALLOWED_DOMAIN)

    return tuple(dict.fromkeys(domains))


def resolved_profile_data(profile: DockerProfile) -> dict[str, Any]:
    """Convert a resolved profile to JSON-safe diagnostic data."""
    data = _json_safe(asdict(profile))
    if not isinstance(data, dict):
        raise TypeError("Resolved profile data must be a dictionary.")

    return data


def has_openai_family_capability(spec: ProfileSpec) -> bool:
    """Return whether a spec includes an OpenAI-family capability."""
    return (
        spec.has_capability(_OPENAI_CAPABILITY)
        or spec.has_capability(_OPENAI_AGENTS_CAPABILITY)
        or spec.has_capability(_BEEAI_CAPABILITY)
        or spec.has_capability(_GOOGLE_ADK_CAPABILITY)
        or spec.has_capability(_LANGCHAIN_CAPABILITY)
        or spec.has_capability(_LANGGRAPH_CAPABILITY)
        or spec.has_capability(_MICROSOFT_AGENT_CAPABILITY)
        or spec.has_capability(_CREWAI_CAPABILITY)
        or spec.has_capability(_OTTO_AGENT_CAPABILITY)
    )


def has_anthropic_family_capability(spec: ProfileSpec) -> bool:
    """Return whether a spec includes an Anthropic-family capability."""
    return spec.has_capability(_ANTHROPIC_CLAUDE_CAPABILITY) or spec.has_capability(
        _ANTHROPIC_PYTHON_CAPABILITY
    )


def without_docker_network_none(options: tuple[str, ...]) -> tuple[str, ...]:
    """Return Docker options with explicit network-none settings removed."""
    return _without_docker_network_none(options)


def without_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    """Return environment policies without a named policy."""
    return _without_environment_policy(policies, name)


def replace_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
    value: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    """Return environment policies with a named policy value replaced."""
    return _replace_environment_policy(policies, name, value)


def append_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
    value: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    """Return environment policies with a named policy appended or replaced."""
    return _append_environment_policy(policies, name, value)


def append_landlock_rule(
    rules: tuple[LandlockPathRule, ...],
    path: str,
    access: str,
) -> tuple[LandlockPathRule, ...]:
    """Return Landlock rules with a path rule appended when missing."""
    return _append_landlock_rule(rules, path, access)


def replace_tmpfs_option(
    options: tuple[str, ...],
    mount_path: str,
    replacement: str,
) -> tuple[str, ...]:
    """Return Docker options with one tmpfs mount replaced."""
    return _replace_tmpfs_option(options, mount_path, replacement)


def append_tmpfs_option(
    options: tuple[str, ...],
    tmpfs_option: str,
) -> tuple[str, ...]:
    """Return Docker options with a tmpfs mount appended when missing."""
    return _append_tmpfs_option(options, tmpfs_option)


def _without_docker_network_none(options: tuple[str, ...]) -> tuple[str, ...]:
    filtered_options = []
    skip_next = False
    for index, option in enumerate(options):
        if skip_next:
            skip_next = False
            continue

        if option == "--network" and index + 1 < len(options):
            if options[index + 1] == "none":
                skip_next = True
                continue

        if option == "--network=none":
            continue

        filtered_options.append(option)

    return tuple(filtered_options)


def _without_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    return tuple(policy for policy in policies if policy.name != name)


def _replace_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
    value: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    return tuple(
        EnvironmentVariablePolicy(policy.name, value) if policy.name == name else policy
        for policy in policies
    )


def _append_environment_policy(
    policies: tuple[EnvironmentVariablePolicy, ...],
    name: str,
    value: str,
) -> tuple[EnvironmentVariablePolicy, ...]:
    if any(policy.name == name for policy in policies):
        return _replace_environment_policy(policies, name, value)

    return (*policies, EnvironmentVariablePolicy(name, value))


def _append_landlock_rule(
    rules: tuple[LandlockPathRule, ...],
    path: str,
    access: str,
) -> tuple[LandlockPathRule, ...]:
    if any(getattr(rule, "path", None) == path for rule in rules):
        return rules

    return (*rules, LandlockPathRule(path, access))


def _replace_tmpfs_option(
    options: tuple[str, ...],
    mount_path: str,
    replacement: str,
) -> tuple[str, ...]:
    replaced_options = []
    skip_next = False
    for index, option in enumerate(options):
        if skip_next:
            skip_next = False
            continue

        if option == "--tmpfs" and index + 1 < len(options):
            tmpfs_value = options[index + 1]
            if tmpfs_value.startswith(f"{mount_path}:"):
                replaced_options.extend(["--tmpfs", replacement])
                skip_next = True
                continue

        replaced_options.append(option)

    return tuple(replaced_options)


def _append_tmpfs_option(
    options: tuple[str, ...],
    tmpfs_option: str,
) -> tuple[str, ...]:
    if tmpfs_option in options:
        return options

    return (*options, "--tmpfs", tmpfs_option)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
