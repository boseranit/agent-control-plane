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
    load_research_run_spec_snapshot,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.research_state import (
    ResearchState,
    load_research_state,
    research_state_path,
)


BLOCKER_OUTCOMES = {"blocked", "prerequisites_failed"}
FAILURE_OUTCOMES = {"invalid", "run_failed", "prerequisites_failed"}
COMPLETED_OUTCOMES = {
    "completed_rejected",
    "completed_inconclusive",
    "completed_candidate",
}
CONTEXT_OUTPUT_NAMES = {
    "context_pack.md",
    "context_summary.json",
    "continuation_summary.json",
}
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
    continuation_summary_path: Path
    continuation_summary: dict[str, Any]


def write_context_outputs(
    paths: ResearchProgramPaths,
    research_run_id: str,
    *,
    output_directory: str | Path | None = None,
    current_experiment_id: str | None = None,
) -> ContextOutputs:
    run_dir = paths.run_directory(research_run_id)
    program_root = Path(paths.root)
    output_dir = Path(output_directory) if output_directory is not None else run_dir
    spec = load_research_run_spec_snapshot(
        run_dir / "research_run_spec.yaml",
        research_program_root=program_root,
    )
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
    continuation_summary = _build_continuation_summary(
        paths=paths,
        spec=spec,
        program_root=program_root,
        current_run_dir=run_dir,
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
            "maximum_memory_bytes": spec.selected_budget.maximum_memory_bytes,
            "default_command_timeout_seconds": (
                spec.selected_budget.default_command_timeout_seconds
            ),
        },
        "data_root": str(spec.data_root),
        "experiment_data_root": str(spec.experiment_data_root),
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
    text = _render_context_pack(
        current_context=summary,
        continuation_context=continuation_summary,
    )

    context_pack_path = output_dir / "context_pack.md"
    context_summary_path = output_dir / "context_summary.json"
    write_text(context_pack_path, text)
    write_json(context_summary_path, summary)
    continuation_summary_path = output_dir / "continuation_summary.json"
    write_json(continuation_summary_path, continuation_summary)

    return ContextOutputs(
        context_pack_path=context_pack_path,
        context_summary_path=context_summary_path,
        context_pack_text=text,
        context_summary=summary,
        continuation_summary_path=continuation_summary_path,
        continuation_summary=continuation_summary,
    )


def _build_continuation_summary(
    *,
    paths: ResearchProgramPaths,
    spec: Any,
    program_root: Path,
    current_run_dir: Path,
) -> dict[str, Any]:
    research_state = load_research_state(research_state_path(paths))
    experiments = _state_prior_experiments(
        research_state,
        max_prior_experiments=spec.continuation.max_prior_experiments,
    )
    pending_ideas = _state_pending_ideas(research_state)
    metric_history = _state_metric_history(research_state)
    repo_loop_context = _repo_loop_context(spec.continuation.repo_loop_context_paths)
    return {
        "artifact_kind": "continuation_summary",
        "controller_generated": True,
        "program_id": program_root.name,
        "program_root": str(program_root),
        "current_run_dir": str(current_run_dir.resolve()),
        "prior_run_dirs": [
            str(path) for path in spec.continuation.prior_run_dirs
        ],
        "prior_worktree_roots": [
            str(path) for path in spec.continuation.prior_worktree_roots
        ],
        "repo_loop_context": repo_loop_context,
        "memory_context": [],
        "prior_experiments": experiments,
        "pending_followups": pending_ideas,
        "future_experiment_ideas": pending_ideas,
        "reusable_implementations": _state_reusable_implementations(research_state),
        "do_not_repeat": _state_do_not_repeat(research_state),
        "metric_history": metric_history,
        "best_metric_runs": _state_best_metric_runs(metric_history),
    }


