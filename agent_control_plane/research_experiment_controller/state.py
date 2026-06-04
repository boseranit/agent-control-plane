from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.artifacts import (
    ResearchOutcome,
)

CONTROLLER_STATE_VERSION = 1


def create_initial_state(
    *,
    research_run_id: str,
    max_experiments: int,
) -> dict[str, Any]:
    return {
        "controller_state_version": CONTROLLER_STATE_VERSION,
        "research_run_id": research_run_id,
        "status": "running",
        "current_phase": "initialized",
        "active_experiment_id": None,
        "experiment_count": 0,
        "max_experiments": max_experiments,
        "experiments": {},
        "threads": {},
    }


def next_experiment_id(state: dict[str, Any]) -> str:
    experiment_count = state.get("experiment_count")
    if isinstance(experiment_count, bool) or not isinstance(experiment_count, int):
        raise ValueError("Research Run state experiment_count must be an integer.")
    return f"EXP-{experiment_count + 1:04d}"


def load_terminal_summary(experiment_dir: str | Path) -> dict[str, Any]:
    summary = read_json_object(Path(experiment_dir) / "summary.json")
    outcome = summary.get("outcome")
    if outcome not in {item.value for item in ResearchOutcome}:
        raise ValueError("Terminal summary has invalid outcome.")
    return summary


def record_terminal_experiment(
    state: dict[str, Any],
    *,
    experiment_id: str,
    experiment_dir: str | Path,
    terminal_summary: dict[str, Any],
) -> None:
    outcome = terminal_summary.get("outcome")
    if outcome not in {item.value for item in ResearchOutcome}:
        raise ValueError("Terminal summary has invalid outcome.")
    experiments = state.get("experiments")
    if not isinstance(experiments, dict):
        raise ValueError("Research Run state experiments must be an object.")

    experiment_path = Path(experiment_dir)
    record = {
        "id": experiment_id,
        "status": "terminal",
        "experiment_directory": str(experiment_path),
        "outcome": outcome,
        "outcome_reason": terminal_summary.get("outcome_reason"),
        "failed_stage": terminal_summary.get("failed_stage"),
        "failure_classification": terminal_summary.get("failure_classification"),
    }
    record.update(_lineage_state_fields(experiment_path))
    experiments[experiment_id] = record
    state["experiment_count"] = len(experiments)
    state["active_experiment_id"] = None


def _lineage_state_fields(experiment_dir: Path) -> dict[str, Any]:
    lineage_path = experiment_dir / "lineage.json"
    if not lineage_path.exists():
        return {}
    lineage = read_json_object(lineage_path)
    return {
        "lineage_path": str(lineage_path),
        "worktree_path": lineage.get("worktree_path"),
        "worktree_branch": lineage.get("worktree_branch"),
        "changed_files": lineage.get("changed_files", []),
    }
