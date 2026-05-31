from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.artifacts import (
    ResearchOutcome,
)

CONTROLLER_STATE_VERSION = 1


def research_run_directory(runtime_root: str | Path, research_run_id: str) -> Path:
    if not isinstance(research_run_id, str) or not research_run_id.strip():
        raise ValueError("Research Run ID is required.")
    return Path(runtime_root).resolve() / research_run_id


def create_initial_state(
    *,
    research_run_id: str,
    run_directory: str | Path,
    spec_snapshot_path: str | Path,
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
        "run_directory": str(Path(run_directory).resolve()),
        "spec_snapshot_path": str(Path(spec_snapshot_path).resolve()),
        "experiments": {},
        "threads": {},
    }


def next_experiment_id(state: dict[str, Any]) -> str:
    experiment_count = state.get("experiment_count")
    if isinstance(experiment_count, bool) or not isinstance(experiment_count, int):
        raise ValueError("Research Run state experiment_count must be an integer.")
    return f"EXP-{experiment_count + 1:04d}"


def experiment_directory(run_directory: str | Path, experiment_id: str) -> Path:
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("Research Experiment ID is required.")
    return Path(run_directory) / "experiments" / experiment_id


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

    experiments[experiment_id] = {
        "id": experiment_id,
        "status": "terminal",
        "experiment_directory": str(Path(experiment_dir)),
        "outcome": outcome,
        "outcome_reason": terminal_summary.get("outcome_reason"),
        "failed_stage": terminal_summary.get("failed_stage"),
        "failure_classification": terminal_summary.get("failure_classification"),
    }
    state["experiment_count"] = len(experiments)
    state["active_experiment_id"] = None
