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
        spec=spec,
        program_root=program_root,
        current_run_dir=run_dir,
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
    write_json(
        paths.memory / "continuation_summary.json",
        continuation_summary,
    )

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
    spec: Any,
    program_root: Path,
    current_run_dir: Path,
    active_experiment_ids: set[str],
) -> dict[str, Any]:
    experiments = _program_terminal_experiments(
        program_root=program_root,
        current_run_dir=current_run_dir,
        active_experiment_ids=active_experiment_ids,
        max_prior_experiments=spec.research_program.max_prior_experiments,
    )
    return {
        "artifact_kind": "continuation_summary",
        "controller_generated": True,
        "program_id": program_root.name,
        "program_root": str(program_root),
        "current_run_dir": str(current_run_dir.resolve()),
        "human_context": _human_context(program_root),
        "memory_context": _memory_context(program_root),
        "prior_experiments": experiments,
        "pending_followups": _pending_followups(experiments),
        "future_experiment_ideas": _future_experiment_ideas(experiments),
        "reusable_implementations": _reusable_implementations(experiments),
        "do_not_repeat": _do_not_repeat(experiments),
        "metric_history": _continuation_metric_history(experiments),
        "best_metric_runs": _best_metric_runs(experiments),
    }


def _program_terminal_experiments(
    *,
    program_root: Path,
    current_run_dir: Path,
    active_experiment_ids: set[str],
    max_prior_experiments: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current_run_dir = current_run_dir.resolve()
    for run_dir in sorted((program_root / "runs").iterdir()):
        run_id = run_dir.name
        for experiment_dir in sorted((run_dir / "experiments").iterdir()):
            experiment_id = experiment_dir.name
            if (
                run_dir.resolve() == current_run_dir
                and experiment_id in active_experiment_ids
                and not (experiment_dir / "summary.json").exists()
            ):
                continue
            record = _continuation_record(
                run_id=run_id,
                experiment_id=experiment_id,
                experiment_dir=experiment_dir,
            )
            if record is not None:
                records.append(record)

    records = sorted(records, key=lambda item: item["source_experiment"])
    if len(records) > max_prior_experiments:
        records = records[-max_prior_experiments:]
    return records


def _continuation_record(
    *,
    run_id: str,
    experiment_id: str,
    experiment_dir: Path,
) -> dict[str, Any] | None:
    summary_path = experiment_dir / "summary.json"
    if not summary_path.exists():
        return None
    summary = read_json_object(summary_path)

    def artifact(name: str) -> dict[str, Any]:
        path = experiment_dir / name
        return read_json_object(path) if path.exists() else {}

    research_spec = artifact("research_spec.json")
    selected_plan = artifact("selected_plan.json")
    implementation = artifact("implementation.json")
    confirmatory = artifact("confirmatory_evaluation_result.json")
    exploratory = artifact("exploratory_diagnostics_result.json")
    plan_update = artifact("plan_update.json")
    lineage_path = experiment_dir / "lineage.json"
    lineage = read_json_object(lineage_path) if lineage_path.exists() else None

    worktree_path = lineage["worktree_path"] if lineage is not None else None
    worktree = (
        {"path": worktree_path, "source": "lineage"}
        if worktree_path is not None
        else None
    )
    changed_files = lineage["changed_files"] if lineage is not None else []
    seed_experiment = selected_plan.get("implementation_seed_experiment")
    seed_worktree = selected_plan.get("implementation_seed_worktree")
    implementation_seed = (
        {"source_experiment": seed_experiment, "worktree_path": seed_worktree}
        if seed_experiment is not None or seed_worktree is not None
        else None
    )
    reusable = bool(
        worktree_path
        and (
            plan_update.get("reusable_worktree")
            or (lineage is not None and lineage["reusable_for_followups"])
            or (
                changed_files
                and summary.get("outcome") in COMPLETED_OUTCOMES
            )
        )
    )
    source_experiment = f"{run_id}/{experiment_id}"
    return {
        "source_experiment": source_experiment,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "experiment_dir": str(experiment_dir),
        "outcome": summary.get("outcome"),
        "outcome_reason": summary.get("outcome_reason"),
        "failed_stage": summary.get("failed_stage"),
        "failure_classification": summary.get("failure_classification"),
        "hypothesis": research_spec.get("hypothesis"),
        "primary_metric": research_spec.get("primary_metric"),
        "prediction_horizon": research_spec.get("prediction_horizon"),
        "label": research_spec.get("label"),
        "selected_plan_rationale": selected_plan.get("rationale"),
        "implementation_summary": implementation.get("summary"),
        "changed_files": changed_files,
        "followups": plan_update.get("followups", []),
        "revisit_conditions": plan_update.get("revisit_conditions", []),
        "blocked_paths": plan_update.get("blocked_paths", []),
        "future_experiment_ideas": exploratory.get("future_experiment_ideas", []),
        "metrics": confirmatory.get("metrics", {}),
        "gate_results": confirmatory.get("gate_results", {}),
        "worktree": worktree,
        "worktree_branch": lineage["worktree_branch"] if lineage is not None else None,
        "implementation_seed": implementation_seed,
        "lineage_path": str(lineage_path) if lineage is not None else None,
        "reusable": reusable,
        "implementation_reuse_notes": plan_update.get("implementation_reuse_notes", []),
        "recommended_next_experiment_kind": plan_update.get(
            "recommended_next_experiment_kind"
        ),
    }


def _human_context(program_root: Path) -> dict[str, Any]:
    program_md = program_root / "program.md"
    program_text = (
        program_md.read_text(encoding="utf-8") if program_md.is_file() else None
    )
    notes_dir = program_root / "notes"
    notes: list[dict[str, str]] = []
    if notes_dir.is_dir():
        notes = [
            {
                "path": path.relative_to(program_root).as_posix(),
                "text": path.read_text(encoding="utf-8"),
            }
            for path in sorted(notes_dir.glob("*.md"))
            if path.is_file()
        ]
    return {"program_md": program_text, "notes": notes}


def _memory_context(program_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((program_root / "memory").glob("*.json")):
        if path.name == "continuation_summary.json":
            continue
        records.append(
            {
                "path": path.relative_to(program_root).as_posix(),
                "content": read_json_object(path),
            }
        )
    return records


def _pending_followups(experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for experiment in experiments:
        for followup in experiment["followups"]:
            records.append(
                {
                    "source_experiment": experiment["source_experiment"],
                    "idea": followup,
                    "suggested_seed_worktree": (
                        experiment["worktree"]["path"]
                        if experiment["reusable"] and experiment["worktree"]
                        else None
                    ),
                }
            )
    return records


def _future_experiment_ideas(
    experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for experiment in experiments:
        for idea in experiment["future_experiment_ideas"]:
            records.append(
                {
                    "source_experiment": experiment["source_experiment"],
                    "idea": idea,
                    "suggested_seed_worktree": (
                        experiment["worktree"]["path"]
                        if experiment["reusable"] and experiment["worktree"]
                        else None
                    ),
                }
            )
    return records


def _reusable_implementations(
    experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "source_experiment": experiment["source_experiment"],
            "worktree_path": experiment["worktree"]["path"],
            "changed_files": experiment["changed_files"],
            "implementation_summary": experiment["implementation_summary"],
        }
        for experiment in experiments
        if experiment["reusable"] and experiment["worktree"]
    ]


def _do_not_repeat(experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for experiment in experiments:
        for blocked_path in experiment["blocked_paths"]:
            records.append(
                {
                    "source_experiment": experiment["source_experiment"],
                    "reason": blocked_path,
                }
            )
        if experiment["outcome"] in FAILURE_OUTCOMES | BLOCKER_OUTCOMES:
            reason = (
                experiment["failure_classification"] or experiment["outcome_reason"]
            )
            if reason:
                records.append(
                    {
                        "source_experiment": experiment["source_experiment"],
                        "reason": reason,
                    }
                )
    return records


def _continuation_metric_history(
    experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for experiment in experiments:
        for metric_path, value in _numeric_leaves(experiment["metrics"]):
            records.append(
                {
                    "source_experiment": experiment["source_experiment"],
                    "metric_path": metric_path,
                    "value": value,
                }
            )
    return sorted(
        records,
        key=lambda item: (
            item["source_experiment"],
            item["metric_path"],
        ),
    )


def _best_metric_runs(experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_metric: dict[str, dict[str, Any]] = {}
    for experiment in experiments:
        for metric_path, value in _numeric_leaves(experiment["metrics"]):
            current = best_by_metric.get(metric_path)
            if current is None or value > current["value"]:
                best_by_metric[metric_path] = {
                    "source_experiment": experiment["source_experiment"],
                    "metric": f"metrics.{metric_path}",
                    "value": value,
                }
    return [best_by_metric[metric_path] for metric_path in sorted(best_by_metric)]


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
        "",
        "## Repository",
        f"- data root: {current_context['data_root']}",
        f"- experiment data root: {current_context['experiment_data_root']}",
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
        "### Human Context",
    ]
    human_context = continuation.get("human_context", {})
    program_md = human_context.get("program_md")
    if isinstance(program_md, str) and program_md.strip():
        lines.extend(["#### program.md", "```text", program_md.rstrip(), "```"])
    notes = human_context.get("notes", [])
    if isinstance(notes, list):
        for item in notes:
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
