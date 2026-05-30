from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_control_plane.task_control_plane.controller import TaskRun, start_task_run
from agent_control_plane.task_control_plane.hatchet_workflow import (
    TaskControlPhaseInput,
    TaskControlRunInput,
    bridge_plan_approval_if_pending,
    build_hatchet_workflows,
    run_current_phase_once,
    run_task_control_loop,
)


class FakeDurableContext:
    def __init__(self, event_payload: dict[str, Any] | None = None) -> None:
        self.event_payload = event_payload or {}
        self.sleeps: list[timedelta] = []
        self.event_waits: list[dict[str, object]] = []

    async def aio_sleep_for(
        self, duration: timedelta, label: str | None = None
    ) -> None:
        self.sleeps.append(duration)

    async def aio_wait_for_event(
        self,
        key: str,
        *,
        scope: str | None = None,
        lookback_window: timedelta | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        self.event_waits.append(
            {
                "key": key,
                "scope": scope,
                "lookback_window": lookback_window,
                "label": label,
            }
        )
        return self.event_payload


class FakeHatchet:
    def __init__(self) -> None:
        self.registrations: list[tuple[str, str]] = []

    def durable_task(self, **kwargs: object) -> Any:
        self.registrations.append(("durable", str(kwargs["name"])))

        def register(function: Any) -> Any:
            return function

        return register

    def task(self, **kwargs: object) -> Any:
        self.registrations.append(("task", str(kwargs["name"])))

        def register(function: Any) -> Any:
            return function

        return register


def init_target_repository(tmp_path: Path) -> Path:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(["git", "init"], cwd=target_repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Task Control Plane Test"],
        cwd=target_repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "task-control-plane@example.test"],
        cwd=target_repository,
        check=True,
    )
    (target_repository / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target_repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=target_repository, check=True
    )
    return target_repository