def _state_prior_experiments(
    state: ResearchState,
    *,
    max_prior_experiments: int,
) -> list[dict[str, Any]]:
    reusable_sources = {
        source
        for component in state.reusable_components.values()
        for source in component.source_experiments
    }
    records = []
    for source_experiment, experiment in sorted(state.experiment_index.items()):
        run_id, experiment_id = _split_source_experiment(source_experiment)
        worktree = (
            {"path": experiment.worktree_path, "source": "lineage"}
            if experiment.worktree_path is not None
            else None
        )
        reusable = source_experiment in reusable_sources and worktree is not None
        records.append(
            {
                "source_experiment": source_experiment,
                "run_id": run_id,
                "experiment_id": experiment_id,
                "experiment_dir": experiment.experiment_dir,
                "outcome": experiment.outcome,
                "outcome_reason": experiment.outcome_reason,
                "failed_stage": experiment.failed_stage,
                "failure_classification": experiment.failure_classification,
                "hypothesis": experiment.hypothesis,
                "primary_metric": experiment.primary_metric,
                "prediction_horizon": experiment.prediction_horizon,
                "label": experiment.label,
                "selected_plan_rationale": experiment.selected_plan_rationale,
                "selected_idea_ids": experiment.selected_idea_ids,
                "fresh_selection_reason": experiment.fresh_selection_reason,
                "seed_component_ids": experiment.seed_component_ids,
                "implementation_summary": experiment.implementation_summary,
                "changed_files": experiment.changed_files,
                "followups": [
                    idea.title
                    for idea in state.idea_index.values()
                    if source_experiment in idea.source_experiments
                ],
                "metrics": _metrics_for_source(state, source_experiment),
                "gate_results": {},
                "worktree": worktree,
                "worktree_branch": experiment.worktree_branch,
                "lineage_path": experiment.lineage_path,
                "reusable": reusable,
            }
        )
    if len(records) > max_prior_experiments:
        records = records[-max_prior_experiments:]
    return records


def _state_pending_ideas(state: ResearchState) -> list[dict[str, Any]]:
    records = []
    pending_items = [
        (idea_id, idea)
        for idea_id, idea in state.idea_index.items()
        if idea.status == "pending"
    ]
    for idea_id, idea in sorted(
        pending_items,
        key=lambda item: (-item[1].priority, item[0]),
    ):
        seed_worktree_paths = [
            state.reusable_components[component_id].worktree_path
            for component_id in idea.seed_component_ids
        ]
        records.append(
            {
                "idea_id": idea_id,
                "dedupe_key": idea.dedupe_key,
                "title": idea.title,
                "idea": idea.title,
                "kind": idea.kind,
                "evidence_basis": idea.evidence_basis,
                "mechanism": idea.mechanism,
                "axis_to_vary": idea.axis_to_vary,
                "specific_change": idea.specific_change,
                "falsifying_evidence": idea.falsifying_evidence,
                "priority": idea.priority,
                "priority_reason": idea.priority_reason,
                "source_experiments": idea.source_experiments,
                "seed_component_ids": idea.seed_component_ids,
                "suggested_seed_worktree": (
                    seed_worktree_paths[0] if seed_worktree_paths else None
                ),
                "suggested_seed_worktrees": seed_worktree_paths,
            }
        )
    return records


def _state_reusable_implementations(state: ResearchState) -> list[dict[str, Any]]:
    return [
        {
            "component_id": component_id,
            "source_experiment": component.source_experiments[0],
            "source_experiments": component.source_experiments,
            "worktree_path": component.worktree_path,
            "changed_files": component.changed_files,
            "implementation_summary": component.summary,
            "reusable_for": component.reusable_for,
            "risk_notes": component.risk_notes,
        }
        for component_id, component in sorted(state.reusable_components.items())
    ]


def _state_do_not_repeat(state: ResearchState) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idea_id, idea in sorted(state.idea_index.items()):
        if idea.status not in {"completed", "blocked", "superseded"}:
            continue
        records.append(
            {
                "idea_id": idea_id,
                "source_experiments": idea.source_experiments,
                "status": idea.status,
                "reason": f"{idea.status}: {idea.title}",
            }
        )
    for blocker_key, blocker in sorted(state.known_blockers.items()):
        records.append(
            {
                "blocker_key": blocker_key,
                "blocker_type": blocker.blocker_type,
                "source_experiments": blocker.source_experiments,
                "affected_idea_ids": blocker.affected_idea_ids,
                "reason": blocker.description,
                "resolution_condition": blocker.resolution_condition,
            }
        )
    return records


