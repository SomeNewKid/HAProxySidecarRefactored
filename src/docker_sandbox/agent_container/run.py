"""AI agent container run command and environment helpers."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
from collections.abc import Mapping, Set
from pathlib import Path, PurePosixPath
from typing import IO, Any, TextIO

from docker_sandbox.container_guard import (
    CONTAINER_MARKER_ENVIRONMENT_VARIABLE,
    CONTAINER_MARKER_VALUE,
)
from docker_sandbox.models import (
    AgentSocketForward,
    BrowserDebuggingProfile,
    BrowserSurfaceProfile,
    DockerConfiguration,
    EnvironmentVariablePolicy,
    NetworkDnsPolicy,
    SandboxRunTarget,
    SocketMount,
)
from docker_sandbox.orchestration import wiring
from docker_sandbox.orchestration.types import CommandResult

DOCKER_EXECUTABLE = "docker"
REMOTE_OUTPUT_DIRECTORY = "/sandbox-output"
REMOTE_LANDLOCK_POLICY_PATH = f"{REMOTE_OUTPUT_DIRECTORY}/landlock-policy.json"
REMOTE_SOURCE_DIRECTORY = "/sandbox-source/src"
LOCAL_ENVIRONMENT_VALUE = "[local]"
SECCOMP_PROFILE_FILE_NAME = "seccomp-profile.json"
READONLY_DENIED_SOURCE_DIRECTORY = "readonly-denied"
READONLY_PERSISTENCE_SOURCE_DIRECTORY = "readonly-persistence"
DENIED_EXECUTABLE_SOURCE_DIRECTORY = "denied-executables"
GIT_REMOTE_URL = "https://github.com/SomeNewKid/ScratchpadOne.git"
ALLOWED_FILE_CONTENT = "This is a test file for the allowed directory."
DENIED_FILE_CONTENT = "This is a test file for the denied directory."
HIDDEN_ALLOWED_FILE_CONTENT = "This is a hidden file."
HIDDEN_DENIED_FILE_CONTENT = "This is a hidden file in the denied directory."

_DESKTOP_AUTOMATION_ENVIRONMENT_NAMES = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
)
_DESKTOP_AUTOMATION_EXECUTABLE_PATHS = (
    "/usr/bin/busctl",
    "/usr/bin/dbus-send",
    "/usr/bin/gdbus",
    "/usr/bin/qdbus",
    "/usr/bin/wmctrl",
    "/usr/bin/xdotool",
)


def build_allowed_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    """Build the agent container allowed directory path."""
    return format_directory_template(
        configuration.profile.allowed_directory_template,
        remote_run_directory,
    )


def build_denied_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    """Build the agent container denied directory path."""
    return format_directory_template(
        configuration.profile.denied_directory_template,
        remote_run_directory,
    )


def format_directory_template(template: str, remote_run_directory: str) -> str:
    """Format an agent container directory template."""
    return template.format(remote_run_directory=remote_run_directory)


def build_config_data(
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    guest_user: str,
    ssh_agent_socket: str | None = None,
    browser_debugging: BrowserDebuggingProfile | None = None,
    browser_surface: BrowserSurfaceProfile | None = None,
) -> dict[str, object]:
    """Build the configuration data mounted into the agent container."""
    return {
        "working_directory": remote_run_directory,
        "allowed_directory": allowed_directory,
        "denied_directory": denied_directory,
        "runtime_user_directory": f"/home/{guest_user}",
        "runtime_temp_directory": "/tmp",
        "mounted_shared_directory": None,
        "operating_system": "Linux",
        "allowed_domain": "example.com",
        "denied_domain": "example.net",
        "allowed_local_address": None,
        "denied_local_address": None,
        "allowed_localnet_address": None,
        "denied_localnet_address": None,
        "allowed_intranet_target": None,
        "denied_intranet_target": "192.168.86.28",
        "allowed_database_address": None,
        "denied_database_address": None,
        "container_runtime_socket": None,
        "local_dev_server_url": None,
        "local_model_server_url": None,
        "metadata_endpoint_url": None,
        "dns_exfiltration_domain": "c2FuZGJveC10ZXN0ZXI.example.com",
        "http_exfiltration_domain": "example.com",
        "http_exfiltration_header": "exfiltration=example",
        "websocket_exfiltration_url": "wss://echo.websocket.org",
        "smtp_exfiltration_url": None,
        "ssh_agent_socket": ssh_agent_socket,
        "browser_debugging_url": get_browser_debugging_url(browser_debugging),
        "browser_executable": get_browser_executable(browser_debugging),
        "existing_browser_profile": get_existing_browser_profile(browser_debugging),
        "browser_chromium_arguments": get_browser_chromium_arguments(browser_surface),
        "allowed_git_repository": None,
        "denied_git_repository": None,
        "git_remote_url": GIT_REMOTE_URL,
        "allow_camera_capture": get_allow_camera_capture(browser_surface),
        "allow_microphone_capture": get_allow_microphone_capture(browser_surface),
        "output_directory": REMOTE_OUTPUT_DIRECTORY,
    }


def build_docker_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    container_name: str,
    remote_run_directory: str,
    network_name: str | None = None,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    environment_variables: dict[str, str] | None = None,
    gateway_ip_address: str | None = None,
    local_environment_variable_names: Set[str] | None = None,
    verbose: bool = False,
    serialize_evidence: bool = False,
) -> list[str]:
    """Build the Docker run command for the AI agent container."""
    output_mount = f"type=bind,source={run_directory},target={REMOTE_OUTPUT_DIRECTORY}"
    source_mount = build_source_mount(configuration)
    command = [
        DOCKER_EXECUTABLE,
        "run",
        "--name",
        container_name,
        "--interactive",
        "--init",
    ]
    command.extend(build_ipc_options(configuration))
    command.extend(build_security_options(configuration, run_directory))
    command.extend(
        [
            "--mount",
            output_mount,
            "--mount",
            source_mount,
            "--user",
            configuration.guest_user,
        ]
    )
    if network_name is not None:
        command.extend(["--network", network_name])
    command.extend(build_dns_policy_options(configuration, gateway_ip_address))
    command.extend(configuration.profile.container_run_options)
    command.extend(build_readonly_denied_mount_options(configuration, run_directory))
    command.extend(
        build_readonly_persistence_mount_options(configuration, run_directory)
    )
    command.extend(build_socket_mount_options(configuration))
    command.extend(build_agent_socket_mount_options(configuration))
    command.extend(build_denied_executable_mount_options(configuration, run_directory))
    command.extend(
        build_environment_options(
            build_container_environment(
                configuration,
                environment_variables or {},
                gateway_ip_address,
            ),
            build_effective_local_environment_variable_names(
                local_environment_variable_names or frozenset(),
            ),
        )
    )
    command.extend(
        [
            configuration.profile.image_name,
            "/bin/sh",
            "-c",
            build_container_script(
                run_target=configuration.run_target,
                remote_run_directory=remote_run_directory,
                allowed_directory=(
                    allowed_directory
                    if allowed_directory is not None
                    else build_allowed_directory(configuration, remote_run_directory)
                ),
                denied_directory=(
                    denied_directory
                    if denied_directory is not None
                    else build_denied_directory(configuration, remote_run_directory)
                ),
                create_denied_fixture=(
                    configuration.profile.readonly_denied_mount_target is None
                ),
                verbose=verbose,
                serialize_evidence=serialize_evidence,
                landlock_policy_path=(
                    REMOTE_LANDLOCK_POLICY_PATH
                    if configuration.profile.landlock_rules
                    else None
                ),
            ),
        ]
    )
    return command


def build_ipc_options(configuration: DockerConfiguration) -> list[str]:
    """Build Docker IPC options for the agent container."""
    options = []
    if configuration.profile.ipc_mode is not None:
        options.append(f"--ipc={configuration.profile.ipc_mode}")

    if configuration.profile.shm_size is not None:
        options.extend(["--shm-size", configuration.profile.shm_size])

    return options


def build_security_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    """Build Docker security options for the agent container."""
    options = []
    if configuration.profile.cgroupns_mode is not None:
        options.append(f"--cgroupns={configuration.profile.cgroupns_mode}")

    if configuration.profile.pids_limit is not None:
        options.extend(["--pids-limit", str(configuration.profile.pids_limit)])

    if configuration.profile.memory is not None:
        options.extend(["--memory", configuration.profile.memory])

    if configuration.profile.memory_swap is not None:
        options.extend(["--memory-swap", configuration.profile.memory_swap])

    if configuration.profile.cpus is not None:
        options.extend(["--cpus", configuration.profile.cpus])

    for ulimit in configuration.profile.ulimits:
        options.extend(
            [
                "--ulimit",
                f"{ulimit.name}={ulimit.soft}:{ulimit.hard}",
            ]
        )

    for sysctl in configuration.profile.sysctls:
        options.extend(["--sysctl", f"{sysctl.name}={sysctl.value}"])

    for capability in configuration.profile.cap_drop:
        options.append(f"--cap-drop={capability}")

    for capability in configuration.profile.cap_add:
        options.append(f"--cap-add={capability}")

    for security_option in configuration.profile.security_options:
        options.extend(["--security-opt", security_option])

    if configuration.profile.seccomp_profile is not None:
        seccomp_path = run_directory / SECCOMP_PROFILE_FILE_NAME
        options.extend(["--security-opt", f"seccomp={seccomp_path}"])

    return options


def build_dns_policy_options(
    configuration: DockerConfiguration,
    gateway_ip_address: str | None,
) -> list[str]:
    """Build Docker DNS options for the agent container."""
    dns_policy = configuration.profile.network_dns_policy
    if dns_policy is None:
        return []

    options: list[str] = []
    dns_address = get_dns_policy_address(dns_policy, gateway_ip_address)
    options.extend(["--dns", dns_address])
    for dns_option in dns_policy.dns_options:
        options.extend(["--dns-option", dns_option])

    for hostname in dns_policy.blocked_hostnames:
        options.extend(
            [
                "--add-host",
                f"{hostname}:{dns_policy.blocked_hostname_address}",
            ]
        )

    return options


def get_dns_policy_address(
    dns_policy: NetworkDnsPolicy,
    gateway_ip_address: str | None,
) -> str:
    """Resolve the DNS address for an agent container run."""
    if dns_policy.use_gateway_as_dns and gateway_ip_address is not None:
        return gateway_ip_address

    return dns_policy.fallback_dns_address


def build_source_mount(configuration: DockerConfiguration) -> str:
    """Build the source mount for the agent container."""
    source_directory = configuration.build_context / "src"
    return (
        f"type=bind,source={source_directory},target={REMOTE_SOURCE_DIRECTORY},readonly"
    )


def build_container_environment(
    configuration: DockerConfiguration,
    environment_variables: Mapping[str, str],
    gateway_ip_address: str | None = None,
) -> dict[str, str]:
    """Build environment variables for the agent container."""
    container_environment = dict(environment_variables)
    container_environment["PYTHONPATH"] = REMOTE_SOURCE_DIRECTORY
    container_environment["PYTHONUNBUFFERED"] = "1"
    container_environment[CONTAINER_MARKER_ENVIRONMENT_VARIABLE] = (
        CONTAINER_MARKER_VALUE
    )
    ssh_agent_socket = get_container_ssh_agent_socket(configuration)
    if ssh_agent_socket is not None:
        container_environment["SSH_AUTH_SOCK"] = ssh_agent_socket

    gpg_home = get_container_gpg_home(configuration)
    if gpg_home is not None:
        container_environment["GNUPGHOME"] = gpg_home

    apply_environment_policies(
        container_environment,
        configuration.profile.environment,
    )
    apply_desktop_automation_policy(
        container_environment,
        configuration.profile.allow_desktop_automation_channel,
    )
    wiring.apply_agent_sidecar_environment(
        container_environment,
        configuration,
        gateway_ip_address,
    )
    return container_environment


def build_effective_local_environment_variable_names(
    local_environment_variable_names: Set[str],
) -> Set[str]:
    """Remove local-only variables that must not pass into the agent."""
    names = set(local_environment_variable_names)
    names.difference_update(wiring.database_environment_variable_names())

    return names


def apply_environment_policies(
    environment: dict[str, str],
    policies: tuple[EnvironmentVariablePolicy, ...],
) -> None:
    """Apply configured agent environment variable policies."""
    for policy in policies:
        if policy.value is None:
            environment.pop(policy.name, None)
            continue

        environment[policy.name] = policy.value


def apply_desktop_automation_policy(
    environment: dict[str, str],
    allow_desktop_automation_channel: bool,
) -> None:
    """Remove desktop automation environment when the profile disables it."""
    if allow_desktop_automation_channel:
        return

    for name in _DESKTOP_AUTOMATION_ENVIRONMENT_NAMES:
        environment.pop(name, None)


def build_readonly_denied_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    """Build readonly denied fixture mount options for the agent container."""
    target = configuration.profile.readonly_denied_mount_target
    if target is None:
        return []

    source = run_directory / READONLY_DENIED_SOURCE_DIRECTORY
    mount = f"type=bind,source={source},target={target},readonly"
    return [
        "--mount",
        mount,
    ]


def build_readonly_persistence_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    """Build readonly persistence directory mounts for the agent container."""
    options = []
    for target in configuration.profile.readonly_persistence_directories:
        validate_container_directory(target)
        source = build_readonly_persistence_source_directory(run_directory, target)
        mount = f"type=bind,source={source},target={target},readonly"
        options.extend(
            [
                "--mount",
                mount,
            ]
        )

    return options


def build_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    """Build configured socket mount options for the agent container."""
    options = []
    for socket_mount in configuration.profile.socket_mounts:
        options.extend(
            [
                "--mount",
                build_socket_mount_option(socket_mount),
            ]
        )

    return options


def build_agent_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    """Build SSH/GPG agent socket mount options for the agent container."""
    options = []
    for agent_socket in get_agent_socket_forwards(configuration):
        options.extend(
            [
                "--mount",
                build_agent_socket_mount_option(agent_socket),
            ]
        )

    return options


def get_agent_socket_forwards(
    configuration: DockerConfiguration,
) -> tuple[AgentSocketForward, ...]:
    """Return SSH/GPG agent sockets forwarded into the agent container."""
    forwards = []
    if configuration.profile.ssh_agent_socket is not None:
        forwards.append(configuration.profile.ssh_agent_socket)

    if configuration.profile.gpg_agent_socket is not None:
        forwards.append(configuration.profile.gpg_agent_socket)

    return tuple(forwards)


def build_agent_socket_mount_option(agent_socket: AgentSocketForward) -> str:
    """Build a Docker mount option for a forwarded agent socket."""
    return (
        f"type=bind,source={agent_socket.source_path},target={agent_socket.target_path}"
    )


def build_denied_executable_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    """Build denied executable bind mounts for the agent container."""
    options = []
    for target_path in get_denied_executable_targets(configuration):
        source_path = (
            run_directory
            / DENIED_EXECUTABLE_SOURCE_DIRECTORY
            / build_denied_executable_stub_name(target_path)
        )
        options.extend(
            [
                "--mount",
                f"type=bind,source={source_path},target={target_path},readonly",
            ]
        )

    return options


def build_socket_mount_option(socket_mount: SocketMount) -> str:
    """Build a Docker mount option for a configured socket mount."""
    mount = (
        f"type=bind,source={socket_mount.source_path},target={socket_mount.target_path}"
    )
    if socket_mount.readonly:
        mount = f"{mount},readonly"

    return mount


def get_container_ssh_agent_socket(
    configuration: DockerConfiguration,
) -> str | None:
    """Return the SSH agent socket path inside the agent container."""
    ssh_agent_socket = configuration.profile.ssh_agent_socket
    if ssh_agent_socket is None:
        return None

    return ssh_agent_socket.target_path


def get_container_gpg_home(configuration: DockerConfiguration) -> str | None:
    """Return the GPG home path inside the agent container."""
    gpg_agent_socket = configuration.profile.gpg_agent_socket
    if gpg_agent_socket is None:
        return None

    return str(PurePosixPath(gpg_agent_socket.target_path).parent)


def build_container_script(
    run_target: SandboxRunTarget,
    remote_run_directory: str,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    create_denied_fixture: bool = True,
    verbose: bool = False,
    serialize_evidence: bool = False,
    landlock_policy_path: str | None = None,
) -> str:
    """Build the shell script executed inside the agent container."""
    if allowed_directory is None:
        allowed_directory = f"{remote_run_directory}/allowed"
    if denied_directory is None:
        denied_directory = f"{remote_run_directory}/denied"

    allowed_child_directory = f"{allowed_directory}/allowed"
    denied_child_directory = f"{denied_directory}/denied"
    arguments = build_sandbox_command_arguments(run_target, landlock_policy_path)
    if verbose:
        arguments.append("--verbose")
    if serialize_evidence:
        arguments.append("--serialize-evidence")

    lines = [
        "set -eu",
        'if [ -n "${HOME:-}" ]; then mkdir -p "$HOME"; fi',
        'if [ -n "${XDG_CACHE_HOME:-}" ]; then mkdir -p "$XDG_CACHE_HOME"; fi',
        'if [ -n "${XDG_CONFIG_HOME:-}" ]; then mkdir -p "$XDG_CONFIG_HOME"; fi',
        (
            'if [ -n "${GNUPGHOME:-}" ]; then '
            'mkdir -p "$GNUPGHOME"; '
            'chmod 700 "$GNUPGHOME"; '
            "fi"
        ),
        (
            'if [ -n "${XDG_RUNTIME_DIR:-}" ]; then '
            'mkdir -p "$XDG_RUNTIME_DIR"; '
            'chmod 700 "$XDG_RUNTIME_DIR"; '
            "fi"
        ),
        f"mkdir -p {shlex.quote(allowed_child_directory)}",
        build_write_text_command(
            f"{allowed_child_directory}/allowed.txt",
            ALLOWED_FILE_CONTENT,
        ),
        build_write_text_command(
            f"{allowed_child_directory}/.hidden",
            HIDDEN_ALLOWED_FILE_CONTENT,
        ),
        " ".join(shlex.quote(argument) for argument in arguments),
    ]
    if create_denied_fixture:
        lines.insert(-1, f"mkdir -p {shlex.quote(denied_child_directory)}")
        lines.insert(
            -1,
            build_write_text_command(
                f"{denied_child_directory}/denied.txt",
                DENIED_FILE_CONTENT,
            ),
        )
        lines.insert(
            -1,
            build_write_text_command(
                f"{denied_child_directory}/.hidden",
                HIDDEN_DENIED_FILE_CONTENT,
            ),
        )
    return "\n".join(lines)


def build_sandbox_command_arguments(
    run_target: SandboxRunTarget,
    landlock_policy_path: str | None,
) -> list[str]:
    """Build the Python command arguments executed by the agent container."""
    if landlock_policy_path is None:
        if run_target == SandboxRunTarget.TESTER:
            return [
                "python",
                "-m",
                "sandbox_tester",
                "--config",
                f"{REMOTE_OUTPUT_DIRECTORY}/config.json",
            ]

        return [
            "python",
            "-m",
            "sandbox_agent",
        ]

    return [
        "python",
        "-m",
        "docker_sandbox.landlock_runner",
        "--config",
        f"{REMOTE_OUTPUT_DIRECTORY}/config.json",
        "--policy",
        landlock_policy_path,
        "--target",
        run_target.value,
    ]


def build_write_text_command(path: str, content: str) -> str:
    """Build a shell command that writes fixed text inside the agent container."""
    quoted_content = shlex.quote(content)
    quoted_path = shlex.quote(path)
    return f"printf '%s' {quoted_content} > {quoted_path}"


def resolve_environment_variables(
    configured_variables: Mapping[str, str],
    host_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve configured agent environment variables from the host."""
    source_environment = os.environ if host_environment is None else host_environment
    environment_variables: dict[str, str] = {}

    for name, value in configured_variables.items():
        if value == LOCAL_ENVIRONMENT_VALUE:
            local_value = source_environment.get(name)
            if local_value is not None:
                environment_variables[name] = local_value
            continue

        environment_variables[name] = value

    return environment_variables