def write_task_spec(tmp_path: Path, target_repository: Path) -> Path:
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        "\n".join(
            [
                "version: 1",
                "description: Hatchet test",
                f"target_repository: {target_repository}",
                "require_plan_approval: false",
                "codex:",
                "  model: gpt-5-codex",
                "tasks:",
                "  - id: TASK-1",
                "    title: First task",
                "    prompt: Implement the first task.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return task_spec_path


def create_task_run(tmp_path: Path) -> TaskRun:
    target_repository = init_target_repository(tmp_path)
    return start_task_run(
        write_task_spec(tmp_path, target_repository),
        runtime_root=tmp_path / "runs",
    )


def read_state(task_run: TaskRun) -> dict[str, Any]:
    return json.loads(task_run.task_state_path.read_text(encoding="utf-8"))


def test_build_hatchet_workflows_registers_only_durable_run() -> None:
    hatchet = FakeHatchet()

    workflows = build_hatchet_workflows(hatchet)

    assert len(workflows) == 1
    assert hatchet.registrations == [("durable", "task-control-run")]


def write_state(task_run: TaskRun, state: dict[str, Any]) -> None:
    task_run.task_state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def set_phase(task_run: TaskRun, phase: str) -> None:
    state = read_state(task_run)
    state["phase"] = phase
    state["tasks"][0]["phase"] = phase
    write_state(task_run, state)


def complete_run(task_run: TaskRun) -> None:
    state = read_state(task_run)
    state["phase"] = "completed"
    state["active_task_id"] = None
    state["active_task"] = None
    state["tasks"][0]["phase"] = "completed"
    state["tasks"][0]["status"] = "completed"
    write_state(task_run, state)


def test_hatchet_loop_runs_phases_in_order(tmp_path: Path) -> None:
    task_run = create_task_run(tmp_path)
    seen: list[str] = []
    next_phase = {
        "ready_for_planning": "plan_approved",
        "plan_approved": "ready_for_tests",
        "ready_for_tests": "tests_passed",
        "tests_passed": "commit_ready",
    }

    def phase_runner(input: TaskControlPhaseInput) -> dict[str, Any]:
        seen.append(input.phase)
        if input.phase == "commit_ready":
            complete_run(task_run)
        else:
            set_phase(task_run, next_phase[input.phase])
        return {"status": "phase_completed", "phase": input.phase}

    result = asyncio.run(
        run_task_control_loop(
            TaskControlRunInput(
                run_id=task_run.run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            FakeDurableContext(),
            phase_runner=phase_runner,
        )
    )

    assert result["status"] == "completed"
    assert seen == [
        "ready_for_planning",
        "plan_approved",
        "ready_for_tests",
        "tests_passed",
        "commit_ready",
    ]


def test_hatchet_loop_sleeps_and_retries_same_phase_on_usage_limit(
    tmp_path: Path,
) -> None:
    task_run = create_task_run(tmp_path)
    seen: list[str] = []

    def phase_runner(input: TaskControlPhaseInput) -> dict[str, Any]:
        seen.append(input.phase)
        if len(seen) == 1:
            return {"status": "usage_limit_wait", "sleep_seconds": 5.0}
        complete_run(task_run)
        return {"status": "phase_completed"}

    ctx = FakeDurableContext()
    result = asyncio.run(
        run_task_control_loop(
            TaskControlRunInput(
                run_id=task_run.run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            ctx,
            phase_runner=phase_runner,
        )
    )

    assert result["status"] == "completed"
    assert seen == ["ready_for_planning", "ready_for_planning"]
    assert ctx.sleeps == [timedelta(seconds=5)]


def test_hatchet_loop_waits_for_plan_approval_event(tmp_path: Path) -> None:
    task_run = create_task_run(tmp_path)
    seen: list[str] = []

    def phase_runner(input: TaskControlPhaseInput) -> dict[str, Any]:
        seen.append(input.phase)
        state = read_state(task_run)
        task_state = state["tasks"][0]
        if input.phase == "ready_for_planning":
            state["phase"] = "plan_pending_approval"
            task_state["phase"] = "plan_pending_approval"
            approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
            approved_plan_path.write_text("Plan.\n", encoding="utf-8")
            write_state(task_run, state)
            return {
                "status": "plan_approval_wait",
                "approved_plan_path": str(approved_plan_path),
            }

        assert task_state["plan_approval"]["status"] == "approved"
        complete_run(task_run)
        return {"status": "phase_completed"}

    ctx = FakeDurableContext({"run_id": task_run.run_id, "status": "approved"})
    result = asyncio.run(
        run_task_control_loop(
            TaskControlRunInput(
                run_id=task_run.run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            ctx,
            phase_runner=phase_runner,
        )
    )

    assert result["status"] == "completed"
    assert seen == ["ready_for_planning", "plan_approved"]
    assert ctx.event_waits[0]["scope"] == task_run.run_id


def test_run_current_phase_once_skips_stale_phase(tmp_path: Path) -> None:
    task_run = create_task_run(tmp_path)
    set_phase(task_run, "plan_approved")

    result = run_current_phase_once(
        TaskControlPhaseInput(
            run_id=task_run.run_id,
            runtime_root=str(tmp_path / "runs"),
            task_state_path=str(task_run.task_state_path),
            phase="ready_for_planning",
        ),
        agent_runtime=object(),
    )

    assert result == {
        "status": "skipped",
        "run_id": task_run.run_id,
        "requested_phase": "ready_for_planning",
        "current_phase": "plan_approved",
    }


def test_cli_bridge_sends_plan_approval_event_for_pending_run(tmp_path: Path) -> None:
    task_run = create_task_run(tmp_path)
    state = read_state(task_run)
    state["phase"] = "plan_pending_approval"
    state["tasks"][0]["phase"] = "plan_pending_approval"
    approved_plan_path = Path(state["tasks"][0]["artifacts"]["approved_plan"])
    approved_plan_path.write_text("Plan.\n", encoding="utf-8")
    write_state(task_run, state)
    sent: list[tuple[str, str, str | None]] = []

    result = bridge_plan_approval_if_pending(
        task_run.run_id,
        runtime_root=tmp_path / "runs",
        approved_plan_editor=lambda _path: None,
        plan_approval_confirmer=lambda _path: True,
        event_sender=lambda run_id, status, path: sent.append((run_id, status, path)),
    )

    assert result is not None
    assert result["approval_status"] == "approved"
    assert sent == [(task_run.run_id, "approved", str(approved_plan_path))]


@pytest.mark.parametrize(
    ("phase", "expected_status"),
    [
        ("completed", "completed"),
        ("failed", "failed"),
        ("plan_approval_declined", "stopped"),
    ],
)
def test_hatchet_loop_returns_terminal_states(
    tmp_path: Path, phase: str, expected_status: str
) -> None:
    task_run = create_task_run(tmp_path)
    state = read_state(task_run)
    state["phase"] = phase
    if phase == "failed":
        state["failure"] = {"status": "failed", "reason": "boom"}
    write_state(task_run, state)

    def phase_runner(_input: TaskControlPhaseInput) -> dict[str, Any]:
        raise AssertionError("terminal runs must not schedule a phase")

    result = asyncio.run(
        run_task_control_loop(
            TaskControlRunInput(
                run_id=task_run.run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            FakeDurableContext(),
            phase_runner=phase_runner,
        )
    )

    assert result["status"] == expected_status
