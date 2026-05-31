from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.boundary_audit import git_snapshot
from agent_control_plane.control_plane.json_artifacts import (
    file_sha256,
    read_json_object,
    read_jsonl,
    write_json,
    write_text,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    load_research_run_spec,
)


BLOCKER_OUTCOMES = {"blocked", "prerequisites_failed"}
FAILURE_OUTCOMES = {"invalid", "run_failed", "prerequisites_failed"}
COMPLETED_OUTCOMES = {
    "completed_rejected",
    "completed_inconclusive",
    "completed_candidate",
}
CONTEXT_OUTPUT_NAMES = {"context_pack.md", "context_summary.json"}
METRIC_ARTIFACT_NAMES = {
    "metrics.json",
    "command_metrics.json",
    "confirmatory_evaluation_result.json",
}
LEDGER_PREREQUISITE_SUCCESS_EVENT_TYPES = {
    "prerequisite_completed",
    "prerequisite_passed",
    "prerequisite_succeeded",
}
LEDGER_SUCCESS_STATUSES = {"completed", "passed", "success", "succeeded"}
LEDGER_FAILURE_STATUSES = {"error", "failed", "failure"}


@dataclass(frozen=True)
class ContextOutputs:
    context_pack_path: Path
    context_summary_path: Path
    context_pack_text: str
    context_summary: dict[str, Any]


def write_context_outputs(
    run_directory: str | Path,
    output_directory: str | Path | None = None,
    current_experiment_id: str | None = None,
) -> ContextOutputs:
    run_dir = Path(run_directory)
    output_dir = Path(output_directory) if output_directory is not None else run_dir
    spec = load_research_run_spec(run_dir / "research_run_spec.yaml")
    state = read_json_object(run_dir / "state.json")
    ledger_events = read_jsonl(run_dir / "ledger.jsonl")
    snapshot = git_snapshot(spec.target_repository)
    active_experiment_ids = _active_experiment_ids(state, current_experiment_id)

    prior_synthesis = _build_prior_synthesis(
        run_dir=run_dir,
        state=state,
        ledger_events=ledger_events,
        active_experiment_ids=active_experiment_ids,
    )

    summary: dict[str, Any] = {
        "artifact_kind": "context_summary",
        "controller_generated": True,
        "current_experiment_id": (
            current_experiment_id or _state_active_experiment_id(state)
        ),
        "spec": {
            "research_run_id": spec.research_run_id,
            "max_experiments": spec.max_experiments,
            "stop_on_prerequisites_failed": spec.stop_on_prerequisites_failed,
            "research_brief": spec.research_brief,
        },
        "budget": {
            "name": spec.budget,
            "month_start": spec.selected_budget.month_start,
            "month_end": spec.selected_budget.month_end,
            "max_runtime_minutes": spec.selected_budget.max_runtime_minutes,
            "default_command_timeout_seconds": (
                spec.selected_budget.default_command_timeout_seconds
            ),
        },
        "data_root": str(spec.data_root),
        "git": {
            "repo_root": str(spec.target_repository),
            "head": snapshot.head,
            "status_text": snapshot.status_porcelain or "clean",
            "changed_files": sorted(snapshot.changed_files),
        },
        "ledger_history": ledger_events,
        "artifact_inventory": _artifact_inventory(run_dir),
        "prior_synthesis": prior_synthesis,
    }
    text = _render_context_pack(summary)

    context_pack_path = output_dir / "context_pack.md"
    context_summary_path = output_dir / "context_summary.json"
    write_text(context_pack_path, text)
    write_json(context_summary_path, summary)

    return ContextOutputs(
        context_pack_path=context_pack_path,
        context_summary_path=context_summary_path,
        context_pack_text=text,
        context_summary=summary,
    )


