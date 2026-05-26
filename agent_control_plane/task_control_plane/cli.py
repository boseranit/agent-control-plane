from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agent_control_plane.task_control_plane.controller import (
    TaskRunError,
    start_task_run,
)
from agent_control_plane.task_control_plane.task_spec import TaskSpecError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="task-control-plane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Start a Task Run from an explicit Task Spec path."
    )
    run_parser.add_argument("task_spec_path", help="Path to the Task Spec YAML file.")

    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args.task_spec_path)
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
