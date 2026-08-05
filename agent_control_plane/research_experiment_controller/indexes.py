# Generated Markdown navigation over authoritative Research Program artifacts.

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_text,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.research_state import (
    load_research_state,
    research_state_path,
)


GENERATED_NOTICE = (
    "<!-- Generated from controller state and terminal summaries. Do not edit. -->"
)


def refresh_research_indexes(research_program_root: str | Path) -> list[Path]:
    """Publish navigation views for retained Research Run evidence."""
    paths = ResearchProgramPaths(research_program_root)
    if not paths.runs.is_dir():
        raise ValueError(f"Research Program has no runs directory: {paths.root}")

    rendered: list[tuple[Path, str]] = []
    for run_id, run_directory in _run_directories(paths).items():
        state_path = run_directory / "state.json"
        if not state_path.is_file():
            continue
        index_path = run_directory / "INDEX.md"
        rendered.append((index_path, render_run_index(paths, run_id)))

    runs_index = paths.runs / "INDEX.md"
    rendered.append((runs_index, render_runs_index(paths)))

    programs_directory = Path(paths.root).parent
    if programs_directory.name == "programs":
        archive_index = programs_directory.parent / "INDEX.md"
        rendered.append((archive_index, render_archive_index(programs_directory)))

    for path, content in rendered:
        write_text(path, content)
    return [path for path, _ in rendered]


def render_runs_index(paths: ResearchProgramPaths) -> str:
    """Render retained and memory-only Research Runs in one program."""
    run_directories = _run_directories(paths)
    memory_records = _memory_records_by_run(paths)
    run_ids = sorted(set(run_directories) | set(memory_records))
    lines = [
        f"# Research Runs: {Path(paths.root).name}",
        "",
        GENERATED_NOTICE,
        "",
        "[Research Program index](../INDEX.md)",
        "",
        "| Research Run | Retained evidence | State | Outcomes |",
        "| --- | --- | --- | --- |",
    ]
    for run_id in run_ids:
        run_directory = run_directories.get(run_id)
        if run_directory is None:
            records = memory_records[run_id]
            lines.append(
                f"| {_cell(run_id)} | {len(records)} continuation-memory records; "
                f"Run directory not retained | historical only | "
                f"{_format_counts(_outcome_counts(records))} |"
            )
            continue
        state_path = run_directory / "state.json"
        if not state_path.is_file():
            lines.append(
                f"| [{_cell(run_id)}]({run_id}/) | incomplete directory | "
                "missing state | — |"
            )
            continue
        state = read_json_object(state_path)
        experiments = _state_experiments(state)
        lines.append(
            f"| [{_cell(run_id)}]({run_id}/INDEX.md) | "
            f"{len(experiments)} terminal Experiments | "
            f"{_cell(str(state.get('status', 'unknown')))} | "
            f"{_format_counts(_outcome_counts(experiments.values()))} |"
        )
    if not run_ids:
        lines.append("| — | No Research Runs recorded | — | — |")
    lines.append("")
    return "\n".join(lines)


