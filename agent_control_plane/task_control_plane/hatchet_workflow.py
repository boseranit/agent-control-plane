from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from hatchet_sdk import DurableContext, Hatchet
from pydantic import BaseModel

from agent_control_plane.task_control_plane.agent_runtime import AgentRuntime
from agent_control_plane.task_control_plane.controller import (
    TaskRunError,
    _active_task_state,
    _check_loaded_task_run_state,
    _confirm_approved_plan,
    _load_existing_task_run,
    _open_approved_plan_in_editor,
    _read_json,
    _record_plan_approval,
    _require_clean_state_target_repository,
    _require_resume_can_continue_from_phase,
    _resume_after_dirty_before_next_task,
    _task_artifacts,
    _write_json,
    commit_active_task_and_advance,
    plan_active_task,
    run_active_task_failed_test_repair,
    run_active_task_implementer,
    run_active_task_review_rejection_repair,
    run_active_task_reviewer,
    run_active_task_tests,
)

PLAN_APPROVAL_EVENT_KEY = "task-control-plan-approval"


class TaskControlRunInput(BaseModel):
    run_id: str
    runtime_root: str = "runs"


@dataclass(frozen=True)
class TaskControlPhaseInput:
    run_id: str
    task_state_path: str
    phase: str
    runtime_root: str = "runs"


class DurableUsageLimitWait(RuntimeError):
    def __init__(self, sleep_seconds: float) -> None:
        super().__init__(f"usage-limit wait: {sleep_seconds}")
        self.sleep_seconds = sleep_seconds


class DurablePlanApprovalWait(RuntimeError):
    def __init__(self, approved_plan_path: Path) -> None:
        super().__init__(f"plan approval wait: {approved_plan_path}")
        self.approved_plan_path = approved_plan_path


PhaseRunner = Callable[[TaskControlPhaseInput], dict[str, Any]]


def build_hatchet_workflows(hatchet: Hatchet) -> list[Any]:
    @hatchet.durable_task(
        name="task-control-run",
        input_validator=TaskControlRunInput,
        execution_timeout=timedelta(days=30),
    )
    async def task_control_run(
        input: TaskControlRunInput, ctx: DurableContext
    ) -> dict[str, Any]:
        return await run_task_control_loop(input, ctx)

    return [task_control_run]


async def run_task_control_loop(
    input: TaskControlRunInput,
    ctx: DurableContext,
    *,
    phase_runner: PhaseRunner | None = None,
) -> dict[str, Any]:
    task_run = _load_existing_task_run(input.run_id, input.runtime_root)
    run_phase = phase_runner or run_current_phase_once

    while True:
        state = _read_json(task_run.task_state_path)
        _check_loaded_task_run_state(task_run, state)

        terminal_result = terminal_result_for_state(state)
        if terminal_result is not None:
            return terminal_result

        if state.get("phase") == "plan_pending_approval":
            event_payload = await ctx.aio_wait_for_event(
                PLAN_APPROVAL_EVENT_KEY,
                scope=input.run_id,
                lookback_window=timedelta(days=30),
                label="plan approval",
            )
            apply_plan_approval_event(task_run.task_state_path, event_payload)
            continue

        phase_input = TaskControlPhaseInput(
            run_id=input.run_id,
            runtime_root=input.runtime_root,
            task_state_path=str(task_run.task_state_path),
            phase=str(state.get("phase")),
        )
        phase_result = run_phase(phase_input)
        status = phase_result.get("status")

        if status == "usage_limit_wait":
            await ctx.aio_sleep_for(
                timedelta(seconds=float(phase_result["sleep_seconds"])),
                label="usage limit",
            )
            continue
        if status in {"phase_completed", "skipped", "plan_approval_wait", "advanced"}:
            continue
        if status in {"completed", "failed", "stopped"}:
            return phase_result

        continue


