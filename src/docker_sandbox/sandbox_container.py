"""Run Sandbox Agent inside disposable Docker containers."""

from __future__ import annotations

import datetime as dt

from .agent_container import fixtures, policy_artifacts
from .agent_container import run as agent_run
from .models import (
    DockerConfiguration,
    DockerRunResult,
)
from .orchestration import environment, results, run_artifacts, sidecar_lifecycle


def run_sandbox_container(
    configuration: DockerConfiguration,
    verbose: bool = False,
    serialize_evidence: bool = False,
) -> DockerRunResult:
    """Run Sandbox Agent in a disposable Docker container."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    run_context = environment.create_run_context(configuration, timestamp)
    run_context.run_directory.mkdir(parents=True, exist_ok=True)
    fixtures.prepare(configuration, run_context.run_directory)
    policy_artifacts.write(configuration, run_context.run_directory)
    run_artifacts.write_initial(
        configuration,
        run_context,
    )
    configured_environment_variables = dict(configuration.environment_variables)
    environment_variables = agent_run.resolve_environment_variables(
        configured_environment_variables,
    )
    sidecar_start_result = sidecar_lifecycle.start_all(configuration, run_context)
    command = agent_run.build_docker_run_command(
        configuration=configuration,
        run_directory=run_context.run_directory,
        container_name=run_context.container_name,
        network_name=run_context.network_name,
        remote_run_directory=run_context.remote_run_directory,
        allowed_directory=run_context.allowed_directory,
        denied_directory=run_context.denied_directory,
        environment_variables=environment_variables,
        gateway_ip_address=sidecar_start_result.gateway_ip_address,
        local_environment_variable_names=configuration.local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
    )
    completed = agent_run.run_interactive_command(command)
    sidecar_lifecycle.write_logs(configuration, run_context)
    fixtures.clean(configuration, run_context.run_directory)

    return results.build_docker_run_result(
        configuration=configuration,
        run_context=run_context,
        command=command,
        completed=completed,
        sidecar_start_result=sidecar_start_result,
    )