def _build_prior_synthesis(
    *,
    run_dir: Path,
    state: dict[str, Any],
    ledger_events: list[dict[str, Any]],
    active_experiment_ids: set[str],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    completed_outcomes: list[dict[str, Any]] = []
    completed_prerequisites: list[dict[str, Any]] = []
    metric_history: list[dict[str, Any]] = []

    experiment_dirs = _experiment_dirs(run_dir, state)
    terminal_experiment_ids = {
        experiment_id
        for experiment_id, experiment_dir in experiment_dirs
        if (experiment_dir / "summary.json").exists()
    }
    excluded_active_ids = active_experiment_ids - terminal_experiment_ids

    for experiment_id, experiment_dir in experiment_dirs:
        summary_path = experiment_dir / "summary.json"
        if experiment_id in excluded_active_ids:
            continue
        if summary_path.exists():
            terminal_summary = read_json_object(summary_path)
            outcome = terminal_summary.get("outcome")
            if outcome in BLOCKER_OUTCOMES:
                blockers.append(_outcome_record(experiment_id, terminal_summary))
            if outcome in FAILURE_OUTCOMES:
                failures.append(_outcome_record(experiment_id, terminal_summary))
            if outcome in COMPLETED_OUTCOMES:
                completed_outcomes.append(
                    {
                        "experiment_id": experiment_id,
                        "outcome": outcome,
                        "reason": terminal_summary.get("outcome_reason"),
                    }
                )

        data_audit_path = experiment_dir / "data_audit.json"
        if data_audit_path.exists():
            data_audit = read_json_object(data_audit_path)
            if data_audit.get("passed") is True:
                completed_prerequisites.append(
                    {
                        "experiment_id": experiment_id,
                        "source": "data_audit.json",
                        "reason": data_audit.get("outcome_reason"),
                    }
                )
        metric_history.extend(
            _metric_history_for_experiment(experiment_id, experiment_dir)
        )

    completed_prerequisites.extend(
        _ledger_completed_prerequisites(
            ledger_events,
            excluded_experiment_ids=excluded_active_ids,
        )
    )

    return {
        "blockers": blockers,
        "repeated_blockers": _repeated_blockers(blockers),
        "failures": failures,
        "completed_outcomes": completed_outcomes,
        "completed_prerequisites": completed_prerequisites,
        "metric_history": sorted(
            metric_history,
            key=lambda item: (
                item["experiment_id"],
                item["source"],
                item["metric_path"],
            ),
        ),
    }


def _artifact_inventory(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(
        run_dir.rglob("*"), key=lambda item: item.relative_to(run_dir).as_posix()
    ):
        if not path.is_file() or path.name in CONTEXT_OUTPUT_NAMES:
            continue
        records.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
            }
        )
    return records


def _active_experiment_ids(
    state: dict[str, Any],
    current_experiment_id: str | None,
) -> set[str]:
    active_ids = set()
    if isinstance(current_experiment_id, str) and current_experiment_id.strip():
        active_ids.add(current_experiment_id)
    state_active_id = _state_active_experiment_id(state)
    if state_active_id is not None:
        active_ids.add(state_active_id)
    return active_ids


def _state_active_experiment_id(state: dict[str, Any]) -> str | None:
    active_experiment_id = state.get("active_experiment_id")
    if isinstance(active_experiment_id, str) and active_experiment_id.strip():
        return active_experiment_id
    return None


def _repeated_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[str]] = {}
    for blocker in blockers:
        experiment_id = blocker["experiment_id"]
        for kind, field in (
            ("failure_classification", "failure_classification"),
            ("reason", "reason"),
        ):
            value = blocker.get(field)
            if isinstance(value, str) and value.strip():
                buckets.setdefault((kind, value), []).append(experiment_id)

    return [
        {
            "kind": kind,
            "value": value,
            "count": len(experiment_ids),
            "experiment_ids": experiment_ids,
        }
        for (kind, value), experiment_ids in sorted(buckets.items())
        if len(experiment_ids) >= 2
    ]