def render_run_index(paths: ResearchProgramPaths, research_run_id: str) -> str:
    """Render terminal evidence for one Research Run."""
    state = read_json_object(paths.state_path(research_run_id))
    if state.get("research_run_id") != research_run_id:
        raise ValueError("Research Run state does not match the index Run ID.")
    experiments = _state_experiments(state)
    lines = [
        f"# Research Run: {research_run_id}",
        "",
        GENERATED_NOTICE,
        "",
        "- [Research Program index](../../INDEX.md)",
        "- [All Research Runs](../INDEX.md)",
        "- Evidence: [Run Spec](research_run_spec.yaml), "
        "[controller state](state.json), [append-only ledger](ledger.jsonl)",
        f"- Status: `{state.get('status', 'unknown')}`",
        f"- Current phase: `{state.get('current_phase', 'unknown')}`",
        f"- Terminal Experiments: {len(experiments)}",
        "",
        "| Experiment | Outcome | Failure | Worktree | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for experiment_id in sorted(experiments, key=_experiment_sort_key):
        record = experiments[experiment_id]
        if not isinstance(record, dict):
            raise ValueError(
                f"Research Run state record must be an object: {experiment_id}"
            )
        summary_path = (
            paths.experiment_directory(research_run_id, experiment_id) / "summary.json"
        )
        summary = read_json_object(summary_path)
        if summary.get("outcome") != record.get("outcome"):
            raise ValueError(
                "Research Experiment outcome mismatch: "
                f"{research_run_id}/{experiment_id}"
            )
        failure = " / ".join(
            str(value)
            for value in (
                summary.get("failed_stage"),
                summary.get("failure_classification"),
            )
            if value
        )
        worktree = paths.worktree_directory(research_run_id, experiment_id)
        worktree_link = (
            f"[worktree](../../worktrees/{research_run_id}/{experiment_id}/)"
            if worktree.is_dir()
            else "—"
        )
        summary_text = _bounded_summary(
            str(summary.get("summary") or summary.get("outcome_reason") or "—")
        )
        lines.append(
            f"| [{experiment_id}](experiments/{experiment_id}/summary.json) | "
            f"{_cell(str(record.get('outcome', 'unknown')))} | "
            f"{_cell(failure or '—')} | {worktree_link} | "
            f"{_cell(summary_text)} |"
        )
    if not experiments:
        lines.append("| — | — | — | — | No terminal Experiments recorded. |")
    lines.append("")
    return "\n".join(lines)


def render_archive_index(programs_directory: Path) -> str:
    """Render Research Programs retained in one controller archive."""
    program_directories = sorted(
        path for path in programs_directory.iterdir() if path.is_dir()
    )
    lines = [
        "# Agent Control Plane Research Archive",
        "",
        GENERATED_NOTICE,
        "",
        "Canonical Research Programs live under `programs/<program-id>/`.",
        "",
        "| Research Program | Retained Runs | Continuation records |",
        "| --- | ---: | ---: |",
    ]
    for program_directory in program_directories:
        paths = ResearchProgramPaths(program_directory)
        memory_path = research_state_path(paths)
        memory_count: int | str = "—"
        if memory_path.is_file():
            memory_count = len(load_research_state(memory_path).experiment_index)
        lines.append(
            f"| [{_cell(program_directory.name)}]"
            f"(programs/{program_directory.name}/INDEX.md) | "
            f"{len(_run_directories(paths))} | {memory_count} |"
        )
    if not program_directories:
        lines.append("| — | 0 | 0 |")
    lines.append("")
    return "\n".join(lines)


def _run_directories(paths: ResearchProgramPaths) -> dict[str, Path]:
    if not paths.runs.is_dir():
        return {}
    return {path.name: path for path in sorted(paths.runs.iterdir()) if path.is_dir()}


def _memory_records_by_run(paths: ResearchProgramPaths) -> dict[str, list[Any]]:
    path = research_state_path(paths)
    if not path.is_file():
        return {}
    records: dict[str, list[Any]] = {}
    for source_experiment, record in load_research_state(path).experiment_index.items():
        run_id, separator, _ = source_experiment.partition("/")
        if separator:
            records.setdefault(run_id, []).append(record)
    return records


def _state_experiments(state: dict[str, Any]) -> dict[str, Any]:
    experiments = state.get("experiments")
    if not isinstance(experiments, dict):
        raise ValueError("Research Run state experiments must be an object.")
    recorded_count = state.get("experiment_count")
    if recorded_count is not None and recorded_count != len(experiments):
        raise ValueError("Research Run state experiment count does not match records.")
    return experiments


def _outcome_counts(records: Any) -> Counter[str]:
    return Counter(
        str(record.get("outcome", "unknown"))
        if isinstance(record, dict)
        else str(getattr(record, "outcome", "unknown"))
        for record in records
    )


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "—"
    return ", ".join(f"{outcome}: {counts[outcome]}" for outcome in sorted(counts))


def _experiment_sort_key(value: str) -> tuple[int, str]:
    prefix, separator, suffix = value.rpartition("-")
    if separator and suffix.isdigit():
        return int(suffix), prefix
    return -1, value


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def _bounded_summary(value: str, *, limit: int = 240) -> str:
    summary = " ".join(value.split())
    if len(summary) <= limit:
        return summary
    return f"{summary[: limit - 1].rstrip()}…"
