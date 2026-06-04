from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller.ledger import (
    append_ledger_event,
    read_ledger_events,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    load_terminal_summary,
    next_experiment_id,
    record_terminal_experiment,
)


def test_program_paths_scope_run_directory(tmp_path: Path) -> None:
    program_root = tmp_path / "programs" / "peer-residuals"
    paths = ResearchProgramPaths(program_root)
    run_directory = paths.run_directory("peer-residual-v1")

    state = create_initial_state(
        research_run_id="peer-residual-v1",
        max_experiments=5,
    )

    assert run_directory == (program_root / "runs" / "peer-residual-v1").resolve()
    assert state == {
        "controller_state_version": 1,
        "research_run_id": "peer-residual-v1",
        "status": "running",
        "current_phase": "initialized",
        "active_experiment_id": None,
        "experiment_count": 0,
        "max_experiments": 5,
        "experiments": {},
        "threads": {},
    }


def test_next_experiment_id_uses_one_based_zero_padded_sequence() -> None:
    state = create_initial_state(
        research_run_id="peer-residual-v1",
        max_experiments=10,
    )

    assert next_experiment_id(state) == "EXP-0001"

    state["experiment_count"] = 7

    assert next_experiment_id(state) == "EXP-0008"


def test_experiment_directory_is_under_run_experiments(tmp_path: Path) -> None:
    paths = ResearchProgramPaths(tmp_path / "programs" / "peer-residuals")
    run_directory = paths.run_directory("peer-residual-v1")

    assert paths.experiment_directory("peer-residual-v1", "EXP-0001") == (
        run_directory / "experiments" / "EXP-0001"
    )


def test_append_and_read_ledger_events(tmp_path: Path) -> None:
    ledger_path = (
        tmp_path
        / "programs"
        / "peer-residuals"
        / "runs"
        / "peer-residual-v1"
        / "ledger.jsonl"
    )

    append_ledger_event(
        ledger_path,
        event_type="research_run_started",
        research_run_id="peer-residual-v1",
    )
    append_ledger_event(
        ledger_path,
        event_type="phase_changed",
        research_run_id="peer-residual-v1",
        current_phase="initialized",
    )

    assert read_ledger_events(ledger_path) == [
        {
            "event_type": "research_run_started",
            "research_run_id": "peer-residual-v1",
        },
        {
            "event_type": "phase_changed",
            "research_run_id": "peer-residual-v1",
            "current_phase": "initialized",
        },
    ]


def test_load_terminal_summary_outcome_from_experiment_directory(
    tmp_path: Path,
) -> None:
    experiment_dir = (
        tmp_path
        / "programs"
        / "peer-residuals"
        / "runs"
        / "peer-residual-v1"
        / "experiments"
        / "EXP-0001"
    )
    write_json(
        experiment_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate ready for inspection.",
        },
    )

    assert load_terminal_summary(experiment_dir) == {
        "outcome": "completed_candidate",
        "outcome_reason": "Locked gates passed.",
        "failed_stage": None,
        "failure_classification": None,
        "summary": "Candidate ready for inspection.",
    }


def test_record_terminal_experiment_updates_state_and_clears_active(
    tmp_path: Path,
) -> None:
    paths = ResearchProgramPaths(tmp_path / "programs" / "peer-residuals")
    experiment_dir = paths.experiment_directory("peer-residual-v1", "EXP-0001")
    state = create_initial_state(
        research_run_id="peer-residual-v1",
        max_experiments=5,
    )
    state["active_experiment_id"] = "EXP-0001"
    terminal_summary = {
        "outcome": "completed_inconclusive",
        "outcome_reason": "Gate was underpowered.",
        "failed_stage": None,
        "failure_classification": None,
        "summary": "Evidence was directionally positive only.",
    }

    record_terminal_experiment(
        state,
        experiment_id="EXP-0001",
        experiment_dir=experiment_dir,
        terminal_summary=terminal_summary,
    )

    assert state["experiment_count"] == 1
    assert state["active_experiment_id"] is None
    assert state["experiments"] == {
        "EXP-0001": {
            "id": "EXP-0001",
            "status": "terminal",
            "experiment_directory": str(experiment_dir),
            "outcome": "completed_inconclusive",
            "outcome_reason": "Gate was underpowered.",
            "failed_stage": None,
            "failure_classification": None,
        }
    }
