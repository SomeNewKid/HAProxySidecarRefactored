"""Squid gateway sidecar orchestration helpers."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from pathlib import Path

from docker_sandbox.models import DockerConfiguration, NetworkGatewayProfile
from docker_sandbox.orchestration.artifacts import (
    command_result_data,
    write_docker_log_artifacts,
    write_json_artifact,
)
from docker_sandbox.orchestration.docker import (
    DOCKER_EXECUTABLE,
    capture_docker_logs,
    run_captured_command,
)
from docker_sandbox.orchestration.types import CommandResult

_GATEWAY_CONTAINER_NAME_PREFIX = "sandbox-agent-gateway"
_SQUID_CONFIGURATION_FILE_NAME = "squid.conf"
_GATEWAY_START_RESULTS_FILE_NAME = "gateway-start-results.json"
_GATEWAY_LOG_FILE_NAME = "gateway-logs.json"
_GATEWAY_ALIAS = "egress-gateway"
_SQUID_CONFIGURATION_PATH = "/etc/squid/squid.conf"


def build_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    """Build the Squid gateway container name for a sandbox run."""
    if configuration.profile.network_gateway is None:
        return None

    return f"{_GATEWAY_CONTAINER_NAME_PREFIX}-{timestamp}"


def write_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
    config_data: Mapping[str, object],
) -> None:
    """Write the Squid configuration artifact for the sandbox run."""
    gateway = configuration.profile.network_gateway
    if gateway is None:
        return

    allowed_domains = build_allowed_domains(gateway.allowed_domains, config_data)
    allowed_ip_addresses = _build_allowed_ip_addresses(gateway.allowed_ip_addresses)
    squid_config = _build_configuration_text(
        allowed_domains,
        gateway.proxy_port,
        allowed_ip_addresses,
    )
    squid_config_path = run_directory / _SQUID_CONFIGURATION_FILE_NAME
    squid_config_path.write_text(squid_config, encoding="utf-8")


def build_allowed_domains(
    configured_domains: tuple[str, ...],
    config_data: Mapping[str, object],
) -> tuple[str, ...]:
    """Build the normalized Squid domain allowlist."""
    _ = config_data
    domains = list(configured_domains)
    normalized_domains = tuple(
        dict.fromkeys(_normalize_domain(domain) for domain in domains)
    )
    return _remove_redundant_domain_suffixes(normalized_domains)


def start_gateway(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    gateway_container_name: str | None,
) -> tuple[list[list[str]] | None, str | None]:
    """Start Squid and fail if its readiness check does not pass."""
    gateway = configuration.profile.network_gateway
    if gateway is None:
        return None, None

    if network_name is None or gateway_container_name is None:
        raise RuntimeError(
            "Network gateway profile requires network and container names."
        )

    commands = build_start_commands(
        gateway.image_name,
        gateway_container_name,
        network_name,
        run_directory / _SQUID_CONFIGURATION_FILE_NAME,
    )
    results = []
    for command in commands:
        completed = run_captured_command(command)
        results.append(_build_command_result(command, completed))

    gateway_ip_address = _inspect_ip_address(gateway_container_name, network_name)
    results.append(
        {
            "command": build_inspect_command(gateway_container_name, network_name),
            "gateway_ip_address": gateway_ip_address,
        }
    )
    _write_start_results(run_directory, results)
    _raise_for_readiness_failure(results[-2])

    return commands, gateway_ip_address


def write_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    gateway_container_name: str | None,
) -> None:
    """Write Squid Docker logs for the sandbox run."""
    if configuration.profile.network_gateway is None:
        return

    if gateway_container_name is None:
        return

    completed = capture_docker_logs(gateway_container_name, DOCKER_EXECUTABLE)
    write_docker_log_artifacts(
        run_directory=run_directory,
        log_result=completed,
        log_file_name=_GATEWAY_LOG_FILE_NAME,
    )


def build_start_commands(
    gateway_image_name: str,
    gateway_container_name: str,
    network_name: str,
    squid_config_path: Path,
) -> list[list[str]]:
    """Build the commands that create the internal network and start Squid."""
    return [
        [
            DOCKER_EXECUTABLE,
            "network",
            "create",
            "--internal",
            network_name,
        ],
        [
            DOCKER_EXECUTABLE,
            "run",
            "--detach",
            "--name",
            gateway_container_name,
            "--network",
            "bridge",
            "--mount",
            (
                f"type=bind,source={squid_config_path},"
                f"target={_SQUID_CONFIGURATION_PATH},readonly"
            ),
            gateway_image_name,
        ],
        [
            DOCKER_EXECUTABLE,
            "network",
            "connect",
            "--alias",
            _GATEWAY_ALIAS,
            network_name,
            gateway_container_name,
        ],
        [
            DOCKER_EXECUTABLE,
            "exec",
            gateway_container_name,
            "/bin/sh",
            "-c",
            (
                "for attempt in 1 2 3 4 5; do "
                f"squid -k check -f {_SQUID_CONFIGURATION_PATH} >/dev/null 2>&1 "
                "&& exit 0; "
                "sleep 1; "
                "done; "
                f"squid -k check -f {_SQUID_CONFIGURATION_PATH}"
            ),
        ],
    ]


def build_cleanup_commands(
    configuration: DockerConfiguration,
    network_name: str | None,
    gateway_container_name: str | None,
) -> list[list[str]] | None:
    """Build cleanup commands for the Squid gateway and network."""
    if configuration.profile.network_gateway is None:
        return None

    if network_name is None or gateway_container_name is None:
        return None

    return [
        [DOCKER_EXECUTABLE, "rm", "--force", gateway_container_name],
        [DOCKER_EXECUTABLE, "network", "rm", network_name],
    ]


def apply_agent_environment(
    container_environment: dict[str, str],
    gateway: NetworkGatewayProfile,
    gateway_ip_address: str | None = None,
    extra_no_proxy_hosts: tuple[str, ...] = (),
) -> None:
    """Add Squid proxy settings to an agent container environment."""
    proxy_host = gateway_ip_address or gateway.proxy_host
    proxy_url = f"http://{proxy_host}:{gateway.proxy_port}"
    no_proxy_hosts = (
        "localhost",
        "127.0.0.1",
        *gateway.no_proxy_hosts,
        *extra_no_proxy_hosts,
    )
    no_proxy = ",".join(dict.fromkeys(no_proxy_hosts))
    container_environment["HTTP_PROXY"] = proxy_url
    container_environment["HTTPS_PROXY"] = proxy_url
    container_environment["NO_PROXY"] = no_proxy
    container_environment["http_proxy"] = proxy_url
    container_environment["https_proxy"] = proxy_url
    container_environment["no_proxy"] = no_proxy


def build_inspect_command(
    gateway_container_name: str,
    network_name: str,
) -> list[str]:
    """Build the command that reads the gateway IP address."""
    template = "{{(index (index .NetworkSettings.Networks "
    template += f"{json.dumps(network_name)}"
    template += ') "IPAddress")}}'
    return [
        DOCKER_EXECUTABLE,
        "inspect",
        "--format",
        template,
        gateway_container_name,
    ]


def _normalize_domain(domain: str) -> str:
    stripped_domain = domain.strip().lower()
    if stripped_domain.startswith("*."):
        return f".{stripped_domain[2:]}"

    return stripped_domain


def _remove_redundant_domain_suffixes(
    domains: tuple[str, ...],
) -> tuple[str, ...]:
    exact_domains = {domain for domain in domains if not domain.startswith(".")}
    filtered_domains = []
    for domain in domains:
        if domain.startswith(".") and domain[1:] in exact_domains:
            continue

        filtered_domains.append(domain)

    return tuple(filtered_domains)


def _build_allowed_ip_addresses(
    configured_ip_addresses: tuple[str, ...],
) -> tuple[str, ...]:
    ip_addresses = []
    for ip_address in configured_ip_addresses:
        normalized_ip_address = _normalize_ip_address(ip_address)
        ip_addresses.append(normalized_ip_address)

    return tuple(dict.fromkeys(ip_addresses))


def _normalize_ip_address(ip_address: str) -> str:
    normalized_ip_address = ip_address.strip().strip("[]")
    network = ipaddress.ip_network(normalized_ip_address, strict=False)
    return str(network)


def _build_configuration_text(
    allowed_domains: tuple[str, ...],
    proxy_port: int,
    allowed_ip_addresses: tuple[str, ...] = (),
) -> str:
    domains = " ".join(allowed_domains)
    lines = [
        f"http_port {proxy_port}",
        "acl SSL_ports port 443",
        "acl Safe_ports port 80",
        "acl Safe_ports port 443",
        "acl CONNECT method CONNECT",
        f"acl allowed_sites dstdomain {domains}",
        r"acl ipv4_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://[0-9]+(\.[0-9]+){3}([:/]|$)",
        r"acl ipv4_literal_connect url_regex -i ^[0-9]+(\.[0-9]+){3}:",
        r"acl ipv6_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://\[[0-9a-f:.]+\]([:/]|$)",
        r"acl ipv6_literal_connect url_regex -i ^\[[0-9a-f:.]+\]:",
        "http_access deny !Safe_ports",
        "http_access deny CONNECT !SSL_ports",
    ]
    if allowed_ip_addresses:
        ip_addresses = " ".join(allowed_ip_addresses)
        lines.extend(
            [
                f"acl allowed_ip_addresses dst {ip_addresses}",
                "http_access allow allowed_ip_addresses",
            ]
        )

    lines.extend(
        [
            "http_access deny ipv4_literal_url",
            "http_access deny ipv4_literal_connect",
            "http_access deny ipv6_literal_url",
            "http_access deny ipv6_literal_connect",
            "http_access allow allowed_sites",
            "http_access deny all",
            "access_log none",
            "cache_log /tmp/squid-cache.log",
            "",
        ]
    )
    return "\n".join(lines)


def _raise_for_readiness_failure(result: Mapping[str, object]) -> None:
    returncode = result.get("returncode")
    if returncode == 0:
        return

    stderr = result.get("stderr")
    if not isinstance(stderr, str) or not stderr.strip():
        stderr = "Squid readiness check did not return a successful response."

    raise RuntimeError(f"Squid gateway readiness check failed: {stderr.strip()}")


def _build_command_result(
    command: list[str],
    completed: CommandResult,
) -> dict[str, object]:
    return command_result_data(command, completed)


def _inspect_ip_address(
    gateway_container_name: str,
    network_name: str,
) -> str | None:
    command = build_inspect_command(gateway_container_name, network_name)
    completed = run_captured_command(command)
    if completed.returncode != 0:
        return None

    ip_address = completed.stdout.strip()
    if not ip_address or ip_address == "<no value>":
        return None

    return ip_address


def _write_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _GATEWAY_START_RESULTS_FILE_NAME
    write_json_artifact(results_path, results)
