from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode
from openai_codex.generated.v2_all import (
    ReadOnlySandboxPolicy,
    ReasoningEffort,
    SandboxMode,
)

from agent_control_plane.task_control_plane.task_spec import TaskSpec, load_task_spec


PACKAGE_DIRECTORY = Path(__file__).parent
PLANNER_PROMPT_PATH = PACKAGE_DIRECTORY / "prompts" / "planner-agent.md"
PLANNER_OUTPUT_SCHEMA_PATH = (
    PACKAGE_DIRECTORY / "schemas" / "planner-output.schema.json"
)
PLANNER_STATUSES = frozenset({"planned", "needs_answers"})


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


def plan_active_task(task_state_path: str | Path, codex_client: Any) -> dict[str, Any]:
    task_state_file = Path(task_state_path)
    state = _read_json(task_state_file)
    active_task_state = _active_task_state(state)
    artifacts = _task_artifacts(active_task_state)

    task_spec = load_task_spec(state["task_spec_snapshot_path"])
    target_repository = Path(state["target_repository"]).resolve()
    task_context_path = Path(artifacts["task_context"])
    task_context = _read_json(task_context_path)

    developer_instructions = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
    planner_output_schema = _read_json(PLANNER_OUTPUT_SCHEMA_PATH)
    thread = _planner_thread(
        codex_client=codex_client,
        task_state=active_task_state,
        target_repository=target_repository,
        developer_instructions=developer_instructions,
        model=task_spec.codex.model,
    )

    _persist_planner_thread_id(active_task_state, thread.id)
    _write_json(task_state_file, state)

    turn_result = thread.run(
        _planner_turn_input(task_context_path, task_context),
        approval_mode=ApprovalMode.auto_review,
        cwd=str(target_repository),
        effort=_reasoning_effort(task_spec.codex.effort),
        model=task_spec.codex.model,
        output_schema=planner_output_schema,
        sandbox_policy=ReadOnlySandboxPolicy(type="readOnly"),
    )
    planner_output = _parse_planner_output(turn_result)
    _check_planner_output_for_routing(planner_output)
    _append_planner_output(Path(artifacts["planning"]), planner_output)

    status = planner_output["status"]
    if status == "planned":
        state["phase"] = "plan_ready"
        active_task_state["phase"] = "plan_ready"
    elif status == "needs_answers":
        state["phase"] = "planning_needs_answers"
        active_task_state["phase"] = "planning_needs_answers"

    _write_json(task_state_file, state)
    return planner_output


def _require_clean_target_repository(target_repository: Path) -> None:
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
            f"Target Repository must be clean before starting a Task Run: {target_repository}"
        )


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
    first_task = task_spec.tasks[0]
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
            "id": first_task.task_id,
            "title": first_task.title,
            "prompt": first_task.prompt,
            "context": first_task.context,
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


def _append_planner_output(path: Path, planner_output: dict[str, Any]) -> None:
    if path.exists():
        planning_artifact = _read_json(path)
    else:
        planning_artifact = {"planner_outputs": []}

    planner_outputs = planning_artifact.setdefault("planner_outputs", [])
    if not isinstance(planner_outputs, list):
        raise TaskRunError("Planning artifact field 'planner_outputs' must be a list.")
    planner_outputs.append(planner_output)
    _write_json(path, planning_artifact)
