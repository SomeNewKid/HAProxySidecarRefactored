"""Tests for AI agent container image generation."""

from __future__ import annotations

from dataclasses import dataclass

from docker_sandbox.agent_container import image


@dataclass(frozen=True)
class _ImageSpec:
    capabilities: tuple[str, ...]

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


def test_package_selection_adds_openai_agents_package() -> None:
    """Verify OpenAI Agents capability selects its package."""
    spec = _ImageSpec(("openai_agents",))

    command = image.build_python_package_install_command(spec)

    assert "openai-agents==0.18.2" in command


def test_package_selection_adds_playwright_install_command() -> None:
    """Verify Playwright capability installs Python and browser dependencies."""
    spec = _ImageSpec(("playwright_chromium",))

    dockerfile = image.generate_dockerfile(spec)

    assert "playwright==1.61.0" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile


def test_package_selection_can_include_probe_dependencies() -> None:
    """Verify probe dependencies are explicit image-generation inputs."""
    spec = _ImageSpec(())

    command = image.build_python_package_install_command(
        spec,
        include_probe_dependencies=True,
    )

    assert "paramiko==5.0.0" in command
    assert "pillow==12.3.0" in command
    assert "pymysql==1.2.0" in command
