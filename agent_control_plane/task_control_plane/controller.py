from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from openai_codex import ApprovalMode
from openai_codex.generated.v2_all import (
    ReadOnlySandboxPolicy,
    ReasoningEffort,
    SandboxMode,
    WorkspaceWriteSandboxPolicy,
)

from agent_control_plane.task_control_plane.task_spec import (
    Task,
    TaskSpec,
    TestCommand,
    load_task_spec,
)


PACKAGE_DIRECTORY = Path(__file__).parent
PLANNER_PROMPT_PATH = PACKAGE_DIRECTORY / "prompts" / "planner-agent.md"
PLANNER_OUTPUT_SCHEMA_PATH = (
    PACKAGE_DIRECTORY / "schemas" / "planner-output.schema.json"
)
CONTEXT_PROMPT_PATH = PACKAGE_DIRECTORY / "prompts" / "context-agent.md"
CONTEXT_ANSWERS_SCHEMA_PATH = (
    PACKAGE_DIRECTORY / "schemas" / "context-answers-output.schema.json"
)
IMPLEMENTER_PROMPT_PATH = PACKAGE_DIRECTORY / "prompts" / "implementer-agent.md"
IMPLEMENTER_RESULT_SCHEMA_PATH = (
    PACKAGE_DIRECTORY / "schemas" / "implementer-result-output.schema.json"
)
REVIEWER_PROMPT_PATH = PACKAGE_DIRECTORY / "prompts" / "reviewer-agent.md"
REVIEWER_OUTPUT_SCHEMA_PATH = (
    PACKAGE_DIRECTORY / "schemas" / "reviewer-output.schema.json"
)
PLANNER_STATUSES = frozenset({"planned", "needs_answers"})
CONTEXT_ANSWER_STATUSES = frozenset({"answered", "unresolved"})
REVIEWER_STATUSES = frozenset({"approved", "rejected"})

HumanAnswerProvider = Callable[[list[dict[str, Any]], Path, Path], list[dict[str, Any]]]
ApprovedPlanEditor = Callable[[Path], None]
PlanApprovalConfirmer = Callable[[Path], bool]
UsageLimitClock = Callable[[], datetime]
UsageLimitSleeper = Callable[[float], None]


@dataclass(frozen=True)
class TaskRun:
    run_id: str
    run_directory: Path
    task_spec_snapshot_path: Path
    task_state_path: Path
    first_task_context_path: Path


class TaskRunError(RuntimeError):
    """Raised when a Task Run cannot be started."""


class PlannerOutputError(RuntimeError):
    """Raised when the Planner Agent output cannot drive Controller routing."""


class ContextOutputError(RuntimeError):
    """Raised when the Context Agent output cannot drive Controller routing."""


class ImplementerOutputError(RuntimeError):
    """Raised when the Implementer Agent output cannot be recorded."""


class ReviewerOutputError(RuntimeError):
    """Raised when the Reviewer Agent output cannot drive Controller routing."""


class HumanAnswerError(RuntimeError):
    """Raised when human answer provider output cannot drive Controller routing."""


def start_task_run(
    task_spec_path: str | Path, runtime_root: str | Path = "runs"
) -> TaskRun:
    task_spec = load_task_spec(task_spec_path)
    _require_clean_target_repository(task_spec.target_repository)

    run_id = _new_run_id()
    runtime_root_path = Path(runtime_root).resolve()
    run_directory = runtime_root_path / run_id
    task_directory = run_directory / "tasks" / task_spec.tasks[0].task_id
    task_directory.mkdir(parents=True)

    task_spec_snapshot_path = run_directory / "task-spec.yaml"
    task_state_path = run_directory / "task-state.json"
    first_task_context_path = task_directory / "context.json"

    shutil.copyfile(task_spec.source_path, task_spec_snapshot_path)

    artifact_paths = _artifact_paths(task_directory)
    context = _first_task_context(
        task_spec=task_spec,
        run_id=run_id,
        run_directory=run_directory,
        task_spec_snapshot_path=task_spec_snapshot_path,
        task_state_path=task_state_path,
        context_path=first_task_context_path,
        artifact_paths=artifact_paths,
    )
    _write_json(first_task_context_path, context)

    state = _initial_task_state(
        task_spec=task_spec,
        run_id=run_id,
        run_directory=run_directory,
        task_spec_snapshot_path=task_spec_snapshot_path,
        task_state_path=task_state_path,
        first_task_context_path=first_task_context_path,
        artifact_paths=artifact_paths,
    )
    _write_json(task_state_path, state)

    return TaskRun(
        run_id=run_id,
        run_directory=run_directory,
        task_spec_snapshot_path=task_spec_snapshot_path,
        task_state_path=task_state_path,
        first_task_context_path=first_task_context_path,
    )