def _state_metric_history(state: ResearchState) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "source_experiment": observation.source_experiment,
                "metric_path": observation.metric_path,
                "value": observation.value,
            }
            for observation in state.metric_observations
        ],
        key=lambda item: (
            item["source_experiment"],
            item["metric_path"],
        ),
    )


def _state_best_metric_runs(
    metric_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_by_metric: dict[str, dict[str, Any]] = {}
    for observation in metric_history:
        metric_path = observation["metric_path"]
        current = best_by_metric.get(metric_path)
        if current is None or observation["value"] > current["value"]:
            best_by_metric[metric_path] = {
                "source_experiment": observation["source_experiment"],
                "metric": f"metrics.{metric_path}",
                "value": observation["value"],
            }
    return [best_by_metric[metric_path] for metric_path in sorted(best_by_metric)]


def _metrics_for_source(
    state: ResearchState,
    source_experiment: str,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for observation in state.metric_observations:
        if observation.source_experiment != source_experiment:
            continue
        metrics[observation.metric_path] = observation.value
    return metrics


def _split_source_experiment(source_experiment: str) -> tuple[str, str]:
    run_id, experiment_id = source_experiment.split("/", 1)
    return run_id, experiment_id


def _repo_loop_context(paths: tuple[Path, ...]) -> list[dict[str, str]]:
    return [
        {
            "path": str(path),
            "text": path.read_text(encoding="utf-8"),
        }
        for path in paths
    ]


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


def _render_context_pack(
    *,
    current_context: dict[str, Any],
    continuation_context: dict[str, Any],
) -> str:
    spec = current_context["spec"]
    budget = current_context["budget"]
    git = current_context["git"]
    prior = current_context["prior_synthesis"]
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
        f"- hard process-tree memory bytes: {budget['maximum_memory_bytes'] or 'unbounded'}",
        "",
        "## Repository",
        f"- data root: {current_context['data_root']}",
        f"- experiment data root: {current_context['experiment_data_root']}",
        "- artifact backfill policy: optional commands may write experiment-local runtime data; canonical data is read-only.",
        "- experiment-local outputs: selected experiments may write declared evaluation evidence under $RESEARCH_EXPERIMENT_DATA_ROOT.",
        f"- repo root: {git['repo_root']}",
        f"- git head: {git['head']}",
        "- git status:",
        git["status_text"].rstrip(),
        "- changed files:",
        *_list_lines(git["changed_files"]),
        "",
        "## Artifact Inventory",
        *_json_lines(current_context["artifact_inventory"]),
        "",
        "## Ledger History",
        *_json_lines(current_context["ledger_history"]),
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
    lines.extend(_render_continuation_context(continuation_context))
    return "\n".join(lines) + "\n"


def _render_continuation_context(continuation: dict[str, Any]) -> list[str]:
    lines = [
        "## Research Program Continuation",
        f"- program root: {continuation['program_root']}",
        "",
        "### Repo Loop Context",
    ]
    for item in continuation["repo_loop_context"]:
        lines.extend(
            [
                f"#### {item['path']}",
                "```text",
                item["text"].rstrip(),
                "```",
            ]
        )
    if not lines[-1].endswith("```"):
        lines.append("- none")
    lines.extend(
        [
            "### Explicit Prior Run Dirs",
            *_list_lines(continuation["prior_run_dirs"]),
            "### Explicit Prior Worktree Roots",
            *_list_lines(continuation["prior_worktree_roots"]),
            "### Memory Context",
            *_json_lines(continuation["memory_context"]),
            "### Pending Followups",
            *_json_lines(continuation["pending_followups"]),
            "### Future Experiment Ideas",
            *_json_lines(continuation["future_experiment_ideas"]),
            "### Reusable Implementations",
            *_json_lines(continuation["reusable_implementations"]),
            "### Do Not Repeat",
            *_json_lines(continuation["do_not_repeat"]),
            "### Continuation Metric History",
            *_json_lines(continuation["metric_history"]),
            "### Best Metric Runs",
            *_json_lines(continuation["best_metric_runs"]),
            "",
        ]
    )
    return lines


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