def get_local_environment_variable_names(
    configured_variables: Mapping[str, str],
) -> set[str]:
    """Return configured variable names that should resolve from the host."""
    return {
        name
        for name, value in configured_variables.items()
        if value == LOCAL_ENVIRONMENT_VALUE
    }


def build_environment_options(
    environment_variables: Mapping[str, str],
    local_environment_variable_names: Set[str],
) -> list[str]:
    """Build Docker environment options for the agent container."""
    options: list[str] = []

    for name, value in sorted(environment_variables.items()):
        if name in local_environment_variable_names:
            options.extend(["--env", name])
            continue

        options.extend(["--env", f"{name}={value}"])

    return options


def run_interactive_command(command: list[str]) -> CommandResult:
    """Run the agent container command while streaming stdout and stderr."""
    process = subprocess.Popen(
        command,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = _start_stream_thread(process.stdout, sys.stdout, stdout_chunks)
    stderr_thread = _start_stream_thread(process.stderr, sys.stderr, stderr_chunks)
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    return CommandResult(
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def get_browser_debugging_url(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    """Return the browser debugging URL exposed to the agent container."""
    if browser_debugging is None:
        return None

    return browser_debugging.debugging_url


def get_browser_executable(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    """Return the browser executable exposed to the agent container."""
    if browser_debugging is None:
        return None

    return browser_debugging.browser_executable


def get_existing_browser_profile(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    """Return the existing browser profile exposed to the agent container."""
    if browser_debugging is None:
        return None

    return browser_debugging.existing_browser_profile


def get_browser_chromium_arguments(
    browser_surface: BrowserSurfaceProfile | None,
) -> list[str]:
    """Return Chromium arguments exposed to the agent container."""
    if browser_surface is None:
        return []

    return list(browser_surface.chromium_arguments)


def get_allow_camera_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    """Return whether browser camera capture is allowed in the agent container."""
    if browser_surface is None:
        return True

    return browser_surface.allow_camera_capture


def get_allow_microphone_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    """Return whether browser microphone capture is allowed in the agent container."""
    if browser_surface is None:
        return True

    return browser_surface.allow_microphone_capture


def validate_executable_name(executable_name: str) -> None:
    """Validate a profile executable name used by the agent container."""
    if not executable_name or "/" in executable_name or "\\" in executable_name:
        raise ValueError(f"Invalid executable name: {executable_name!r}")


def validate_executable_path(executable_path: str) -> None:
    """Validate a profile executable path used by the agent container."""
    path = PurePosixPath(executable_path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError(f"Invalid executable path: {executable_path!r}")


def validate_container_directory(directory: str) -> None:
    """Validate a profile directory path used by the agent container."""
    path = PurePosixPath(directory)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError(f"Invalid container directory: {directory!r}")


def build_denied_executable_stub_name(target_path: str) -> str:
    """Build the local stub filename for a denied executable path."""
    validate_executable_path(target_path)
    return target_path.strip("/").replace("/", "__")


def build_readonly_persistence_source_directory(
    run_directory: Path,
    target: str,
) -> Path:
    """Build the local source directory for a readonly persistence mount."""
    return (
        run_directory
        / READONLY_PERSISTENCE_SOURCE_DIRECTORY
        / target.strip("/").replace("/", "__")
    )


def get_denied_executable_targets(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    """Return denied executable target paths for the agent container."""
    targets = []

    for executable_name in configuration.profile.denied_executables:
        validate_executable_name(executable_name)
        targets.append(f"/usr/bin/{executable_name}")

    for executable_path in configuration.profile.denied_executable_paths:
        validate_executable_path(executable_path)
        targets.append(executable_path)

    if configuration.profile.remove_desktop_automation_tools:
        targets = [
            target
            for target in targets
            if target not in _DESKTOP_AUTOMATION_EXECUTABLE_PATHS
        ]

    return tuple(dict.fromkeys(targets))


def _start_stream_thread(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> threading.Thread:
    thread = threading.Thread(
        target=_stream_text,
        args=(source, destination, chunks),
        daemon=True,
    )
    thread.start()
    return thread


def _stream_text(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> None:
    if source is None:
        return

    while True:
        chunk = source.read(1)
        if chunk == "":
            return

        chunks.append(chunk)
        destination.write(chunk)
        destination.flush()
