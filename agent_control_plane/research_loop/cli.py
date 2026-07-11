from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .loop import LoopConfig, ResearchLoop
from .mirror import Mirror, NoOpMirror
from .records import (
    next_experiment_id,
    read_experiment_result,
    ready_hypotheses,
    record_root,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "status":
        return _status(args)
    if args.command == "leaderboard":
        return _leaderboard(args)
    parser.print_help()
    return 2


def _run(args: argparse.Namespace) -> int:
    mirror_enabled = args.mlflow_uri is not None or args.mlflow_experiment is not None
    with _open_runtime() as runtime:
        loop = ResearchLoop(
            LoopConfig(
                repo=Path(args.repo),
                slug=args.slug,
                max_experiments=args.max_experiments,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                mirror_tracking_uri=args.mlflow_uri,
                mirror_experiment_name=args.mlflow_experiment,
            ),
            runtime,
            mirror=_build_mirror(mirror_enabled),
        )
        summary = loop.run()
    print(f"stop_reason: {summary.stop_reason}")
    print(f"experiments_completed: {summary.experiments_completed}")
    print(f"reported_failures: {summary.reported_failures}")
    return 0


def _status(args: argparse.Namespace) -> int:
    root = record_root(Path(args.repo), args.slug)
    print(f"next_experiment_id: {next_experiment_id(root)}")
    ready = ready_hypotheses(root)
    if ready:
        for doc in ready:
            print(f"ready: {doc.frontmatter.id} {doc.frontmatter.slug}")
    else:
        print("ready: -")
    return 0


def _leaderboard(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    rows: list[tuple[str, str, str, float, Optional[float]]] = []
    for result_path in sorted(repo.glob("eda/*/results/EXP-*-result.json")):
        slug = result_path.parents[1].name
        exp_id = result_path.name.removesuffix("-result.json")
        result = read_experiment_result(result_path.parents[1], exp_id)
        rows.append(
            (
                slug,
                result.exp_id,
                result.verdict or "inconclusive",
                result.metrics.sharpe,
                result.bh_adjusted_p,
            )
        )
    rows.sort(key=lambda row: (row[2] != "survived", row[0], row[1]))
    for slug, exp_id, verdict, sharpe, adjusted_p in rows:
        adjusted = "-" if adjusted_p is None else f"{adjusted_p:g}"
        print(f"{slug} {exp_id} {verdict} sharpe={sharpe:g} bh_adjusted_p={adjusted}")
    return 0


def _open_runtime():
    from .adapters.codex import open_codex_runtime

    return open_codex_runtime()


def _build_mirror(enabled: bool) -> Mirror:
    if not enabled:
        return NoOpMirror()
    from .adapters.mlflow import MLflowMirror

    return MLflowMirror()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="start or resume a research loop")
    run.add_argument("--repo", required=True)
    run.add_argument("--slug", required=True)
    run.add_argument("--max-experiments", type=int, default=1)
    run.add_argument("--model", default="gpt-5-codex")
    run.add_argument("--reasoning-effort", default="high")
    run.add_argument("--mlflow-uri")
    run.add_argument("--mlflow-experiment")

    status = subparsers.add_parser("status", help="show committed-record state")
    status.add_argument("--repo", required=True)
    status.add_argument("--slug", required=True)

    leaderboard = subparsers.add_parser(
        "leaderboard",
        help="scan eda/*/results/*.json",
    )
    leaderboard.add_argument("--repo", required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
