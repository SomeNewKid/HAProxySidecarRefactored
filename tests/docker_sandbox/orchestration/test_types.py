"""Tests for Docker sandbox orchestration types."""

from __future__ import annotations

from pathlib import Path

from docker_sandbox.orchestration.types import CommandResult, RunContext, SidecarPlan


def test_command_result_captures_process_output() -> None:
    """Verify command results have the same shape as captured process output."""
    result = CommandResult(
        returncode=7,
        stdout="out\n",
        stderr="err\n",
    )

    assert result.returncode == 7
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


def test_run_context_groups_run_paths_and_names() -> None:
    """Verify run context groups the names needed throughout a run."""
    context = RunContext(
        timestamp="2026-07-20-16-00-00",
        run_id="run-2026-07-20-16-00-00",
        run_directory=Path(".docker_sandbox/runs/run-2026-07-20-16-00-00"),
        container_name="sandbox-agent-run-2026-07-20-16-00-00",
        remote_run_directory="/sandbox-work/run-2026-07-20-16-00-00",
        allowed_directory="/sandbox-work/run-2026-07-20-16-00-00/allowed",
        denied_directory="/sandbox-denied",
        network_name="sandbox-agent-net-2026-07-20-16-00-00",
        gateway_container_name="sandbox-agent-gateway-2026-07-20-16-00-00",
    )

    assert context.network_name == "sandbox-agent-net-2026-07-20-16-00-00"
    assert context.gateway_container_name == (
        "sandbox-agent-gateway-2026-07-20-16-00-00"
    )


def test_sidecar_plan_groups_commands_and_artifacts() -> None:
    """Verify sidecar plans can describe start, readiness, cleanup, and logs."""
    plan = SidecarPlan(
        name="example",
        container_name="example-sidecar-1",
        start_commands=(("docker", "run", "example"),),
        cleanup_commands=(("docker", "rm", "--force", "example-sidecar-1"),),
        readiness_results_file_name="example-readiness-results.json",
        log_file_names=("example-stdout.txt", "example-stderr.txt"),
    )

    assert plan.name == "example"
    assert plan.start_commands == (("docker", "run", "example"),)
    assert plan.cleanup_commands == (("docker", "rm", "--force", "example-sidecar-1"),)
    assert plan.readiness_results_file_name == "example-readiness-results.json"
    assert plan.log_file_names == ("example-stdout.txt", "example-stderr.txt")