def resume_task_run(
    run_id: str,
    codex_client: Any,
    *,
    runtime_root: str | Path = "runs",
    human_answer_provider: HumanAnswerProvider | None = None,
    approved_plan_editor: ApprovedPlanEditor | None = None,
    plan_approval_confirmer: PlanApprovalConfirmer | None = None,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_run = _load_existing_task_run(run_id, runtime_root)

    while True:
        state = _read_json(task_run.task_state_path)
        _check_loaded_task_run_state(task_run, state)
        phase = state.get("phase")

        if phase == "completed":
            return {"status": "completed", "run_id": task_run.run_id}
        if phase == "failed":
            failure = state.get("failure")
            return failure if isinstance(failure, dict) else {"status": "failed"}
        if phase == "plan_approval_declined":
            return {
                "status": "stopped",
                "reason": "plan_approval_declined",
                "active_task_id": state.get("active_task_id"),
            }
        if phase == "target_repository_dirty_before_next_task":
            _resume_after_dirty_before_next_task(task_run.task_state_path)
            continue

        _require_resume_can_continue_from_phase(state)

        if phase in {"ready_for_planning", "planning_needs_answers"}:
            _require_clean_target_repository(
                Path(state["target_repository"]).resolve(),
                "before resuming planning",
            )
            plan_active_task(
                task_run.task_state_path,
                codex_client,
                human_answer_provider=human_answer_provider,
                approved_plan_editor=approved_plan_editor,
                plan_approval_confirmer=plan_approval_confirmer,
                usage_clock=usage_clock,
                usage_sleep=usage_sleep,
            )
            continue

        if phase == "plan_approved":
            _require_clean_target_repository(
                Path(state["target_repository"]).resolve(),
                "before resuming implementation",
            )
            run_active_task_implementer(
                task_run.task_state_path,
                codex_client,
                usage_clock=usage_clock,
                usage_sleep=usage_sleep,
            )
            continue

        if phase == "ready_for_tests":
            run_active_task_tests(task_run.task_state_path)
            continue

        if phase == "tests_failed":
            repair_result = run_active_task_failed_test_repair(
                task_run.task_state_path,
                codex_client,
                usage_clock=usage_clock,
                usage_sleep=usage_sleep,
            )
            if repair_result.get("status") == "failed":
                return repair_result
            continue

        if phase == "tests_passed":
            run_active_task_reviewer(
                task_run.task_state_path,
                codex_client,
                usage_clock=usage_clock,
                usage_sleep=usage_sleep,
            )
            continue

        if phase == "review_rejected":
            repair_result = run_active_task_review_rejection_repair(
                task_run.task_state_path,
                codex_client,
                usage_clock=usage_clock,
                usage_sleep=usage_sleep,
            )
            if repair_result.get("status") == "failed":
                return repair_result
            continue

        if phase == "commit_ready":
            result = commit_active_task_and_advance(task_run.task_state_path)
            if result["status"] == "completed":
                return result
            continue

        raise TaskRunError(f"Cannot safely resume Task Run from phase: {phase!r}.")


def plan_active_task(
    task_state_path: str | Path,
    codex_client: Any,
    *,
    human_answer_provider: HumanAnswerProvider | None = None,
    approved_plan_editor: ApprovedPlanEditor | None = None,
    plan_approval_confirmer: PlanApprovalConfirmer | None = None,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()
    task_context_path = Path(artifacts["task_context"])
    planning_artifact_path = Path(artifacts["planning"])
    task_context = _read_json(task_context_path)

    planner_developer_instructions = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
    planner_output_schema = _read_json(PLANNER_OUTPUT_SCHEMA_PATH)
    resuming_planner_questions = state.get("phase") == "planning_needs_answers"
    if resuming_planner_questions and _planner_thread_id(active_task_state) is None:
        raise TaskRunError(
            "Cannot resume Planner Agent questions without a saved Planner Agent thread ID."
        )
    thread = _planner_thread(
        codex_client=codex_client,
        task_state=active_task_state,
        target_repository=target_repository,
        developer_instructions=planner_developer_instructions,
        model=task_spec.codex.model,
    )

    _persist_planner_thread_id(active_task_state, thread.id)
    _write_json(task_state_file, state)

    if resuming_planner_questions:
        planner_output = _latest_planner_output(planning_artifact_path)
        _check_planner_output_for_routing(planner_output)
        if planner_output["status"] != "needs_answers":
            raise TaskRunError(
                "Saved planning phase requires latest Planner Agent output to need answers."
            )
    else:
        turn_result = _run_planner_thread(
            thread=thread,
            turn_input=_planner_turn_input(task_context_path, task_context),
            target_repository=target_repository,
            effort=task_spec.codex.effort,
            model=task_spec.codex.model,
            output_schema=planner_output_schema,
            task_state_file=task_state_file,
            state=state,
            active_task_state=active_task_state,
            usage_clock=usage_clock,
            usage_sleep=usage_sleep,
        )
        planner_output = _parse_planner_output(turn_result)
        _check_planner_output_for_routing(planner_output)
        _append_planner_output(planning_artifact_path, planner_output)

    context_thread: Any | None = None
    context_answers_schema: dict[str, Any] | None = None
    while planner_output["status"] == "needs_answers":
        state["phase"] = "planning_needs_answers"
        active_task_state["phase"] = "planning_needs_answers"
        _write_json(task_state_file, state)

        if context_thread is None:
            context_developer_instructions = CONTEXT_PROMPT_PATH.read_text(
                encoding="utf-8"
            )
            context_answers_schema = _read_json(CONTEXT_ANSWERS_SCHEMA_PATH)
            context_thread = _context_thread(
                codex_client=codex_client,
                task_state=active_task_state,
                target_repository=target_repository,
                developer_instructions=context_developer_instructions,
                model=task_spec.codex.model,
            )
            _persist_context_thread_id(active_task_state, context_thread.id)
            _write_json(task_state_file, state)

        questions = _planner_questions(planner_output)
        context_turn_result = _run_context_thread(
            thread=context_thread,
            turn_input=_context_turn_input(
                questions=questions,
                task_context_path=task_context_path,
                planning_artifact_path=planning_artifact_path,
            ),
            target_repository=target_repository,
            effort=task_spec.codex.effort,
            model=task_spec.codex.model,
            output_schema=context_answers_schema,
            task_state_file=task_state_file,
            state=state,
            active_task_state=active_task_state,
            usage_clock=usage_clock,
            usage_sleep=usage_sleep,
        )
        context_output = _parse_context_output(context_turn_result)
        _check_context_output_for_routing(context_output, questions)
        context_answers = _context_answers(context_output)
        unresolved_questions = _unresolved_questions_for_human(
            questions, context_answers
        )
        human_answers: list[dict[str, Any]] = []
        if unresolved_questions:
            if human_answer_provider is None:
                raise HumanAnswerError(
                    "Planner questions need human answers, but no human answer provider was supplied."
                )
            human_answers = human_answer_provider(
                unresolved_questions, task_context_path, planning_artifact_path
            )
            _check_human_answers_for_routing(human_answers, unresolved_questions)

        _append_answer_batch(
            planning_artifact_path,
            planner_questions=questions,
            context_answers=context_answers,
            human_answers=human_answers,
        )

        turn_result = _run_planner_thread(
            thread=thread,
            turn_input=_planner_follow_up_turn_input(
                task_context_path=task_context_path,
                planning_artifact_path=planning_artifact_path,
                planner_questions=questions,
                context_answers=context_answers,
                human_answers=human_answers,
            ),
            target_repository=target_repository,
            effort=task_spec.codex.effort,
            model=task_spec.codex.model,
            output_schema=planner_output_schema,
            task_state_file=task_state_file,
            state=state,
            active_task_state=active_task_state,
            usage_clock=usage_clock,
            usage_sleep=usage_sleep,
        )
        planner_output = _parse_planner_output(turn_result)
        _check_planner_output_for_routing(planner_output)
        _append_planner_output(planning_artifact_path, planner_output)

    approved_plan_path = Path(artifacts["approved_plan"])
    _write_approved_plan_candidate(approved_plan_path, planner_output["plan_markdown"])

    state["phase"] = "plan_ready"
    active_task_state["phase"] = "plan_ready"
    if task_spec.require_plan_approval:
        state["phase"] = "plan_pending_approval"
        active_task_state["phase"] = "plan_pending_approval"
        _write_json(task_state_file, state)
        (approved_plan_editor or _open_approved_plan_in_editor)(approved_plan_path)
        approval_confirmed = (plan_approval_confirmer or _confirm_approved_plan)(
            approved_plan_path
        ) is True
        approval_status = "approved" if approval_confirmed else "declined"
        _record_plan_approval(
            state=state,
            active_task_state=active_task_state,
            planning_artifact_path=planning_artifact_path,
            approved_plan_path=approved_plan_path,
            status=approval_status,
            mode="human",
        )
    else:
        _record_plan_approval(
            state=state,
            active_task_state=active_task_state,
            planning_artifact_path=planning_artifact_path,
            approved_plan_path=approved_plan_path,
            status="approved",
            mode="automatic",
        )

    _write_json(task_state_file, state)
    return planner_output


def build_implementer_turn_input(task_state_path: str | Path) -> str:
    state = _read_json(task_state_path)
    active_task_state = _active_task_state(state)
    plan_approval = active_task_state.get("plan_approval")
    if not isinstance(plan_approval, dict) or plan_approval.get("status") != "approved":
        raise TaskRunError("Approved Plan has not been approved for implementation.")

    artifacts = _task_artifacts(active_task_state)
    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    active_task_id = active_task_state.get("id")
    task = next(
        (task for task in task_spec.tasks if task.task_id == active_task_id), None
    )
    if task is None:
        raise TaskRunError(f"Task Spec snapshot has no active Task: {active_task_id}")

    return "\n".join(
        [
            "Implement the active Task using the Approved Plan artifact.",
            "",
            f"Task ID: {task.task_id}",
            f"Task title: {task.title}",
            f"Task prompt: {task.prompt}",
            f"Task context: {task.context or 'None'}",
            "",
            f"Task context artifact: {artifacts['task_context']}",
            f"Approved Plan artifact: {artifacts['approved_plan']}",
        ]
    )


def run_active_task_implementer(
    task_state_path: str | Path,
    codex_client: Any,
    *,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    return _run_active_task_implementer_turn(
        task_state_file,
        codex_client,
        build_implementer_turn_input(task_state_file),
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
    )


def run_active_task_failed_test_repair(
    task_state_path: str | Path,
    codex_client: Any,
    *,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)
    latest_test_status = _latest_failed_test_status(active_task_state)
    task_spec = load_task_spec(state["task_spec_snapshot_path"])

    iterations = _active_task_iterations(active_task_state) + 1
    active_task_state["iterations"] = iterations
    if iterations >= task_spec.max_iterations:
        failure = _mark_active_task_failed(
            state=state,
            active_task_state=active_task_state,
            reason="max_iterations_reached",
            iterations=iterations,
            max_iterations=task_spec.max_iterations,
        )
        _write_json(task_state_file, state)
        return failure

    state["phase"] = "failed_test_repair_pending"
    active_task_state["phase"] = "failed_test_repair_pending"
    _write_json(task_state_file, state)

    return _run_active_task_implementer_turn(
        task_state_file,
        codex_client,
        _failed_test_repair_turn_input(artifacts, latest_test_status),
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
    )


def run_active_task_review_rejection_repair(
    task_state_path: str | Path,
    codex_client: Any,
    *,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    latest_review_output_json = _latest_rejected_review_output_json(active_task_state)
    task_spec = load_task_spec(state["task_spec_snapshot_path"])

    iterations = _active_task_iterations(active_task_state) + 1
    active_task_state["iterations"] = iterations
    if iterations >= task_spec.max_iterations:
        failure = _mark_active_task_failed(
            state=state,
            active_task_state=active_task_state,
            reason="max_iterations_reached",
            iterations=iterations,
            max_iterations=task_spec.max_iterations,
        )
        _write_json(task_state_file, state)
        return failure

    state["phase"] = "review_rejection_repair_pending"
    active_task_state["phase"] = "review_rejection_repair_pending"
    _write_json(task_state_file, state)

    return _run_active_task_implementer_turn(
        task_state_file,
        codex_client,
        _review_rejection_repair_turn_input(latest_review_output_json),
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
    )


def _run_active_task_implementer_turn(
    task_state_file: Path,
    codex_client: Any,
    turn_input: str,
    *,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()

    implementer_developer_instructions = IMPLEMENTER_PROMPT_PATH.read_text(
        encoding="utf-8"
    )
    implementer_result_schema = _read_json(IMPLEMENTER_RESULT_SCHEMA_PATH)
    thread = _implementer_thread(
        codex_client=codex_client,
        task_state=active_task_state,
        target_repository=target_repository,
        developer_instructions=implementer_developer_instructions,
        model=task_spec.codex.model,
    )

    _persist_implementer_thread_id(active_task_state, thread.id)
    _write_json(task_state_file, state)

    turn_result = _run_implementer_thread(
        thread=thread,
        turn_input=turn_input,
        target_repository=target_repository,
        effort=task_spec.codex.effort,
        model=task_spec.codex.model,
        output_schema=implementer_result_schema,
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
    )
    implementer_output = _parse_implementer_output(turn_result)
    _write_json(Path(artifacts["implementation_result"]), implementer_output)

    state["phase"] = "ready_for_tests"
    active_task_state["phase"] = "ready_for_tests"
    active_task_state.pop("latest_test_status", None)
    _write_json(task_state_file, state)
    return implementer_output


def run_active_task_tests(task_state_path: str | Path) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()
    command_log_path = Path(artifacts["command_log"])

    test_status = _run_test_commands(
        commands=task_spec.test_commands,
        target_repository=target_repository,
        command_log_path=command_log_path,
    )

    phase = "tests_passed" if test_status["passed"] else "tests_failed"
    state["phase"] = phase
    active_task_state["phase"] = phase
    active_task_state["latest_test_status"] = test_status
    _write_json(task_state_file, state)
    return test_status


def run_active_task_reviewer(
    task_state_path: str | Path,
    codex_client: Any,
    *,
    usage_clock: UsageLimitClock | None = None,
    usage_sleep: UsageLimitSleeper | None = None,
) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)
    latest_test_status = _latest_passing_test_status(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()

    reviewer_developer_instructions = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    reviewer_output_schema = _read_json(REVIEWER_OUTPUT_SCHEMA_PATH)
    thread = _reviewer_thread(
        codex_client=codex_client,
        target_repository=target_repository,
        developer_instructions=reviewer_developer_instructions,
        model=task_spec.codex.model,
    )

    turn_result = _run_reviewer_thread(
        thread=thread,
        turn_input=_reviewer_turn_input(
            task_spec=task_spec,
            active_task_state=active_task_state,
            artifacts=artifacts,
            latest_test_status=latest_test_status,
        ),
        target_repository=target_repository,
        effort=task_spec.codex.effort,
        model=task_spec.codex.model,
        output_schema=reviewer_output_schema,
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
    )
    reviewer_output = _parse_reviewer_output(turn_result)
    reviewer_output_json = _reviewer_output_json_text(turn_result, reviewer_output)
    _check_reviewer_output_for_routing(reviewer_output)
    _append_review_output(Path(artifacts["review_log"]), reviewer_output_json)

    active_task_state["review_attempts"] = (
        _active_task_review_attempts(active_task_state) + 1
    )
    active_task_state["latest_review_output"] = reviewer_output
    active_task_state["latest_review_output_json"] = reviewer_output_json
    if reviewer_output["status"] == "approved":
        state["phase"] = "commit_ready"
        active_task_state["phase"] = "commit_ready"
    else:
        state["phase"] = "review_rejected"
        active_task_state["phase"] = "review_rejected"
    _write_json(task_state_file, state)
    return reviewer_output


def commit_active_task_and_advance(task_state_path: str | Path) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    _require_active_task_commit_ready(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()
    active_task_id = active_task_state.get("id")
    task = _task_spec_task_by_id(task_spec, active_task_id)

    commit_sha = _commit_all_target_repository_changes(
        target_repository=target_repository,
        message=f"{task.task_id}: {task.title}",
    )
    completed_at = _utc_timestamp()
    active_task_state["status"] = "completed"
    active_task_state["phase"] = "completed"
    active_task_state["commit_sha"] = commit_sha
    active_task_state["completed_at"] = completed_at

    next_task_state = _next_pending_task_state(state, task.task_id)
    if next_task_state is None:
        state["phase"] = "completed"
        state["active_task_id"] = None
        state["active_task"] = None
        state["completed_at"] = completed_at
        _write_json(task_state_file, state)
        return {
            "status": "completed",
            "completed_task_id": task.task_id,
            "commit_sha": commit_sha,
        }

    try:
        _require_clean_target_repository(
            target_repository, "before starting the next Task"
        )
    except TaskRunError:
        state["phase"] = "target_repository_dirty_before_next_task"
        _write_json(task_state_file, state)
        raise

    next_task = _task_spec_task_by_id(task_spec, next_task_state.get("id"))
    _activate_next_task(
        state=state,
        next_task_state=next_task_state,
        next_task=next_task,
        task_spec=task_spec,
        task_state_path=task_state_file,
    )
    _write_json(task_state_file, state)
    return {
        "status": "advanced",
        "completed_task_id": task.task_id,
        "commit_sha": commit_sha,
        "active_task_id": next_task.task_id,
    }


def _load_existing_task_run(run_id: str, runtime_root: str | Path) -> TaskRun:
    if not isinstance(run_id, str) or not run_id.strip():
        raise TaskRunError("Task Run ID is required.")

    runtime_root_path = Path(runtime_root).resolve()
    run_directory = runtime_root_path / run_id
    task_spec_snapshot_path = run_directory / "task-spec.yaml"
    task_state_path = run_directory / "task-state.json"

    if not run_directory.exists():
        raise TaskRunError(f"Task Run does not exist: {run_id}")
    if not task_spec_snapshot_path.exists():
        raise TaskRunError(
            f"Task Run is missing snapshotted Task Spec: {task_spec_snapshot_path}"
        )
    if not task_state_path.exists():
        raise TaskRunError(
            f"Task Run is missing Controller-owned Task State: {task_state_path}"
        )

    state = _read_json(task_state_path)
    active_task_state = _active_task_state(state) if state.get("active_task_id") else {}
    artifacts = active_task_state.get("artifacts") if active_task_state else {}
    first_task_context_path = (
        Path(artifacts["task_context"])
        if isinstance(artifacts, dict)
        and isinstance(artifacts.get("task_context"), str)
        else run_directory / "tasks"
    )
    return TaskRun(
        run_id=run_id,
        run_directory=run_directory,
        task_spec_snapshot_path=task_spec_snapshot_path,
        task_state_path=task_state_path,
        first_task_context_path=first_task_context_path,
    )


def _check_loaded_task_run_state(task_run: TaskRun, state: Mapping[str, Any]) -> None:
    if state.get("run_id") != task_run.run_id:
        raise TaskRunError(
            f"Task State run_id does not match requested Task Run ID: {task_run.run_id}"
        )

    task_spec_snapshot_path = Path(state.get("task_spec_snapshot_path", ""))
    if task_spec_snapshot_path.resolve() != task_run.task_spec_snapshot_path.resolve():
        raise TaskRunError(
            "Task State does not point at this Task Run's snapshotted Task Spec."
        )

    task_state_path = Path(state.get("task_state_path", ""))
    if task_state_path.resolve() != task_run.task_state_path.resolve():
        raise TaskRunError(
            "Task State does not point at this Task Run's Controller-owned state file."
        )

    load_task_spec(task_run.task_spec_snapshot_path)


def _require_resume_can_continue_from_phase(state: Mapping[str, Any]) -> None:
    active_task_state = _active_task_state(state)
    active_task_id = state.get("active_task_id")
    if active_task_state.get("id") != active_task_id:
        raise TaskRunError("Task State active Task fields are inconsistent.")
    if active_task_state.get("status") != "active":
        raise TaskRunError(f"Task Run cannot resume inactive Task: {active_task_id!r}.")
    if active_task_state.get("phase") != state.get("phase"):
        raise TaskRunError(
            "Task Run phase and active Task phase must match before resume."
        )


def _resume_after_dirty_before_next_task(task_state_path: str | Path) -> None:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    if state.get("phase") != "target_repository_dirty_before_next_task":
        raise TaskRunError("Task Run is not waiting to start the next Task.")

    active_task_state = _active_task_state(state)
    if active_task_state.get("status") != "completed":
        raise TaskRunError(
            "Task Run cannot start the next Task until the active Task is completed."
        )

    target_repository = Path(state["target_repository"]).resolve()
    _require_clean_target_repository(target_repository, "before starting the next Task")

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    completed_task_id = active_task_state.get("id")
    next_task_state = _next_pending_task_state(state, completed_task_id)
    if next_task_state is None:
        state["phase"] = "completed"
        state["active_task_id"] = None
        state["active_task"] = None
        state["completed_at"] = (
            active_task_state.get("completed_at") or _utc_timestamp()
        )
        _write_json(task_state_file, state)
        return

    next_task = _task_spec_task_by_id(task_spec, next_task_state.get("id"))
    _activate_next_task(
        state=state,
        next_task_state=next_task_state,
        next_task=next_task,
        task_spec=task_spec,
        task_state_path=task_state_file,
    )
    _write_json(task_state_file, state)


def _latest_passing_test_status(task_state: Mapping[str, Any]) -> dict[str, Any]:
    latest_test_status = task_state.get("latest_test_status")
    if not isinstance(latest_test_status, dict):
        raise TaskRunError("Active Task has no deterministic test result.")
    if latest_test_status.get("passed") is not True:
        raise TaskRunError("Active Task latest deterministic tests did not pass.")
    return latest_test_status


def _latest_failed_test_status(task_state: Mapping[str, Any]) -> dict[str, Any]:
    latest_test_status = task_state.get("latest_test_status")
    if not isinstance(latest_test_status, dict):
        raise TaskRunError("Active Task has no deterministic test result.")
    if latest_test_status.get("passed") is not False:
        raise TaskRunError("Active Task latest deterministic tests did not fail.")
    return latest_test_status


def _latest_rejected_review_output_json(task_state: Mapping[str, Any]) -> str:
    latest_review_output = task_state.get("latest_review_output")
    if not isinstance(latest_review_output, dict):
        raise TaskRunError("Active Task has no Reviewer Agent output.")
    if latest_review_output.get("status") != "rejected":
        raise TaskRunError("Active Task latest Reviewer Agent output was not rejected.")

    latest_review_output_json = task_state.get("latest_review_output_json")
    if isinstance(latest_review_output_json, str) and latest_review_output_json:
        return latest_review_output_json
    return json.dumps(latest_review_output)


def _active_task_iterations(task_state: Mapping[str, Any]) -> int:
    iterations = task_state.get("iterations")
    if not isinstance(iterations, int) or iterations < 0:
        raise TaskRunError(
            "Active Task iteration count must be a non-negative integer."
        )
    return iterations


def _active_task_review_attempts(task_state: Mapping[str, Any]) -> int:
    review_attempts = task_state.get("review_attempts", 0)
    if not isinstance(review_attempts, int) or review_attempts < 0:
        raise TaskRunError(
            "Active Task review attempt count must be a non-negative integer."
        )
    return review_attempts


def _failed_test_repair_turn_input(
    artifacts: Mapping[str, str], latest_test_status: Mapping[str, Any]
) -> str:
    command_log_path = (
        latest_test_status.get("command_log_path") or artifacts["command_log"]
    )
    return "\n".join(
        [
            "The deterministic test commands failed.",
            "",
            f"Approved Plan artifact: {artifacts['approved_plan']}",
            f"Command log artifact: {command_log_path}",
            "",
            "Inspect the command log, fix the implementation, and return a new implementation result.",
        ]
    )


def _review_rejection_repair_turn_input(latest_review_output_json: str) -> str:
    return "\n".join(
        [
            "The Reviewer Agent rejected the Task. Address the reviewer feedback exactly.",
            "",
            "Reviewer output:",
            latest_review_output_json,
        ]
    )


def _mark_active_task_failed(
    *,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    reason: str,
    iterations: int,
    max_iterations: int,
) -> dict[str, Any]:
    failure = {
        "status": "failed",
        "reason": reason,
        "failed_at": _utc_timestamp(),
        "iterations": iterations,
        "max_iterations": max_iterations,
    }
    state["phase"] = "failed"
    state["failure"] = {
        "active_task_id": active_task_state.get("id"),
        **failure,
    }
    active_task_state["status"] = "failed"
    active_task_state["phase"] = "failed"
    active_task_state["failure"] = failure
    return failure


def _run_test_commands(
    *,
    commands: tuple[TestCommand, ...],
    target_repository: Path,
    command_log_path: Path,
) -> dict[str, Any]:
    command_log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _utc_timestamp()
    command_results: list[dict[str, Any]] = []

    with command_log_path.open("a", encoding="utf-8", buffering=1) as command_log:
        log_lock = threading.Lock()
        _write_command_log(
            command_log,
            log_lock,
            "\n".join(
                [
                    "===== test run START =====",
                    f"started_at: {started_at}",
                    f"cwd: {target_repository}",
                    "",
                ]
            ),
        )

        for command in commands:
            command_results.append(
                _run_test_command(
                    command=command,
                    target_repository=target_repository,
                    command_log=command_log,
                    log_lock=log_lock,
                )
            )

        passed = all(result["status"] == "passed" for result in command_results)
        ended_at = _utc_timestamp()
        status = "passed" if passed else "failed"
        _write_command_log(
            command_log,
            log_lock,
            "\n".join(
                [
                    "===== test run END =====",
                    f"ended_at: {ended_at}",
                    f"status: {status}",
                    "",
                ]
            ),
        )

    return {
        "status": status,
        "passed": passed,
        "started_at": started_at,
        "ended_at": ended_at,
        "command_log_path": str(command_log_path),
        "command_results": command_results,
    }


def _run_test_command(
    *,
    command: TestCommand,
    target_repository: Path,
    command_log: TextIO,
    log_lock: threading.Lock,
) -> dict[str, Any]:
    argv = list(command.argv)
    started_at = _utc_timestamp()
    started_monotonic = time.monotonic()
    _write_command_log(
        command_log,
        log_lock,
        "\n".join(
            [
                f"===== test command START: {command.name} =====",
                f"name: {command.name}",
                f"argv: {json.dumps(argv)}",
                f"started_at: {started_at}",
                f"cwd: {target_repository}",
                "",
            ]
        ),
    )

    try:
        process = subprocess.Popen(
            argv,
            cwd=target_repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        ended_at = _utc_timestamp()
        duration_seconds = round(time.monotonic() - started_monotonic, 3)
        _write_command_log(
            command_log,
            log_lock,
            "\n".join(
                [
                    f"[stderr] failed to start command: {exc}",
                    f"===== test command END: {command.name} =====",
                    f"ended_at: {ended_at}",
                    "exit_code: null",
                    "status: failed",
                    f"duration_seconds: {duration_seconds}",
                    "",
                ]
            ),
        )
        return {
            "name": command.name,
            "argv": argv,
            "started_at": started_at,
            "ended_at": ended_at,
            "exit_code": None,
            "status": "failed",
            "duration_seconds": duration_seconds,
        }

    stdout_thread = threading.Thread(
        target=_stream_pipe_to_command_log,
        args=(process.stdout, "stdout", command_log, log_lock),
    )
    stderr_thread = threading.Thread(
        target=_stream_pipe_to_command_log,
        args=(process.stderr, "stderr", command_log, log_lock),
    )
    stdout_thread.start()
    stderr_thread.start()
    exit_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    ended_at = _utc_timestamp()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    status = "passed" if exit_code == 0 else "failed"
    _write_command_log(
        command_log,
        log_lock,
        "\n".join(
            [
                f"===== test command END: {command.name} =====",
                f"ended_at: {ended_at}",
                f"exit_code: {exit_code}",
                f"status: {status}",
                f"duration_seconds: {duration_seconds}",
                "",
            ]
        ),
    )
    return {
        "name": command.name,
        "argv": argv,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": exit_code,
        "status": status,
        "duration_seconds": duration_seconds,
    }


def _stream_pipe_to_command_log(
    pipe: BinaryIO | None,
    stream_name: str,
    command_log: TextIO,
    log_lock: threading.Lock,
) -> None:
    if pipe is None:
        return
    try:
        while chunk := pipe.read1(4096):
            text = chunk.decode("utf-8", errors="replace")
            _write_stream_chunk(command_log, log_lock, stream_name, text)
    finally:
        pipe.close()


def _write_stream_chunk(
    command_log: TextIO, log_lock: threading.Lock, stream_name: str, text: str
) -> None:
    if not text:
        return
    prefixed_lines = []
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            line = f"{line}\n"
        prefixed_lines.append(f"[{stream_name}] {line}")
    prefixed_text = "".join(prefixed_lines)
    _write_command_log(command_log, log_lock, prefixed_text)


def _write_command_log(
    command_log: TextIO, log_lock: threading.Lock, text: str
) -> None:
    if not text.endswith("\n"):
        text = f"{text}\n"
    with log_lock:
        command_log.write(text)
        command_log.flush()


def _require_clean_target_repository(
    target_repository: Path, clean_context: str = "before starting a Task Run"
) -> None:
    if not target_repository.exists():
        raise TaskRunError(f"Target Repository does not exist: {target_repository}")
    if not target_repository.is_dir():
        raise TaskRunError(f"Target Repository is not a directory: {target_repository}")

    inside_work_tree = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=target_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if inside_work_tree.returncode != 0 or inside_work_tree.stdout.strip() != "true":
        raise TaskRunError(
            f"Target Repository is not a git work tree: {target_repository}"
        )

    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise TaskRunError(
            f"Could not inspect Target Repository status: {status.stderr.strip()}"
        )
    if status.stdout.strip():
        raise TaskRunError(
            f"Target Repository must be clean {clean_context}: {target_repository}"
        )


def _require_active_task_commit_ready(task_state: Mapping[str, Any]) -> None:
    if task_state.get("phase") != "commit_ready":
        raise TaskRunError("Active Task is not ready to commit.")
    _latest_passing_test_status(task_state)
    latest_review_output = task_state.get("latest_review_output")
    if not isinstance(latest_review_output, dict):
        raise TaskRunError("Active Task has no Reviewer Agent output.")
    if latest_review_output.get("status") != "approved":
        raise TaskRunError("Active Task latest Reviewer Agent output was not approved.")


def _commit_all_target_repository_changes(
    *, target_repository: Path, message: str
) -> str:
    _run_git_command(["add", "--all"], target_repository)
    staged_changes = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--exit-code"],
        cwd=target_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if staged_changes.returncode == 0:
        raise TaskRunError("No non-ignored Target Repository changes to commit.")
    if staged_changes.returncode not in {0, 1}:
        raise TaskRunError(
            "Could not inspect staged Target Repository changes: "
            f"{staged_changes.stderr.strip()}"
        )

    _run_git_command(["commit", "-m", message], target_repository)
    return _run_git_command(["rev-parse", "HEAD"], target_repository).stdout.strip()


def _run_git_command(
    args: list[str], target_repository: Path
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=target_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        command = " ".join(["git", *args])
        if detail:
            raise TaskRunError(f"{command} failed: {detail}")
        raise TaskRunError(f"{command} failed.")
    return result


def _task_spec_task_by_id(task_spec: TaskSpec, task_id: Any) -> Task:
    for task in task_spec.tasks:
        if task.task_id == task_id:
            return task
    raise TaskRunError(f"Task Spec snapshot has no Task: {task_id}")


def _next_pending_task_state(
    state: Mapping[str, Any], completed_task_id: str
) -> dict[str, Any] | None:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise TaskRunError("Task State field 'tasks' must be a list.")

    for index, task_state in enumerate(tasks):
        if not isinstance(task_state, dict):
            raise TaskRunError("Task State tasks must be objects.")
        if task_state.get("id") != completed_task_id:
            continue
        for next_task_state in tasks[index + 1 :]:
            if not isinstance(next_task_state, dict):
                raise TaskRunError("Task State tasks must be objects.")
            if next_task_state.get("status") == "pending":
                return next_task_state
        return None

    raise TaskRunError(f"Task State has no completed Task: {completed_task_id}")


def _activate_next_task(
    *,
    state: dict[str, Any],
    next_task_state: dict[str, Any],
    next_task: Task,
    task_spec: TaskSpec,
    task_state_path: Path,
) -> None:
    run_directory = Path(state["run_directory"])
    task_directory = run_directory / "tasks" / next_task.task_id
    task_directory.mkdir(parents=True, exist_ok=True)
    context_path = task_directory / "context.json"
    artifact_paths = _artifact_paths(task_directory)

    context = _task_context(
        task_spec=task_spec,
        task=next_task,
        run_id=state["run_id"],
        run_directory=run_directory,
        task_spec_snapshot_path=Path(state["task_spec_snapshot_path"]),
        task_state_path=task_state_path,
        context_path=context_path,
        artifact_paths=artifact_paths,
    )
    _write_json(context_path, context)

    next_task_state["status"] = "active"
    next_task_state["phase"] = "ready_for_planning"
    next_task_state["iterations"] = 0
    next_task_state["artifacts"] = {
        name: str(path)
        for name, path in {"task_context": context_path, **artifact_paths}.items()
    }
    state["phase"] = "ready_for_planning"
    state["active_task_id"] = next_task.task_id
    state["active_task"] = {"id": next_task.task_id, "title": next_task.title}


def _new_run_id() -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def _artifact_paths(task_directory: Path) -> dict[str, Path]:
    return {
        "task_context": task_directory / "context.json",
        "planning": task_directory / "planning.json",
        "approved_plan": task_directory / "approved-plan.md",
        "implementation_result": task_directory / "implementation-result.json",
        "command_log": task_directory / "command.log",
        "review_log": task_directory / "review.log",
    }


def _first_task_context(
    *,
    task_spec: TaskSpec,
    run_id: str,
    run_directory: Path,
    task_spec_snapshot_path: Path,
    task_state_path: Path,
    context_path: Path,
    artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    return _task_context(
        task_spec=task_spec,
        task=task_spec.tasks[0],
        run_id=run_id,
        run_directory=run_directory,
        task_spec_snapshot_path=task_spec_snapshot_path,
        task_state_path=task_state_path,
        context_path=context_path,
        artifact_paths=artifact_paths,
    )


def _task_context(
    *,
    task_spec: TaskSpec,
    task: Task,
    run_id: str,
    run_directory: Path,
    task_spec_snapshot_path: Path,
    task_state_path: Path,
    context_path: Path,
    artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "target_repository": str(task_spec.target_repository),
        "run_directory": str(run_directory),
        "task_spec_snapshot_path": str(task_spec_snapshot_path),
        "task_state_path": str(task_state_path),
        "run": {
            "description": task_spec.description,
            "context": task_spec.context,
            "require_plan_approval": task_spec.require_plan_approval,
            "max_iterations": task_spec.max_iterations,
        },
        "task": {
            "id": task.task_id,
            "title": task.title,
            "prompt": task.prompt,
            "context": task.context,
        },
        "artifacts": {
            name: str(path)
            for name, path in {"task_context": context_path, **artifact_paths}.items()
        },
    }


def _initial_task_state(
    *,
    task_spec: TaskSpec,
    run_id: str,
    run_directory: Path,
    task_spec_snapshot_path: Path,
    task_state_path: Path,
    first_task_context_path: Path,
    artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    first_task = task_spec.tasks[0]
    return {
        "run_id": run_id,
        "phase": "ready_for_planning",
        "active_task_id": first_task.task_id,
        "active_task": {"id": first_task.task_id, "title": first_task.title},
        "target_repository": str(task_spec.target_repository),
        "run_directory": str(run_directory),
        "task_spec_snapshot_path": str(task_spec_snapshot_path),
        "task_state_path": str(task_state_path),
        "tasks": [
            {
                "id": task.task_id,
                "title": task.title,
                "status": "active" if index == 0 else "pending",
                "phase": "ready_for_planning" if index == 0 else "pending",
                "iterations": 0,
                "artifacts": (
                    {
                        name: str(path)
                        for name, path in {
                            "task_context": first_task_context_path,
                            **artifact_paths,
                        }.items()
                    }
                    if index == 0
                    else {}
                ),
            }
            for index, task in enumerate(task_spec.tasks)
        ],
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TaskRunError(f"Expected JSON object at {path}")
    return data


def _active_task_state(state: Mapping[str, Any]) -> dict[str, Any]:
    active_task_id = state.get("active_task_id")
    for task_state in state.get("tasks", []):
        if isinstance(task_state, dict) and task_state.get("id") == active_task_id:
            return task_state
    raise TaskRunError(f"Task State has no active Task: {active_task_id}")


def _task_artifacts(task_state: Mapping[str, Any]) -> dict[str, str]:
    artifacts = task_state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TaskRunError("Active Task State has no artifacts.")
    return artifacts


def _planner_thread(
    *,
    codex_client: Any,
    task_state: dict[str, Any],
    target_repository: Path,
    developer_instructions: str,
    model: str | None,
) -> Any:
    planner_thread_id = _planner_thread_id(task_state)
    thread_kwargs = {
        "approval_mode": ApprovalMode.auto_review,
        "cwd": str(target_repository),
        "developer_instructions": developer_instructions,
        "model": model,
        "sandbox": SandboxMode.read_only,
    }
    if planner_thread_id:
        return codex_client.thread_resume(planner_thread_id, **thread_kwargs)
    return codex_client.thread_start(**thread_kwargs)


def _run_planner_thread(
    *,
    thread: Any,
    turn_input: str,
    target_repository: Path,
    effort: str | None,
    model: str | None,
    output_schema: dict[str, Any],
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    usage_clock: UsageLimitClock | None,
    usage_sleep: UsageLimitSleeper | None,
) -> Any:
    return _run_codex_thread_with_usage_limit(
        role="planner",
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
        run=lambda: thread.run(
            turn_input,
            approval_mode=ApprovalMode.auto_review,
            cwd=str(target_repository),
            effort=_reasoning_effort(effort),
            model=model,
            output_schema=output_schema,
            sandbox_policy=ReadOnlySandboxPolicy(type="readOnly"),
        ),
    )


def _planner_thread_id(task_state: Mapping[str, Any]) -> str | None:
    threads = task_state.get("threads")
    if not isinstance(threads, dict):
        return None
    planner_thread_id = threads.get("planner")
    if planner_thread_id is None:
        return None
    if not isinstance(planner_thread_id, str) or not planner_thread_id.strip():
        raise TaskRunError("Planner Agent thread ID in Task State must be a string.")
    return planner_thread_id


def _persist_planner_thread_id(task_state: dict[str, Any], thread_id: Any) -> None:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise TaskRunError("Planner Agent thread did not return a usable thread ID.")
    threads = task_state.setdefault("threads", {})
    if not isinstance(threads, dict):
        raise TaskRunError("Task State field 'threads' must be a mapping.")
    threads["planner"] = thread_id


def _context_thread(
    *,
    codex_client: Any,
    task_state: dict[str, Any],
    target_repository: Path,
    developer_instructions: str,
    model: str | None,
) -> Any:
    context_thread_id = _context_thread_id(task_state)
    thread_kwargs = {
        "approval_mode": ApprovalMode.auto_review,
        "cwd": str(target_repository),
        "developer_instructions": developer_instructions,
        "model": model,
        "sandbox": SandboxMode.read_only,
    }
    if context_thread_id:
        return codex_client.thread_resume(context_thread_id, **thread_kwargs)
    return codex_client.thread_start(**thread_kwargs)


def _run_context_thread(
    *,
    thread: Any,
    turn_input: str,
    target_repository: Path,
    effort: str | None,
    model: str | None,
    output_schema: dict[str, Any],
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    usage_clock: UsageLimitClock | None,
    usage_sleep: UsageLimitSleeper | None,
) -> Any:
    return _run_codex_thread_with_usage_limit(
        role="context",
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
        run=lambda: thread.run(
            turn_input,
            approval_mode=ApprovalMode.auto_review,
            cwd=str(target_repository),
            effort=_reasoning_effort(effort),
            model=model,
            output_schema=output_schema,
            sandbox_policy=ReadOnlySandboxPolicy(type="readOnly"),
        ),
    )


def _context_thread_id(task_state: Mapping[str, Any]) -> str | None:
    threads = task_state.get("threads")
    if not isinstance(threads, dict):
        return None
    context_thread_id = threads.get("context")
    if context_thread_id is None:
        return None
    if not isinstance(context_thread_id, str) or not context_thread_id.strip():
        raise TaskRunError("Context Agent thread ID in Task State must be a string.")
    return context_thread_id


def _persist_context_thread_id(task_state: dict[str, Any], thread_id: Any) -> None:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise TaskRunError("Context Agent thread did not return a usable thread ID.")
    threads = task_state.setdefault("threads", {})
    if not isinstance(threads, dict):
        raise TaskRunError("Task State field 'threads' must be a mapping.")
    threads["context"] = thread_id


def _implementer_thread(
    *,
    codex_client: Any,
    task_state: dict[str, Any],
    target_repository: Path,
    developer_instructions: str,
    model: str | None,
) -> Any:
    implementer_thread_id = _implementer_thread_id(task_state)
    thread_kwargs = {
        "approval_mode": ApprovalMode.auto_review,
        "cwd": str(target_repository),
        "developer_instructions": developer_instructions,
        "model": model,
        "sandbox": SandboxMode.workspace_write,
    }
    if implementer_thread_id:
        return codex_client.thread_resume(implementer_thread_id, **thread_kwargs)
    return codex_client.thread_start(**thread_kwargs)


def _run_implementer_thread(
    *,
    thread: Any,
    turn_input: str,
    target_repository: Path,
    effort: str | None,
    model: str | None,
    output_schema: dict[str, Any],
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    usage_clock: UsageLimitClock | None,
    usage_sleep: UsageLimitSleeper | None,
) -> Any:
    return _run_codex_thread_with_usage_limit(
        role="implementer",
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
        run=lambda: thread.run(
            turn_input,
            approval_mode=ApprovalMode.auto_review,
            cwd=str(target_repository),
            effort=_reasoning_effort(effort),
            model=model,
            output_schema=output_schema,
            sandbox_policy=WorkspaceWriteSandboxPolicy(type="workspaceWrite"),
        ),
    )


def _implementer_thread_id(task_state: Mapping[str, Any]) -> str | None:
    threads = task_state.get("threads")
    if not isinstance(threads, dict):
        return None
    implementer_thread_id = threads.get("implementer")
    if implementer_thread_id is None:
        return None
    if not isinstance(implementer_thread_id, str) or not implementer_thread_id.strip():
        raise TaskRunError(
            "Implementer Agent thread ID in Task State must be a string."
        )
    return implementer_thread_id


def _persist_implementer_thread_id(task_state: dict[str, Any], thread_id: Any) -> None:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise TaskRunError(
            "Implementer Agent thread did not return a usable thread ID."
        )
    threads = task_state.setdefault("threads", {})
    if not isinstance(threads, dict):
        raise TaskRunError("Task State field 'threads' must be a mapping.")
    threads["implementer"] = thread_id


def _reviewer_thread(
    *,
    codex_client: Any,
    target_repository: Path,
    developer_instructions: str,
    model: str | None,
) -> Any:
    return codex_client.thread_start(
        approval_mode=ApprovalMode.deny_all,
        cwd=str(target_repository),
        developer_instructions=developer_instructions,
        model=model,
        sandbox=SandboxMode.read_only,
    )


def _run_reviewer_thread(
    *,
    thread: Any,
    turn_input: str,
    target_repository: Path,
    effort: str | None,
    model: str | None,
    output_schema: dict[str, Any],
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    usage_clock: UsageLimitClock | None,
    usage_sleep: UsageLimitSleeper | None,
) -> Any:
    return _run_codex_thread_with_usage_limit(
        role="reviewer",
        task_state_file=task_state_file,
        state=state,
        active_task_state=active_task_state,
        usage_clock=usage_clock,
        usage_sleep=usage_sleep,
        run=lambda: thread.run(
            turn_input,
            approval_mode=ApprovalMode.deny_all,
            cwd=str(target_repository),
            effort=_reasoning_effort(effort),
            model=model,
            output_schema=output_schema,
            sandbox_policy=ReadOnlySandboxPolicy(type="readOnly"),
        ),
    )


def _run_codex_thread_with_usage_limit(
    *,
    role: str,
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    usage_clock: UsageLimitClock | None,
    usage_sleep: UsageLimitSleeper | None,
    run: Callable[[], Any],
) -> Any:
    clock = usage_clock or _local_runtime_now
    sleeper = usage_sleep or time.sleep

    while True:
        try:
            return run()
        except Exception as exc:
            now = _runtime_datetime(clock())
            suggested_retry_at = _usage_limit_retry_at(exc, now)
            if suggested_retry_at is None:
                raise

            sleep_seconds = max(
                (suggested_retry_at - now).total_seconds(),
                0.0,
            )
            _record_usage_limit_wait(
                task_state_file=task_state_file,
                state=state,
                active_task_state=active_task_state,
                role=role,
                message=_exception_message(exc),
                detected_at=now,
                suggested_retry_at=suggested_retry_at,
                sleep_seconds=sleep_seconds,
            )
            sleeper(sleep_seconds)


def _usage_limit_retry_at(exc: Exception, now: datetime) -> datetime | None:
    message = _exception_message(exc)
    if not _looks_like_usage_limit(message):
        return None
    return _parse_retry_time(message, now)


def _looks_like_usage_limit(message: str) -> bool:
    normalized = message.lower()
    usage_markers = (
        "usage limit",
        "rate limit",
        "quota",
        "too many requests",
        "limit reached",
        "limit exceeded",
    )
    return any(marker in normalized for marker in usage_markers)


def _parse_retry_time(message: str, now: datetime) -> datetime | None:
    return (
        _parse_relative_retry_time(message, now)
        or _parse_absolute_retry_time(message, now)
        or _parse_time_of_day_retry_time(message, now)
    )


def _parse_relative_retry_time(message: str, now: datetime) -> datetime | None:
    retry_after_match = re.search(
        r"\bretry-after\s*[:=]\s*(?P<seconds>\d+(?:\.\d+)?)\b",
        message,
        flags=re.IGNORECASE,
    )
    if retry_after_match:
        return now + timedelta(seconds=float(retry_after_match.group("seconds")))

    relative_match = re.search(
        r"\b(?:in|after)\s+(?P<duration>(?:\d+(?:\.\d+)?\s*"
        r"(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)"
        r"(?:\s*(?:,|and)?\s*)?)+)",
        message,
        flags=re.IGNORECASE,
    )
    if not relative_match:
        return None

    seconds = 0.0
    for amount, unit in re.findall(
        r"(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)",
        relative_match.group("duration"),
        flags=re.IGNORECASE,
    ):
        seconds += float(amount) * _duration_unit_seconds(unit)

    if seconds <= 0:
        return None
    return now + timedelta(seconds=seconds)


def _duration_unit_seconds(unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"s", "sec", "secs", "second", "seconds"}:
        return 1.0
    if normalized in {"m", "min", "mins", "minute", "minutes"}:
        return 60.0
    if normalized in {"h", "hr", "hrs", "hour", "hours"}:
        return 60.0 * 60.0
    if normalized in {"d", "day", "days"}:
        return 60.0 * 60.0 * 24.0
    raise TaskRunError(f"Unknown usage-limit retry duration unit: {unit!r}.")


def _parse_absolute_retry_time(message: str, now: datetime) -> datetime | None:
    iso_match = re.search(
        r"\b(?P<date>\d{4}-\d{2}-\d{2})[ T]"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
        r"(?P<zone>\s*(?:Z|UTC|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if iso_match:
        zone = _normalized_datetime_zone(iso_match.group("zone"))
        timestamp = f"{iso_match.group('date')}T{iso_match.group('time')}{zone}"
        try:
            return _runtime_datetime(
                datetime.fromisoformat(timestamp),
                fallback_timezone=now.tzinfo,
            )
        except ValueError:
            return None

    month_match = re.search(
        r"\b(?P<timestamp>[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
        r"(?:,|\s+at)?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))\b",
        message,
        flags=re.IGNORECASE,
    )
    if not month_match:
        return None

    timestamp = re.sub(
        r"\s+at\s+",
        " ",
        month_match.group("timestamp").replace(",", ""),
        flags=re.IGNORECASE,
    )
    for format_string in (
        "%B %d %Y %I:%M:%S %p",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M:%S %p",
        "%b %d %Y %I:%M %p",
    ):
        try:
            parsed = datetime.strptime(timestamp, format_string)
        except ValueError:
            continue
        return parsed.replace(tzinfo=now.tzinfo)
    return None


def _parse_time_of_day_retry_time(message: str, now: datetime) -> datetime | None:
    time_match = re.search(
        r"\b(?:at|after)\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)"
        r"(?:\s*(?P<zone>UTC|Z|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if not time_match:
        return None

    time_text = _normalized_time_of_day(time_match.group("time"))
    for format_string in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(time_text, format_string)
        except ValueError:
            continue
        tzinfo = _timezone_from_retry_suffix(time_match.group("zone"), now.tzinfo)
        retry_at = datetime.combine(now.date(), parsed.time(), tzinfo=tzinfo)
        if retry_at <= now:
            retry_at += timedelta(days=1)
        return retry_at
    return None


def _normalized_datetime_zone(zone: str | None) -> str:
    if zone is None or not zone.strip():
        return ""
    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return "+00:00"
    if re.fullmatch(r"[+-]\d{4}", normalized):
        return f"{normalized[:3]}:{normalized[3:]}"
    return normalized


def _normalized_time_of_day(time_text: str) -> str:
    normalized = time_text.strip().upper().replace(".", "")
    return re.sub(r"(?<=\d)(AM|PM)$", r" \1", normalized)


def _timezone_from_retry_suffix(
    zone: str | None, fallback_timezone: tzinfo | None
) -> tzinfo:
    if zone is None or not zone.strip():
        return fallback_timezone or _local_runtime_now().tzinfo or UTC

    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return UTC
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", normalized):
        offset = normalized.replace(":", "")
        sign = 1 if offset[0] == "+" else -1
        hours = int(offset[1:3])
        minutes = int(offset[3:5])
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return fallback_timezone or _local_runtime_now().tzinfo or UTC


def _record_usage_limit_wait(
    *,
    task_state_file: Path,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    role: str,
    message: str,
    detected_at: datetime,
    suggested_retry_at: datetime,
    sleep_seconds: float,
) -> None:
    record = {
        "role": role,
        "detected_at": _format_runtime_timestamp(detected_at),
        "suggested_retry_at": _format_runtime_timestamp(suggested_retry_at),
        "sleep_seconds": sleep_seconds,
        "message": message,
    }
    _append_usage_limit_wait(state, record, "Task State")
    _append_usage_limit_wait(active_task_state, dict(record), "Active Task State")
    _write_json(task_state_file, state)


def _append_usage_limit_wait(
    owner: dict[str, Any], record: dict[str, Any], owner_name: str
) -> None:
    waits = owner.setdefault("usage_limit_waits", [])
    if not isinstance(waits, list):
        raise TaskRunError(f"{owner_name} field 'usage_limit_waits' must be a list.")
    waits.append(record)


def _exception_message(exc: Exception) -> str:
    message = str(exc)
    if message:
        return message
    if exc.args:
        return " ".join(str(arg) for arg in exc.args)
    return exc.__class__.__name__


def _runtime_datetime(
    value: datetime, *, fallback_timezone: tzinfo | None = None
) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    return value.replace(tzinfo=fallback_timezone or _local_runtime_now().tzinfo or UTC)


def _format_runtime_timestamp(value: datetime) -> str:
    return _runtime_datetime(value).isoformat()


def _local_runtime_now() -> datetime:
    return datetime.now().astimezone()


def _planner_turn_input(
    task_context_path: Path, task_context: Mapping[str, Any]
) -> str:
    task = task_context["task"]
    artifacts = task_context["artifacts"]
    return "\n".join(
        [
            "Plan the active Task.",
            "",
            f"Task ID: {task['id']}",
            f"Task title: {task['title']}",
            f"Task prompt: {task['prompt']}",
            f"Task context: {task.get('context') or 'None'}",
            "",
            f"Task context artifact: {task_context_path}",
            f"Planning artifact: {artifacts['planning']}",
            f"Approved Plan artifact: {artifacts['approved_plan']}",
        ]
    )


def _context_turn_input(
    *,
    questions: list[dict[str, Any]],
    task_context_path: Path,
    planning_artifact_path: Path,
) -> str:
    return "\n".join(
        [
            "Answer these Planner Agent questions from the Target Repository and task context.",
            "",
            f"Task context artifact: {task_context_path}",
            f"Planning artifact: {planning_artifact_path}",
            "",
            "Planner questions:",
            json.dumps(questions, indent=2, sort_keys=True),
        ]
    )


def _planner_follow_up_turn_input(
    *,
    task_context_path: Path,
    planning_artifact_path: Path,
    planner_questions: list[dict[str, Any]],
    context_answers: list[dict[str, Any]],
    human_answers: list[dict[str, Any]],
) -> str:
    latest_answer_batch = {
        "planner_questions": planner_questions,
        "context_answers": context_answers,
        "human_answers": human_answers,
    }
    return "\n".join(
        [
            "Continue planning the active Task using the latest answers.",
            "",
            f"Task context artifact: {task_context_path}",
            f"Planning artifact: {planning_artifact_path}",
            "",
            "Latest answer batch:",
            json.dumps(latest_answer_batch, indent=2, sort_keys=True),
        ]
    )


def _reviewer_turn_input(
    *,
    task_spec: TaskSpec,
    active_task_state: Mapping[str, Any],
    artifacts: Mapping[str, str],
    latest_test_status: Mapping[str, Any],
) -> str:
    active_task_id = active_task_state.get("id")
    task = next(
        (task for task in task_spec.tasks if task.task_id == active_task_id), None
    )
    if task is None:
        raise TaskRunError(f"Task Spec snapshot has no active Task: {active_task_id}")

    command_log_path = (
        latest_test_status.get("command_log_path") or artifacts["command_log"]
    )
    return "\n".join(
        [
            "Review the active Task after passing deterministic tests.",
            "",
            f"Task ID: {task.task_id}",
            f"Task title: {task.title}",
            f"Task prompt: {task.prompt}",
            f"Task context: {task.context or 'None'}",
            "",
            f"Task context artifact: {artifacts['task_context']}",
            f"Approved Plan artifact: {artifacts['approved_plan']}",
            f"Command log artifact: {command_log_path}",
            f"Review log artifact: {artifacts['review_log']}",
        ]
    )


def _reasoning_effort(effort: str | None) -> ReasoningEffort | None:
    if effort is None:
        return None
    return ReasoningEffort(effort)


def _parse_planner_output(turn_result: Any) -> dict[str, Any]:
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, str):
        try:
            parsed = json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise PlannerOutputError(
                "Planner Agent returned unparseable JSON."
            ) from exc
    elif isinstance(final_response, dict):
        parsed = final_response
    else:
        raise PlannerOutputError("Planner Agent did not return a JSON object.")

    if not isinstance(parsed, dict):
        raise PlannerOutputError("Planner Agent output must be a JSON object.")
    return parsed


def _parse_context_output(turn_result: Any) -> dict[str, Any]:
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, str):
        try:
            parsed = json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise ContextOutputError(
                "Context Agent returned unparseable JSON."
            ) from exc
    elif isinstance(final_response, dict):
        parsed = final_response
    else:
        raise ContextOutputError("Context Agent did not return a JSON object.")

    if not isinstance(parsed, dict):
        raise ContextOutputError("Context Agent output must be a JSON object.")
    return parsed


def _parse_implementer_output(turn_result: Any) -> dict[str, Any]:
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, str):
        try:
            parsed = json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise ImplementerOutputError(
                "Implementer Agent returned unparseable JSON."
            ) from exc
    elif isinstance(final_response, dict):
        parsed = final_response
    else:
        raise ImplementerOutputError("Implementer Agent did not return a JSON object.")

    if not isinstance(parsed, dict):
        raise ImplementerOutputError("Implementer Agent output must be a JSON object.")
    return parsed


def _parse_reviewer_output(turn_result: Any) -> dict[str, Any]:
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, str):
        try:
            parsed = json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise ReviewerOutputError(
                "Reviewer Agent returned unparseable JSON."
            ) from exc
    elif isinstance(final_response, dict):
        parsed = final_response
    else:
        raise ReviewerOutputError("Reviewer Agent did not return a JSON object.")

    if not isinstance(parsed, dict):
        raise ReviewerOutputError("Reviewer Agent output must be a JSON object.")
    return parsed


def _reviewer_output_json_text(
    turn_result: Any, reviewer_output: Mapping[str, Any]
) -> str:
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, str):
        return final_response
    return json.dumps(reviewer_output)


def _check_planner_output_for_routing(planner_output: Mapping[str, Any]) -> None:
    status = planner_output.get("status")
    if status not in PLANNER_STATUSES:
        raise PlannerOutputError(f"Unknown Planner Agent status: {status!r}.")
    if status == "planned":
        plan_markdown = planner_output.get("plan_markdown")
        if not isinstance(plan_markdown, str) or not plan_markdown.strip():
            raise PlannerOutputError(
                "Planner Agent status 'planned' requires plan_markdown."
            )
    if status == "needs_answers":
        questions = planner_output.get("questions")
        if not isinstance(questions, list) or not questions:
            raise PlannerOutputError(
                "Planner Agent status 'needs_answers' requires questions."
            )
        seen_question_ids: set[str] = set()
        for question in questions:
            if not isinstance(question, dict):
                raise PlannerOutputError("Planner Agent questions must be objects.")
            question_id = question.get("id")
            if not isinstance(question_id, str) or not question_id.strip():
                raise PlannerOutputError("Planner Agent questions require an id.")
            if question_id in seen_question_ids:
                raise PlannerOutputError(
                    f"Planner Agent question ID is duplicated: {question_id!r}."
                )
            seen_question_ids.add(question_id)
            question_text = question.get("question")
            if not isinstance(question_text, str) or not question_text.strip():
                raise PlannerOutputError(
                    "Planner Agent questions require question text."
                )


def _check_context_output_for_routing(
    context_output: Mapping[str, Any], questions: list[dict[str, Any]]
) -> None:
    answers = context_output.get("answers")
    if not isinstance(answers, list):
        raise ContextOutputError("Context Agent output requires answers.")

    question_ids = {question["id"] for question in questions}
    seen_answer_ids: set[str] = set()
    for answer in answers:
        if not isinstance(answer, dict):
            raise ContextOutputError("Context Agent answers must be objects.")
        question_id = answer.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ContextOutputError("Context Agent answers require question_id.")
        if question_id not in question_ids:
            raise ContextOutputError(
                f"Context Agent answered an unknown question_id: {question_id!r}."
            )
        if question_id in seen_answer_ids:
            raise ContextOutputError(
                f"Context Agent answer is duplicated: {question_id!r}."
            )
        seen_answer_ids.add(question_id)

        status = answer.get("status")
        if status not in CONTEXT_ANSWER_STATUSES:
            raise ContextOutputError(
                f"Unknown Context Agent answer status: {status!r}."
            )
        reason = answer.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ContextOutputError("Context Agent answers require a reason.")
        if status == "answered":
            answer_text = answer.get("answer")
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise ContextOutputError(
                    "Context Agent answered status requires answer."
                )

    if seen_answer_ids != question_ids:
        raise ContextOutputError(
            "Context Agent must answer or mark every planner question."
        )


def _check_reviewer_output_for_routing(reviewer_output: Mapping[str, Any]) -> None:
    status = reviewer_output.get("status")
    if status not in REVIEWER_STATUSES:
        raise ReviewerOutputError(f"Unknown Reviewer Agent status: {status!r}.")

    summary = reviewer_output.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewerOutputError("Reviewer Agent output requires summary.")

    for field in ("blocking_issues", "requested_changes", "non_blocking_issues"):
        issues = reviewer_output.get(field)
        if not isinstance(issues, list):
            raise ReviewerOutputError(f"Reviewer Agent output requires {field}.")
        for issue in issues:
            if not isinstance(issue, dict):
                raise ReviewerOutputError(
                    f"Reviewer Agent {field} entries must be objects."
                )


def _check_human_answers_for_routing(
    human_answers: Any, unresolved_questions: list[dict[str, Any]]
) -> None:
    if not isinstance(human_answers, list):
        raise HumanAnswerError("Human answer provider must return a list of answers.")

    unresolved_question_ids = {question["id"] for question in unresolved_questions}
    seen_answer_ids: set[str] = set()
    for answer in human_answers:
        if not isinstance(answer, dict):
            raise HumanAnswerError("Human answers must be objects.")
        question_id = answer.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise HumanAnswerError("Human answers require question_id.")
        if question_id not in unresolved_question_ids:
            raise HumanAnswerError(
                f"Human answer references an unknown question_id: {question_id!r}."
            )
        if question_id in seen_answer_ids:
            raise HumanAnswerError(f"Human answer is duplicated: {question_id!r}.")
        seen_answer_ids.add(question_id)

        answer_text = answer.get("answer")
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise HumanAnswerError("Human answers require answer text.")

    if seen_answer_ids != unresolved_question_ids:
        raise HumanAnswerError(
            "Human answer provider must answer every unresolved question."
        )


def _planner_questions(planner_output: Mapping[str, Any]) -> list[dict[str, Any]]:
    questions = planner_output["questions"]
    if not isinstance(questions, list):
        raise PlannerOutputError(
            "Planner Agent status 'needs_answers' requires questions."
        )
    return questions


def _latest_planner_output(planning_artifact_path: Path) -> dict[str, Any]:
    planning_artifact = _planning_artifact(planning_artifact_path)
    planner_outputs = planning_artifact["planner_outputs"]
    if not planner_outputs:
        raise TaskRunError(
            "Saved planning phase has no Planner Agent output in the planning artifact."
        )
    planner_output = planner_outputs[-1]
    if not isinstance(planner_output, dict):
        raise TaskRunError("Saved Planner Agent output must be a JSON object.")
    return planner_output


def _context_answers(context_output: Mapping[str, Any]) -> list[dict[str, Any]]:
    answers = context_output["answers"]
    if not isinstance(answers, list):
        raise ContextOutputError("Context Agent output requires answers.")
    return answers


def _unresolved_questions_for_human(
    questions: list[dict[str, Any]], context_answers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    questions_by_id = {question["id"]: question for question in questions}
    unresolved_questions: list[dict[str, Any]] = []
    for answer in context_answers:
        if answer["status"] != "unresolved":
            continue
        question = dict(questions_by_id[answer["question_id"]])
        question["unresolved_reason"] = answer["reason"]
        unresolved_questions.append(question)
    return unresolved_questions


def _append_planner_output(path: Path, planner_output: dict[str, Any]) -> None:
    planning_artifact = _planning_artifact(path)

    planning_artifact["planner_outputs"].append(planner_output)
    _write_json(path, planning_artifact)


def _append_answer_batch(
    path: Path,
    *,
    planner_questions: list[dict[str, Any]],
    context_answers: list[dict[str, Any]],
    human_answers: list[dict[str, Any]],
) -> None:
    planning_artifact = _planning_artifact(path)
    planning_artifact["answer_batches"].append(
        {
            "planner_questions": planner_questions,
            "context_answers": context_answers,
            "human_answers": human_answers,
        }
    )
    _write_json(path, planning_artifact)


def _append_review_output(path: Path, reviewer_output_json: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as review_log:
        review_log.write(reviewer_output_json)
        if not reviewer_output_json.endswith("\n"):
            review_log.write("\n")


def _write_approved_plan_candidate(path: Path, plan_markdown: str) -> None:
    content = plan_markdown if plan_markdown.endswith("\n") else f"{plan_markdown}\n"
    path.write_text(content, encoding="utf-8")


def _open_approved_plan_in_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise TaskRunError(
            "Plan approval requires EDITOR, VISUAL, or an injected Approved Plan editor."
        )
    subprocess.run([*shlex.split(editor), str(path)], check=True)


def _confirm_approved_plan(path: Path) -> bool:
    response = input(f"Approve Approved Plan at {path}? [y/N] ")
    return response.strip().lower() in {"y", "yes"}


def _record_plan_approval(
    *,
    state: dict[str, Any],
    active_task_state: dict[str, Any],
    planning_artifact_path: Path,
    approved_plan_path: Path,
    status: str,
    mode: str,
) -> None:
    timestamp_field = "approved_at" if status == "approved" else "declined_at"
    approval = {
        "status": status,
        "mode": mode,
        "approved_plan_path": str(approved_plan_path),
        timestamp_field: _utc_timestamp(),
    }

    state["phase"] = (
        "plan_approved" if status == "approved" else "plan_approval_declined"
    )
    active_task_state["phase"] = state["phase"]
    active_task_state["plan_approval"] = approval

    planning_artifact = _planning_artifact(planning_artifact_path)
    planning_artifact["approved_plan"] = {
        "path": str(approved_plan_path),
        "approval": approval,
    }
    _write_json(planning_artifact_path, planning_artifact)


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _planning_artifact(path: Path) -> dict[str, Any]:
    if path.exists():
        planning_artifact = _read_json(path)
    else:
        planning_artifact = {}

    planner_outputs = planning_artifact.setdefault("planner_outputs", [])
    if not isinstance(planner_outputs, list):
        raise TaskRunError("Planning artifact field 'planner_outputs' must be a list.")

    answer_batches = planning_artifact.setdefault("answer_batches", [])
    if not isinstance(answer_batches, list):
        raise TaskRunError("Planning artifact field 'answer_batches' must be a list.")

    return planning_artifact
