from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from agent_control_plane.control_plane.command_runner import (
    CommandSpec,
    run_command,
    write_command_metrics,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    CommandDeclaration,
    DataAudit,
)
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_data_audit_failure,
)


@dataclass(frozen=True)
class PrerequisiteAuditRequest:
    data_root: str | Path
    prerequisite_commands: Sequence[CommandDeclaration | dict[str, Any]]
    data_audit_commands: Sequence[CommandDeclaration | dict[str, Any]]
    cwd: str | Path
    run_dir: str | Path
    timeout_seconds: float


def run_data_audit_phase(request: PrerequisiteAuditRequest) -> dict[str, Any]:
    run_dir = Path(request.run_dir)
    data_root = Path(request.data_root).expanduser()
    command_results = []

    if not data_root.exists():
        write_command_metrics(run_dir / "command_metrics.json", command_results)
        return _failed_result("data_root_missing", command_results)

    for phase, commands in (
        ("prerequisite", request.prerequisite_commands),
        ("data_audit", request.data_audit_commands),
    ):
        for index, command in enumerate(commands, start=1):
            command_spec = _command_spec(command, phase, index, request.timeout_seconds)
            result = run_command(
                command_spec,
                cwd=request.cwd,
                stdout_path=run_dir / "commands" / f"{phase}_{index}_stdout.log",
                stderr_path=run_dir / "commands" / f"{phase}_{index}_stderr.log",
                env={
                    "RESEARCH_DATA_ROOT": str(data_root),
                    "RESEARCH_RUN_DIR": str(run_dir),
                    "RESEARCH_REPO_ROOT": str(Path(request.cwd).resolve()),
                },
            )
            command_results.append(result)

    write_command_metrics(run_dir / "command_metrics.json", command_results)
    if any(result.status != "passed" for result in command_results):
        return _failed_result("prerequisite_command_failed", command_results)

    data_audit = DataAudit(
        passed=True,
        outcome=None,
        outcome_reason="Data/prerequisite audit passed.",
        failed_stage=None,
        failure_classification=None,
        command_results=[result.to_record() for result in command_results],
    )
    return {
        "status": "data_audit_passed",
        "data_audit": data_audit.model_dump(mode="json"),
    }


def _failed_result(
    failure_classification: str,
    command_results: Sequence[Any],
) -> dict[str, Any]:
    summary = classify_data_audit_failure(failure_classification)
    data_audit = DataAudit(
        passed=False,
        outcome=summary.outcome,
        outcome_reason=summary.outcome_reason,
        failed_stage=summary.failed_stage,
        failure_classification=summary.failure_classification,
        command_results=[
            result.to_record() if hasattr(result, "to_record") else result
            for result in command_results
        ],
    )
    return {
        "status": "experiment_completed",
        "data_audit": data_audit.model_dump(mode="json"),
        **summary.model_dump(mode="json"),
    }


def _command_spec(
    command: CommandDeclaration | dict[str, Any],
    phase: str,
    index: int,
    default_timeout_seconds: float,
) -> CommandSpec:
    data = (
        command.model_dump(mode="json")
        if isinstance(command, CommandDeclaration)
        else command
    )
    return CommandSpec(
        name=str(data.get("name") or f"{phase}-{index}"),
        argv=data["argv"],
        timeout_seconds=float(data.get("timeout_seconds") or default_timeout_seconds),
    )
