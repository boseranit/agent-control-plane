from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.controller import (
    ResearchRunError,
    load_research_run,
    start_research_run,
)
from agent_control_plane.research_experiment_controller.ledger import read_ledger_events


def write_minimal_research_run_spec(
    tmp_path: Path,
    repo: Path,
    *,
    research_run_id: str = "peer-residual-v1",
) -> Path:
    path = tmp_path / f"{research_run_id}.yaml"
    path.write_text(
        f"""
research_run_id: {research_run_id}
target_repository: {repo}
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: /mnt/redbackup/data
""",
        encoding="utf-8",
    )
    return path


def test_start_research_run_creates_run_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)

    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    assert run.research_run_id == "peer-residual-v1"
    assert run.run_directory == (tmp_path / "runs" / "peer-residual-v1").resolve()
    assert run.spec_snapshot_path == run.run_directory / "research_run_spec.yaml"
    assert run.state_path == run.run_directory / "state.json"
    assert run.ledger_path == run.run_directory / "ledger.jsonl"
    assert run.experiments_directory == run.run_directory / "experiments"
    assert run.spec_snapshot_path.exists()
    assert run.state_path.exists()
    assert run.ledger_path.exists()
    assert run.experiments_directory.is_dir()


def test_start_research_run_writes_resolved_spec_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)

    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    snapshot = yaml.safe_load(run.spec_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["version"] == 1
    assert snapshot["research_run_id"] == "peer-residual-v1"
    assert snapshot["target_repository"] == str(repo.resolve())
    assert snapshot["max_experiments"] == 1
    assert snapshot["worktree"] == {"create": True, "root": ".worktrees"}
    assert snapshot["mlflow"] == {
        "enabled": False,
        "tracking_uri": None,
        "experiment_name": None,
    }
    assert "source_path" not in snapshot
    assert "selected_budget" not in snapshot


def test_start_research_run_writes_state_and_ledger_events(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)

    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    state = read_json_object(run.state_path)
    assert state["research_run_id"] == "peer-residual-v1"
    assert state["current_phase"] == "initialized"
    assert state["active_experiment_id"] is None
    assert state["experiment_count"] == 0
    assert state["max_experiments"] == 1
    assert state["run_directory"] == str(run.run_directory)
    assert state["spec_snapshot_path"] == str(run.spec_snapshot_path)

    events = read_ledger_events(run.ledger_path)
    assert events == [
        {
            "event_type": "research_run_started",
            "research_run_id": "peer-residual-v1",
        },
        {
            "event_type": "phase_changed",
            "research_run_id": "peer-residual-v1",
            "current_phase": "initialized",
        },
        {
            "event_type": "artifact_written",
            "research_run_id": "peer-residual-v1",
            "artifact_name": "research_run_spec",
            "artifact_path": str(run.spec_snapshot_path),
        },
        {
            "event_type": "artifact_written",
            "research_run_id": "peer-residual-v1",
            "artifact_name": "state",
            "artifact_path": str(run.state_path),
        },
    ]


def test_start_research_run_rejects_existing_run_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    start_research_run(spec_path, runtime_root=tmp_path / "runs")

    with pytest.raises(ResearchRunError, match="already exists"):
        start_research_run(spec_path, runtime_root=tmp_path / "runs")


def test_load_research_run_uses_snapshot_and_state_after_source_spec_deleted(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    started = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    snapshot_before = yaml.safe_load(
        started.spec_snapshot_path.read_text(encoding="utf-8")
    )
    state_before = read_json_object(started.state_path)

    spec_path.unlink()

    loaded = load_research_run("peer-residual-v1", runtime_root=tmp_path / "runs")

    assert loaded.research_run_id == "peer-residual-v1"
    assert loaded.run_directory == started.run_directory
    assert loaded.spec_snapshot_path == started.spec_snapshot_path
    assert loaded.state_path == started.state_path
    assert yaml.safe_load(loaded.spec_snapshot_path.read_text(encoding="utf-8")) == (
        snapshot_before
    )
    assert loaded.state == state_before
