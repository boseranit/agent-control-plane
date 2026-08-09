from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.command_runner import (
    CommandResult,
    CommandSpec,
    run_command,
    write_command_metrics,
)
from agent_control_plane.control_plane.systemd_scope import ResourceLimitExceeded
from agent_control_plane.research_experiment_controller.artifacts import (
    CommandDeclaration,
    command_declaration_record,
)
from agent_control_plane.research_experiment_controller.command_environment import (
    research_command_env,
)


@dataclass(frozen=True)
class VerificationRepairRequest:
    attempt: int
    cwd: Path
    run_dir: Path
    failed_results: list[dict[str, Any]]


RepairCallback = Callable[[VerificationRepairRequest], None]


def run_verification_commands(
    *,
    verification_commands: Sequence[CommandDeclaration | dict[str, Any]],
    cwd: str | Path,
    run_dir: str | Path,
    data_root: str | Path | None = None,
    experiment_data_root: str | Path | None = None,
    repo_root: str | Path | None = None,
    timeout_seconds: float,
    max_repairs: int,
    maximum_memory_bytes: int | None = None,
    repair_callback: RepairCallback | None = None,
) -> dict[str, Any]:
    resolved_cwd = Path(cwd).resolve()
    resolved_run_dir = Path(run_dir)
    all_results: list[CommandResult] = []
    attempt = 0
    repairs = 0

    while True:
        attempt_results = _run_attempt(
            verification_commands=verification_commands,
            cwd=resolved_cwd,
            run_dir=resolved_run_dir,
            env=research_command_env(
                data_root=data_root,
                experiment_data_root=experiment_data_root,
                run_dir=resolved_run_dir,
                repo_root=repo_root,
            ),
            timeout_seconds=timeout_seconds,
            maximum_memory_bytes=maximum_memory_bytes,
            attempt=attempt,
        )
        all_results.extend(attempt_results)
        write_command_metrics(resolved_run_dir / "command_metrics.json", all_results)
        memory_failure = next(
            (result for result in attempt_results if result.memory_limit_exceeded),
            None,
        )
        if memory_failure is not None:
            raise ResourceLimitExceeded(
                f"Verification command {memory_failure.name!r} exceeded the hard "
                f"memory limit of {memory_failure.maximum_memory_bytes} bytes."
            )
        if all(result.status == "passed" for result in attempt_results):
            return {
                "status": "passed",
                "attempts": attempt + 1,
                "repairs": repairs,
                "command_results": [result.to_record() for result in all_results],
            }
        if attempt >= max_repairs or repair_callback is None:
            return {
                "status": "failed",
                "outcome": "run_failed",
                "outcome_reason": _failure_reason(repairs),
                "failed_stage": "verification",
                "failure_classification": "verification_command_failed",
                "summary": _failure_reason(repairs),
                "attempts": attempt + 1,
                "repairs": repairs,
                "command_results": [result.to_record() for result in all_results],
            }

        failed_results = [
            result.to_record()
            for result in attempt_results
            if result.status != "passed"
        ]
        repair_callback(
            VerificationRepairRequest(
                attempt=attempt + 1,
                cwd=resolved_cwd,
                run_dir=resolved_run_dir,
                failed_results=failed_results,
            )
        )
        repairs += 1
        attempt += 1


def _run_attempt(
    *,
    verification_commands: Sequence[CommandDeclaration | dict[str, Any]],
    cwd: Path,
    run_dir: Path,
    env: dict[str, str],
    timeout_seconds: float,
    maximum_memory_bytes: int | None,
    attempt: int,
) -> list[CommandResult]:
    return [
        run_command(
            _command_spec(
                command,
                index,
                timeout_seconds,
                maximum_memory_bytes,
            ),
            cwd=cwd,
            stdout_path=_log_path(run_dir, attempt, command, index, "stdout"),
            stderr_path=_log_path(run_dir, attempt, command, index, "stderr"),
            env=env,
        )
        for index, command in enumerate(verification_commands, start=1)
    ]


def _command_spec(
    command: CommandDeclaration | dict[str, Any],
    index: int,
    default_timeout_seconds: float,
    maximum_memory_bytes: int | None,
) -> CommandSpec:
    data = command_declaration_record(command)
    return CommandSpec(
        name=str(data.get("name") or f"verification-{index}"),
        argv=data["argv"],
        timeout_seconds=float(data.get("timeout_seconds") or default_timeout_seconds),
        maximum_memory_bytes=maximum_memory_bytes,
    )


def _log_path(
    run_dir: Path,
    attempt: int,
    command: CommandDeclaration | dict[str, Any],
    index: int,
    stream: str,
) -> Path:
    data = command_declaration_record(command)
    name = _safe_name(str(data.get("name") or f"verification-{index}"))
    return (
        run_dir
        / "logs"
        / "verification"
        / f"attempt-{attempt}"
        / f"{name}.{stream}.log"
    )


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return safe or "verification"


def _failure_reason(repairs: int) -> str:
    return f"Verification commands failed after {repairs} repairs."
