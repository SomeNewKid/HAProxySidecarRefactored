"""AI agent container image generation helpers."""

from __future__ import annotations

from typing import Protocol

from docker_sandbox import capabilities

_MCP_PACKAGE = "mcp==1.28.1"
_OPENAI_PACKAGE = "openai==2.45.0"
_OPENAI_AGENTS_PACKAGE = "openai-agents==0.18.2"
_CLAUDE_AGENT_SDK_PACKAGE = "claude-agent-sdk==0.2.120"
_ANTHROPIC_PACKAGE = "anthropic==0.116.0"
_BEEAI_PACKAGE = "beeai-framework==0.1.81"
_GOOGLE_ADK_PACKAGE = "google-adk==2.5.0"
_LANGCHAIN_PACKAGE = "langchain==1.3.14"
_LANGCHAIN_OPENAI_PACKAGE = "langchain-openai==1.3.5"
_LANGGRAPH_PACKAGE = "langgraph==1.2.9"
_MICROSOFT_AGENT_PACKAGE = "agent-framework==1.11.0"
_CREWAI_PACKAGE = "crewai==1.15.3"
_LITELLM_PROXY_PACKAGE = "'litellm[proxy]==1.92.0'"
_PLAYWRIGHT_PACKAGE = "playwright==1.61.0"
_PROBE_PACKAGES = (
    "paramiko==5.0.0",
    "pillow==12.3.0",
    "pymysql==1.2.0",
)
_PLAYWRIGHT_BROWSERS_PATH = "/ms-playwright"


class _CapabilitySpec(Protocol):
    def has_capability(self, capability: str) -> bool:
        """Return whether a capability is declared."""
        ...


def generate_dockerfile(
    spec: _CapabilitySpec,
    include_probe_dependencies: bool = False,
) -> str:
    """Generate the Dockerfile needed by the sandbox spec."""
    package_install_command = build_python_package_install_command(
        spec,
        include_probe_dependencies=include_probe_dependencies,
    )
    return f"""FROM python:3.12-slim

WORKDIR /opt/sandbox-agent

RUN useradd --create-home --shell /usr/sbin/nologin sandbox

COPY src/docker_sandbox/dockerfile/runtime_sitecustomize.py \\
    /tmp/runtime_sitecustomize.py
COPY src/docker_sandbox/dockerfile/remove_python_packaging.py \\
    /tmp/remove_python_packaging.py
ENV PLAYWRIGHT_BROWSERS_PATH={_PLAYWRIGHT_BROWSERS_PATH}
{package_install_command}

RUN rm -f \\
        /usr/local/bin/pip \\
        /usr/local/bin/pip3 \\
        /usr/local/bin/pip3.* \\
        /usr/local/bin/wheel \\
        /usr/bin/apt \\
        /usr/bin/apt-get \\
        /usr/bin/bash \\
        /usr/bin/busctl \\
        /usr/bin/dbus-send \\
        /usr/bin/dpkg \\
        /usr/bin/dpkg-query \\
        /usr/bin/findmnt \\
        /usr/bin/git \\
        /usr/bin/gpg \\
        /usr/bin/gpg-connect-agent \\
        /usr/bin/gpgconf \\
        /usr/bin/journalctl \\
        /usr/bin/loginctl \\
        /usr/bin/mount \\
        /usr/bin/nice \\
        /usr/bin/nohup \\
        /usr/bin/nsenter \\
        /usr/bin/perl \\
        /usr/bin/renice \\
        /usr/bin/scp \\
        /usr/bin/sftp \\
        /usr/bin/setsid \\
        /usr/bin/ssh \\
        /usr/bin/ssh-add \\
        /usr/bin/su \\
        /usr/bin/systemd-run \\
        /usr/bin/systemctl \\
        /usr/bin/umount \\
        /usr/bin/unshare \\
        /usr/sbin/service \\
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

RUN python /tmp/remove_python_packaging.py \\
    && rm -f \\
        /usr/local/bin/pip \\
        /usr/local/bin/pip3 \\
        /usr/local/bin/pip3.* \\
        /usr/local/bin/wheel \\
        /usr/bin/pip \\
        /usr/bin/pip3 \\
        /usr/bin/pip3.* \\
        /usr/bin/wheel

RUN rm -f \\
        /usr/bin/gdbus \\
        /usr/bin/qdbus \\
        /usr/bin/wmctrl \\
        /usr/bin/xdotool \\
    && rm -rf \\
        /var/cache/apt \\
        /var/lib/apt \\
        /var/lib/dpkg \\
        /var/log/apt
"""


def build_python_package_install_command(
    spec: _CapabilitySpec,
    include_probe_dependencies: bool = False,
) -> str:
    """Build the Python package installation command for an agent image."""
    packages = []
    if spec.has_capability(capabilities.OPENAI):
        packages.append(_OPENAI_PACKAGE)
    if spec.has_capability(capabilities.OPENAI_AGENTS):
        packages.append(_OPENAI_AGENTS_PACKAGE)
    if spec.has_capability(capabilities.MCP_CLIENT):
        packages.append(_MCP_PACKAGE)
    if spec.has_capability(capabilities.ANTHROPIC_CLAUDE):
        packages.append(_CLAUDE_AGENT_SDK_PACKAGE)
    if spec.has_capability(capabilities.ANTHROPIC_PYTHON):
        packages.append(_ANTHROPIC_PACKAGE)
    if spec.has_capability(capabilities.BEEAI):
        packages.append(_BEEAI_PACKAGE)
        packages.append(_LITELLM_PROXY_PACKAGE)
    if spec.has_capability(capabilities.GOOGLE_ADK):
        packages.append(_GOOGLE_ADK_PACKAGE)
        packages.append(_LITELLM_PROXY_PACKAGE)
    if spec.has_capability(capabilities.LANGCHAIN):
        packages.append(_LANGCHAIN_PACKAGE)
        packages.append(_LANGCHAIN_OPENAI_PACKAGE)
    if spec.has_capability(capabilities.LANGGRAPH):
        packages.append(_LANGGRAPH_PACKAGE)
        packages.append(_LANGCHAIN_OPENAI_PACKAGE)
    if spec.has_capability(capabilities.MICROSOFT_AGENT):
        packages.append(_MICROSOFT_AGENT_PACKAGE)
    if spec.has_capability(capabilities.CREWAI):
        packages.append(_CREWAI_PACKAGE)
    if spec.has_capability(capabilities.OTTO_AGENT):
        packages.append(_OPENAI_PACKAGE)
    if spec.has_capability(capabilities.PLAYWRIGHT_CHROMIUM):
        packages.append(_PLAYWRIGHT_PACKAGE)
    if include_probe_dependencies:
        packages.extend(_PROBE_PACKAGES)

    if not packages:
        return ""

    package_arguments = " ".join(packages)
    install_command = f"\nRUN python -m pip install --no-cache-dir {package_arguments}"
    if spec.has_capability(capabilities.PLAYWRIGHT_CHROMIUM):
        install_command += (
            " \\\n    && python -m playwright install --with-deps chromium"
        )

    return f"{install_command}\n"