def _metric_history_for_experiment(
    experiment_id: str,
    experiment_dir: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sorted(METRIC_ARTIFACT_NAMES):
        path = experiment_dir / source
        if not path.exists():
            continue
        data = read_json_object(path)
        for metric_path, value in _numeric_leaves(data):
            records.append(
                {
                    "experiment_id": experiment_id,
                    "source": source,
                    "metric_path": metric_path,
                    "value": value,
                }
            )
    return records


def _numeric_leaves(data: Any, prefix: str = "") -> list[tuple[str, int | float]]:
    if isinstance(data, dict):
        leaves: list[tuple[str, int | float]] = []
        for key in sorted(data):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.extend(_numeric_leaves(data[key], child_prefix))
        return leaves
    if isinstance(data, list):
        leaves = []
        for index, item in enumerate(data):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            leaves.extend(_numeric_leaves(item, child_prefix))
        return leaves
    if isinstance(data, bool):
        return []
    if isinstance(data, int | float):
        return [(prefix, data)]
    return []


def _ledger_completed_prerequisites(
    ledger_events: list[dict[str, Any]],
    *,
    excluded_experiment_ids: set[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in ledger_events:
        if not _is_completed_prerequisite_ledger_event(event):
            continue
        prerequisite = event.get("prerequisite") or event.get("name")
        if not isinstance(prerequisite, str) or not prerequisite:
            continue
        experiment_id = event.get("experiment_id")
        if isinstance(experiment_id, str) and experiment_id in excluded_experiment_ids:
            continue
        records.append(
            {
                "experiment_id": experiment_id,
                "source": "ledger",
                "reason": prerequisite,
            }
        )
    return records


def _is_completed_prerequisite_ledger_event(event: dict[str, Any]) -> bool:
    status = event.get("status")
    if isinstance(status, str) and status.lower() in LEDGER_FAILURE_STATUSES:
        return False
    if event.get("passed") is False or event.get("success") is False:
        return False

    event_type = event.get("event_type")
    if event_type in LEDGER_PREREQUISITE_SUCCESS_EVENT_TYPES:
        return True
    if event.get("passed") is True or event.get("success") is True:
        return True
    return isinstance(status, str) and status.lower() in LEDGER_SUCCESS_STATUSES


def _experiment_dirs(run_dir: Path, state: dict[str, Any]) -> list[tuple[str, Path]]:
    experiments_dir = run_dir / "experiments"
    found: dict[str, Path] = {}
    experiments = state.get("experiments")
    if isinstance(experiments, dict):
        for experiment_id, experiment_state in experiments.items():
            if not isinstance(experiment_id, str):
                continue
            if isinstance(experiment_state, dict):
                experiment_directory = experiment_state.get("experiment_directory")
                if isinstance(experiment_directory, str) and experiment_directory:
                    found[experiment_id] = Path(experiment_directory)

    if experiments_dir.is_dir():
        for path in experiments_dir.iterdir():
            if path.is_dir():
                found.setdefault(path.name, path)

    return [(experiment_id, found[experiment_id]) for experiment_id in sorted(found)]


def _outcome_record(
    experiment_id: str,
    terminal_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "outcome": terminal_summary.get("outcome"),
        "reason": terminal_summary.get("outcome_reason"),
        "failed_stage": terminal_summary.get("failed_stage"),
        "failure_classification": terminal_summary.get("failure_classification"),
    }


def _render_context_pack(summary: dict[str, Any]) -> str:
    spec = summary["spec"]
    budget = summary["budget"]
    git = summary["git"]
    prior = summary["prior_synthesis"]
    lines = [
        "# Research Context Pack",
        "",
        "## Spec",
        f"- run id: {spec['research_run_id']}",
        f"- max experiments: {spec['max_experiments']}",
        f"- stop on prerequisites failed: {spec['stop_on_prerequisites_failed']}",
        "- brief:",
        spec["research_brief"].rstrip(),
        "",
        "## Research Budget",
        f"- name: {budget['name']}",
        f"- month window: {budget['month_start']}..{budget['month_end']}",
        f"- runtime minutes: {budget['max_runtime_minutes']}",
        f"- default timeout seconds: {budget['default_command_timeout_seconds']}",
        "",
        "## Repository",
        f"- data root: {summary['data_root']}",
        f"- repo root: {git['repo_root']}",
        f"- git head: {git['head']}",
        "- git status:",
        git["status_text"].rstrip(),
        "- changed files:",
        *_list_lines(git["changed_files"]),
        "",
        "## Artifact Inventory",
        *_json_lines(summary["artifact_inventory"]),
        "",
        "## Ledger History",
        *_json_lines(summary["ledger_history"]),
        "",
        "## Prior Synthesis",
        "### Blockers",
        *_json_lines(prior["blockers"]),
        "### Repeated Blockers",
        *_json_lines(prior["repeated_blockers"]),
        "### Failures",
        *_json_lines(prior["failures"]),
        "### Completed Outcomes",
        *_json_lines(prior["completed_outcomes"]),
        "### Completed Prerequisites",
        *_json_lines(prior["completed_prerequisites"]),
        "### Metric History",
        *_json_lines(prior["metric_history"]),
        "",
    ]
    return "\n".join(lines) + "\n"


def _list_lines(items: list[Any]) -> list[str]:
    if not items:
        return ["- none"]
    return [f"- {item}" for item in items]


def _json_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    return [
        f"- {json.dumps(item, separators=(',', ':'), sort_keys=True)}" for item in items
    ]
