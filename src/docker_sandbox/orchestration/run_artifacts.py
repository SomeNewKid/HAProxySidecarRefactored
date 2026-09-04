"""Initial run artifact writers for Docker sandbox orchestration."""

from __future__ import annotations

from docker_sandbox.agent_container import run as agent_run
from docker_sandbox.models import DockerConfiguration
from docker_sandbox.orchestration import wiring
from docker_sandbox.orchestration.artifacts import write_json_artifact
from docker_sandbox.orchestration.types import RunContext
from docker_sandbox.sidecars import haproxy, mcp, squid_gateway

_CONFIG_FILE_NAME = "config.json"
_DOCKERFILE_ARTIFACT_FILE_NAME = "Dockerfile"
_SANDBOX_SPEC_ARTIFACT_FILE_NAME = "sandbox-spec.json"
_RESOLVED_PROFILE_ARTIFACT_FILE_NAME = "resolved-profile.json"


def write_initial(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> dict[str, object]:
    """Write initial run artifacts and return agent container config data."""
    _write_configuration_artifacts(configuration, run_context)
    config_data = _build_agent_config_data(configuration, run_context)
    _write_sidecar_configuration_artifacts(configuration, run_context, config_data)
    write_json_artifact(run_context.run_directory / _CONFIG_FILE_NAME, config_data)
    return config_data


def _write_configuration_artifacts(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> None:
    if configuration.generated_dockerfile is not None:
        dockerfile_text = configuration.generated_dockerfile.rstrip()
        dockerfile_path = run_context.run_directory / _DOCKERFILE_ARTIFACT_FILE_NAME
        dockerfile_path.write_text(
            f"{dockerfile_text}\n",
            encoding="utf-8",
        )

    if configuration.resolved_spec is not None:
        write_json_artifact(
            run_context.run_directory / _SANDBOX_SPEC_ARTIFACT_FILE_NAME,
            configuration.resolved_spec,
        )

    write_json_artifact(
        run_context.run_directory / _RESOLVED_PROFILE_ARTIFACT_FILE_NAME,
        configuration.profile,
    )


def _build_agent_config_data(
    configuration: DockerConfiguration,
    run_context: RunContext,
) -> dict[str, object]:
    return agent_run.build_config_data(
        run_context.remote_run_directory,
        run_context.allowed_directory,
        run_context.denied_directory,
        configuration.guest_user,
        agent_run.get_container_ssh_agent_socket(configuration),
        configuration.profile.browser_debugging,
        configuration.profile.browser_surface,
    )


def _write_sidecar_configuration_artifacts(
    configuration: DockerConfiguration,
    run_context: RunContext,
    config_data: dict[str, object],
) -> None:
    if wiring.should_start_squid_gateway(configuration):
        squid_gateway.write_configuration(
            configuration,
            run_context.run_directory,
            config_data,
        )

    if wiring.should_start_mcp_sidecar(configuration):
        mcp.write_exposure(configuration, run_context.run_directory)

    if wiring.should_start_haproxy_sidecar(configuration):
        haproxy.write_configuration(configuration, run_context.run_directory)
