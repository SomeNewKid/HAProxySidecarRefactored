"""Docker sandbox hardening profile."""

from __future__ import annotations

from .models import (
    DockerProfile,
    DockerSysctl,
    DockerUlimit,
    EnvironmentVariablePolicy,
    LandlockPathRule,
)

LOCKED_DOWN_PROFILE_NAME = "locked-down"
LOCKED_DOWN_IMAGE_NAME = "sandbox-agent/sandbox-agent:locked-down"

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

_PROFILES: dict[str, DockerProfile] = {
    LOCKED_DOWN_PROFILE_NAME: _LOCKED_DOWN_PROFILE,
}

SUPPORTED_PROFILE_NAMES = tuple(sorted(_PROFILES))


def get_docker_profile(name: str) -> DockerProfile:
    """Return the Docker hardening profile with the given name."""
    try:
        return _PROFILES[name]
    except KeyError as error:
        raise ValueError(f"Unsupported Docker sandbox profile: {name}") from error
