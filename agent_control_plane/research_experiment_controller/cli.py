from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_control_plane.research_experiment_controller.controller import (
    ResearchRunError,
    start_research_run,
)
from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
    run_research_shell,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    ResearchRunSpecError,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-experiment-controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Start a Research Run from a Research Run Spec."
    )
    run_parser.add_argument(
        "research_run_spec_path", help="Path to a Research Run Spec YAML file."
    )
    run_parser.add_argument(
        "--runtime-root",
        default="runs",
        help="Runtime root for Research Run directories.",
    )

    resume_parser = subparsers.add_parser(
        "resume", help="Resume an existing Research Run through the Durable Shell."
    )
    resume_parser.add_argument("research_run_id", help="Research Run ID to resume.")
    resume_parser.add_argument(
        "--runtime-root",
        default="runs",
        help="Runtime root for Research Run directories.",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args.research_run_spec_path, runtime_root=args.runtime_root)
    if args.command == "resume":
        return _resume(args.research_run_id, runtime_root=args.runtime_root)
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run(research_run_spec_path: str, *, runtime_root: str | Path = "runs") -> int:
    try:
        research_run = start_research_run(
            research_run_spec_path,
            runtime_root=runtime_root,
        )
    except (OSError, ResearchRunError, ResearchRunSpecError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Started Research Run: {research_run.research_run_id}")
    print(f"Run directory: {research_run.run_directory}")
    print(f"Research Run Spec: {research_run.spec_snapshot_path}")
    print(f"Research State: {research_run.state_path}")
    return 0


def _resume(research_run_id: str, *, runtime_root: str | Path = "runs") -> int:
    try:
        result = asyncio.run(
            run_research_shell(
                ResearchRunInput(
                    research_run_id=research_run_id,
                    runtime_root=str(runtime_root),
                )
            )
        )
    except (OSError, ResearchRunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Resumed Research Run: {research_run_id}")
    print(f"Status: {result.get('status')}")
    return 0
