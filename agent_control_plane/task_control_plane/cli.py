from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from collections.abc import Sequence
from typing import Any

from agent_control_plane.task_control_plane.controller import (
    TaskRunError,
    resume_task_run,
    start_task_run,
)
from agent_control_plane.task_control_plane.task_spec import TaskSpecError


def main(
    argv: Sequence[str] | None = None,
    *,
    codex_client_factory: Callable[[], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="task-control-plane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Start a Task Run from an explicit Task Spec path."
    )
    run_parser.add_argument("task_spec_path", help="Path to the Task Spec YAML file.")

    resume_parser = subparsers.add_parser(
        "resume", help="Resume an existing Task Run from saved Task State."
    )
    resume_parser.add_argument("run_id", help="Task Run ID to resume.")

    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args.task_spec_path)
    if args.command == "resume":
        return _resume(args.run_id, codex_client_factory=codex_client_factory)
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run(task_spec_path: str) -> int:
    try:
        task_run = start_task_run(task_spec_path)
    except (OSError, TaskSpecError, TaskRunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Started Task Run: {task_run.run_id}")
    print(f"Run directory: {task_run.run_directory}")
    print(f"Task State: {task_run.task_state_path}")
    print(f"First task context: {task_run.first_task_context_path}")
    return 0


def _resume(
    run_id: str, *, codex_client_factory: Callable[[], Any] | None = None
) -> int:
    try:
        codex_client = (codex_client_factory or _default_codex_client_factory)()
        result = resume_task_run(run_id, codex_client)
    except (OSError, TaskSpecError, TaskRunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Resumed Task Run: {run_id}")
    print(f"Status: {result.get('status')}")
    return 0


def _default_codex_client_factory() -> Any:
    from openai_codex import Codex

    return Codex()
