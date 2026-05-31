from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.artifacts import (
    ExperimentDesign,
    ResearchOutcome,
    SelectedPlan,
    Summary,
)
from agent_control_plane.research_experiment_controller.controller import (
    ResearchRunError,
    load_research_run,
    run_research_loop,
    start_research_run,
)
from agent_control_plane.research_experiment_controller.experiment_flow import (
    ExperimentFlowRequest,
    ExperimentFlowSelection,
    run_experiment_flow,
)
from agent_control_plane.research_experiment_controller.ledger import read_ledger_events
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_completed,
    classify_invalid,
    classify_run_failed,
)


def write_minimal_research_run_spec(
    tmp_path: Path,
    repo: Path,
    *,
    research_run_id: str = "peer-residual-v1",
    max_experiments: int = 1,
    data_root: Path | None = None,
    stop_on_prerequisites_failed: bool = True,
) -> Path:
    path = tmp_path / f"{research_run_id}.yaml"
    data_root_value = data_root or tmp_path / "data"
    if data_root is None:
        data_root_value.mkdir()
    path.write_text(
        f"""
research_run_id: {research_run_id}
target_repository: {repo}
max_experiments: {max_experiments}
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {data_root_value}
stop_on_prerequisites_failed: {str(stop_on_prerequisites_failed).lower()}
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


def test_run_research_loop_repeats_until_max_experiments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=2,
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    seen: list[str] = []

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        seen.append(request.experiment_id)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"plan-{request.experiment_id}",
                    rationale="Admissible bounded experiment.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_rejected,
                    outcome_reason="Locked gate failed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Experiment rejected.",
                ),
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    assert result == {
        "status": "completed",
        "research_run_id": "peer-residual-v1",
        "experiments_completed": 2,
    }
    assert seen == ["EXP-0001", "EXP-0002"]
    assert state["status"] == "completed"
    assert state["current_phase"] == "completed"
    assert state["experiment_count"] == 2
    assert list(state["experiments"]) == ["EXP-0001", "EXP-0002"]


def test_run_research_loop_continues_after_no_op_until_max_experiments(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=2,
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=False,
                    rationale="No admissible experiment selected.",
                ),
                experiment_design=None,
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    first_summary = read_json_object(
        run.experiments_directory / "EXP-0001" / "summary.json"
    )
    second_summary = read_json_object(
        run.experiments_directory / "EXP-0002" / "summary.json"
    )
    assert result == {
        "status": "completed",
        "research_run_id": "peer-residual-v1",
        "experiments_completed": 2,
    }
    assert state["experiments"]["EXP-0001"]["outcome"] == "no_op"
    assert state["experiments"]["EXP-0002"]["outcome"] == "no_op"
    assert first_summary["outcome"] == "no_op"
    assert first_summary["failed_stage"] is None
    assert first_summary["failure_classification"] is None
    assert second_summary["outcome"] == "no_op"


def test_run_research_loop_default_skeleton_records_no_ops_until_max(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=3,
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    result = run_research_loop(run.research_run_id, runtime_root=tmp_path / "runs")

    state = read_json_object(run.state_path)
    first_selected_plan = read_json_object(
        run.experiments_directory / "EXP-0001" / "selected_plan.json"
    )
    third_selected_plan = read_json_object(
        run.experiments_directory / "EXP-0003" / "selected_plan.json"
    )
    assert result["experiments_completed"] == 3
    assert first_selected_plan["selected"] is False
    assert third_selected_plan["selected"] is False
    assert state["experiments"]["EXP-0001"]["outcome"] == "no_op"
    assert state["experiments"]["EXP-0002"]["outcome"] == "no_op"
    assert state["experiments"]["EXP-0003"]["outcome"] == "no_op"


def test_selected_plan_without_deterministic_commands_is_blocked(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="plan-without-commands",
                    rationale="Design is interesting but not executable.",
                ),
                experiment_design=ExperimentDesign(),
            ),
        )

    run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    selected_plan = read_json_object(
        run.experiments_directory / "EXP-0001" / "selected_plan.json"
    )
    assert selected_plan["selected"] is True
    assert state["experiments"]["EXP-0001"]["outcome"] == "blocked"
    assert summary["outcome"] == "blocked"
    assert summary["failed_stage"] == "selection"
    assert summary["failure_classification"] == "no_deterministic_commands"


def test_selected_plan_cannot_return_no_op_terminal_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="selected-plan",
                    rationale="Plan selected.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.no_op,
                    outcome_reason="No admissible experiment selected.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="No-op should not be accepted for selected plan.",
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert state["experiments"]["EXP-0001"]["outcome"] == "invalid"
    assert summary["outcome"] == "invalid"
    assert summary["failed_stage"] == "selection"
    assert summary["failure_classification"] == "selected_plan_returned_no_op"


def test_missing_data_root_writes_data_audit_and_summary_before_terminal_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        data_root=tmp_path / "missing-data",
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="needs-data",
                    rationale="Plan needs data audit.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    state = read_json_object(run.state_path)
    data_audit = read_json_object(experiment_dir / "data_audit.json")
    summary = read_json_object(experiment_dir / "summary.json")

    assert state["experiments"]["EXP-0001"]["outcome"] == "prerequisites_failed"
    assert data_audit == {
        "passed": False,
        "outcome": "prerequisites_failed",
        "outcome_reason": "Data/prerequisite audit failed: data_root_missing.",
        "failed_stage": "data_audit",
        "failure_classification": "data_root_missing",
        "command_results": [],
    }
    assert summary["outcome"] == "prerequisites_failed"
    assert summary["failed_stage"] == "data_audit"
    assert summary["failure_classification"] == "data_root_missing"


def test_failed_data_audit_command_writes_summary_and_command_artifacts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="bad-schema",
                    rationale="Plan needs schema audit.",
                ),
                experiment_design=ExperimentDesign(
                    data_audit_commands=[
                        {
                            "name": "schema-check",
                            "argv": [sys.executable, "-c", "raise SystemExit(2)"],
                        }
                    ],
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    state = read_json_object(run.state_path)
    data_audit = read_json_object(experiment_dir / "data_audit.json")
    metrics = read_json_object(experiment_dir / "command_metrics.json")
    summary = read_json_object(experiment_dir / "summary.json")

    assert state["experiments"]["EXP-0001"]["outcome"] == "prerequisites_failed"
    assert data_audit["failed_stage"] == "data_audit"
    assert data_audit["failure_classification"] == "prerequisite_command_failed"
    assert data_audit["command_results"][0]["name"] == "schema-check"
    assert summary["outcome"] == "prerequisites_failed"
    assert summary["failed_stage"] == "data_audit"
    assert metrics["failed_count"] == 1
    assert (experiment_dir / "commands" / "data_audit_1_stdout.log").exists()
    assert (experiment_dir / "commands" / "data_audit_1_stderr.log").exists()


def test_prerequisites_failed_stops_research_run_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=3,
        data_root=tmp_path / "missing-data",
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"needs-data-{request.experiment_id}",
                    rationale="Plan needs data audit.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    assert result["experiments_completed"] == 1
    assert state["status"] == "completed"
    assert list(state["experiments"]) == ["EXP-0001"]
    assert state["experiments"]["EXP-0001"]["outcome"] == "prerequisites_failed"


def test_stop_on_prerequisites_failed_false_continues_to_max_experiments(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=2,
        data_root=tmp_path / "missing-data",
        stop_on_prerequisites_failed=False,
    )
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"needs-data-{request.experiment_id}",
                    rationale="Plan needs data audit.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    assert result["experiments_completed"] == 2
    assert state["status"] == "completed"
    assert state["experiments"]["EXP-0001"]["outcome"] == "prerequisites_failed"
    assert state["experiments"]["EXP-0002"]["outcome"] == "prerequisites_failed"


def test_terminal_summary_routes_to_experiment_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="candidate-plan",
                    rationale="Admissible bounded experiment.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": ["python", "eval.py"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_candidate,
                    outcome_reason="Locked gates passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Candidate ready for inspection.",
                    confirmatory_findings=["IC 0.04"],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert state["experiments"]["EXP-0001"] == {
        "id": "EXP-0001",
        "status": "terminal",
        "experiment_directory": str(run.experiments_directory / "EXP-0001"),
        "outcome": "completed_candidate",
        "outcome_reason": "Locked gates passed.",
        "failed_stage": None,
        "failure_classification": None,
    }
    assert summary["outcome"] == "completed_candidate"
    assert summary["confirmatory_findings"] == ["IC 0.04"]


def test_non_completed_runner_result_records_run_failed_experiment(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return {
            "status": "agent_unavailable",
            "outcome_reason": "Strategist did not return a selected plan.",
        }

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result == {
        "status": "completed",
        "research_run_id": "peer-residual-v1",
        "experiments_completed": 1,
    }
    assert state["active_experiment_id"] is None
    assert state["current_phase"] == "completed"
    assert state["experiments"]["EXP-0001"]["outcome"] == "run_failed"
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "controller"
    assert summary["failure_classification"] == "agent_unavailable"


def test_runner_exception_records_run_failed_experiment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        raise RuntimeError("agent crashed")

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result["experiments_completed"] == 1
    assert state["active_experiment_id"] is None
    assert state["experiments"]["EXP-0001"]["outcome"] == "run_failed"
    assert summary["outcome_reason"] == "agent crashed"
    assert summary["failure_classification"] == "runner_exception"


def test_outcome_classification_hooks_return_summary_artifacts() -> None:
    invalid = classify_invalid("Critic found leakage.")
    run_failed = classify_run_failed("Evaluator crashed.")
    completed = classify_completed(
        ResearchOutcome.completed_inconclusive,
        "Locked gate underpowered.",
    )

    assert invalid.model_dump(mode="json")["outcome"] == "invalid"
    assert run_failed.model_dump(mode="json")["outcome"] == "run_failed"
    assert completed.model_dump(mode="json") == {
        "outcome": "completed_inconclusive",
        "outcome_reason": "Locked gate underpowered.",
        "failed_stage": None,
        "failure_classification": None,
        "summary": "Locked gate underpowered.",
        "confirmatory_findings": [],
        "exploratory_findings": [],
    }