def run_current_phase_once(
    input: TaskControlPhaseInput,
    *,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    task_state_path = Path(input.task_state_path)
    state = _read_json(task_state_path)
    terminal_result = terminal_result_for_state(state)
    if terminal_result is not None:
        return terminal_result

    current_phase = state.get("phase")
    if current_phase != input.phase:
        return {
            "status": "skipped",
            "run_id": input.run_id,
            "requested_phase": input.phase,
            "current_phase": current_phase,
        }

    if current_phase == "target_repository_dirty_before_next_task":
        _resume_after_dirty_before_next_task(task_state_path)
        return {"status": "phase_completed", "phase": current_phase}

    _require_resume_can_continue_from_phase(state)
    runtime = agent_runtime or AgentRuntime()

    try:
        result = _run_current_phase_with_runtime(
            task_state_path, runtime, current_phase
        )
    except DurableUsageLimitWait as exc:
        return {
            "status": "usage_limit_wait",
            "run_id": input.run_id,
            "phase": current_phase,
            "sleep_seconds": exc.sleep_seconds,
        }
    except DurablePlanApprovalWait as exc:
        return {
            "status": "plan_approval_wait",
            "run_id": input.run_id,
            "phase": current_phase,
            "approved_plan_path": str(exc.approved_plan_path),
        }

    if isinstance(result, dict) and result.get("status") in {
        "completed",
        "failed",
        "advanced",
    }:
        return result
    return {"status": "phase_completed", "phase": current_phase}


def bridge_plan_approval_if_pending(
    run_id: str,
    *,
    runtime_root: str | Path = "runs",
    approved_plan_editor: Callable[[Path], None] | None = None,
    plan_approval_confirmer: Callable[[Path], bool] | None = None,
    event_sender: Callable[[str, str, str | None], None] | None = None,
) -> dict[str, Any] | None:
    task_run = _load_existing_task_run(run_id, runtime_root)
    state = _read_json(task_run.task_state_path)
    if state.get("phase") != "plan_pending_approval":
        return None

    active_task_state = _active_task_state(state)
    approved_plan_path = Path(_task_artifacts(active_task_state)["approved_plan"])
    (approved_plan_editor or _open_approved_plan_in_editor)(approved_plan_path)
    approved = (plan_approval_confirmer or _confirm_approved_plan)(approved_plan_path)
    status = "approved" if approved else "declined"
    (event_sender or send_plan_approval_event)(run_id, status, str(approved_plan_path))
    return {
        "status": "plan_approval_event_sent",
        "run_id": run_id,
        "approval_status": status,
        "approved_plan_path": str(approved_plan_path),
    }


def send_plan_approval_event(
    run_id: str, status: str, approved_plan_path: str | None = None
) -> None:
    try:
        hatchet = Hatchet()
        hatchet.event.push(
            PLAN_APPROVAL_EVENT_KEY,
            {
                "run_id": run_id,
                "status": status,
                "approved_plan_path": approved_plan_path,
            },
            scope=run_id,
        )
    except Exception as exc:
        raise TaskRunError("Could not send Hatchet plan approval event.") from exc


def apply_plan_approval_event(
    task_state_path: str | Path, event_payload: dict[str, Any]
) -> dict[str, Any]:
    payload = _normalize_event_payload(event_payload)
    state = _read_json(task_state_path)
    if state.get("phase") != "plan_pending_approval":
        return {"status": "skipped", "reason": "not_pending_approval"}
    if payload.get("run_id") not in {None, state.get("run_id")}:
        raise TaskRunError("Plan approval event run_id does not match Task Run.")

    approval_status = _approval_status(payload)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)
    approved_plan_path = Path(
        payload.get("approved_plan_path") or artifacts["approved_plan"]
    )
    _record_plan_approval(
        state=state,
        active_task_state=active_task_state,
        planning_artifact_path=Path(artifacts["planning"]),
        approved_plan_path=approved_plan_path,
        status=approval_status,
        mode="human",
    )
    _write_json(Path(task_state_path), state)
    return {
        "status": "plan_approval_recorded",
        "approval_status": approval_status,
    }


def terminal_result_for_state(state: dict[str, Any]) -> dict[str, Any] | None:
    phase = state.get("phase")
    if phase == "completed":
        return {"status": "completed", "run_id": state.get("run_id")}
    if phase == "failed":
        failure = state.get("failure")
        return failure if isinstance(failure, dict) else {"status": "failed"}
    if phase == "plan_approval_declined":
        return {
            "status": "stopped",
            "reason": "plan_approval_declined",
            "active_task_id": state.get("active_task_id"),
        }
    return None


def _run_current_phase_with_runtime(
    task_state_path: Path, agent_runtime: Any, phase: Any
) -> dict[str, Any]:
    state = _read_json(task_state_path)
    if phase in {"ready_for_planning", "planning_needs_answers"}:
        _require_clean_state_target_repository(state, "before resuming planning")
        return plan_active_task(
            task_state_path,
            agent_runtime,
            approved_plan_editor=lambda _path: None,
            plan_approval_confirmer=_raise_plan_approval_wait,
            usage_sleep=_raise_usage_limit_wait,
        )
    if phase == "plan_approved":
        _require_clean_state_target_repository(state, "before resuming implementation")
        return run_active_task_implementer(
            task_state_path,
            agent_runtime,
            usage_sleep=_raise_usage_limit_wait,
        )
    if phase == "ready_for_tests":
        return run_active_task_tests(task_state_path)
    if phase == "tests_failed":
        return run_active_task_failed_test_repair(
            task_state_path,
            agent_runtime,
            usage_sleep=_raise_usage_limit_wait,
        )
    if phase == "tests_passed":
        return run_active_task_reviewer(
            task_state_path,
            agent_runtime,
            usage_sleep=_raise_usage_limit_wait,
        )
    if phase == "review_rejected":
        return run_active_task_review_rejection_repair(
            task_state_path,
            agent_runtime,
            usage_sleep=_raise_usage_limit_wait,
        )
    if phase == "commit_ready":
        return commit_active_task_and_advance(task_state_path)
    raise TaskRunError(f"Cannot run Task Run phase once: {phase!r}.")


def _raise_usage_limit_wait(sleep_seconds: float) -> None:
    raise DurableUsageLimitWait(sleep_seconds)


def _raise_plan_approval_wait(approved_plan_path: Path) -> bool:
    raise DurablePlanApprovalWait(approved_plan_path)


def _normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("payload")
    if isinstance(nested, dict):
        return nested
    return payload


def _approval_status(payload: dict[str, Any]) -> str:
    status = (
        payload["status"] if "status" in payload else payload.get("approval_status")
    )
    if status in {"approved", "approve", True}:
        return "approved"
    if status in {"declined", "decline", "rejected", False}:
        return "declined"
    raise TaskRunError(f"Unknown plan approval event status: {status!r}.")
