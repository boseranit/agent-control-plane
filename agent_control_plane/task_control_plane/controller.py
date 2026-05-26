from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_control_plane.task_control_plane.task_spec import TaskSpec, load_task_spec


@dataclass(frozen=True)
class TaskRun:
    run_id: str
    run_directory: Path
    task_spec_snapshot_path: Path
    task_state_path: Path
    first_task_context_path: Path


class TaskRunError(RuntimeError):
    """Raised when a Task Run cannot be started."""


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
