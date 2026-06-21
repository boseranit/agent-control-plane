from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.control_plane.usage_limit import (
    UsageLimitEvent,
    UsageLimitWait,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    ExperimentDesign,
    FeatureSpec,
    FeatureSpecs,
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
    run_experiment_flow as _run_experiment_flow,
)
from agent_control_plane.research_experiment_controller.ledger import read_ledger_events
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_completed,
    classify_invalid,
    classify_run_failed,
)
from research_helpers import write_evaluation_result_files, write_signal_panel


COMPLETED_OUTCOMES = {
    "completed_rejected",
    "completed_inconclusive",
    "completed_candidate",
}


def write_minimal_research_run_spec(
    tmp_path: Path,
    repo: Path,
    *,
    research_run_id: str = "peer-residual-v1",
    max_experiments: int = 1,
    data_root: Path | None = None,
    stop_on_prerequisites_failed: bool = True,
    worktree_create: bool = True,
    max_repairs: int = 3,
    mlflow_experiment_name: str | None = None,
) -> Path:
    init_repo_if_needed(repo)
    path = tmp_path / f"{research_run_id}.yaml"
    data_root_value = data_root or tmp_path / "data"
    experiment_data_root = tmp_path / "experiment-data"
    research_program_root = tmp_path / "programs" / research_run_id
    if data_root is None:
        data_root_value.mkdir()
    mlflow_block = ""
    if mlflow_experiment_name is not None:
        mlflow_block = f"""
mlflow:
  enabled: false
  experiment_name: {mlflow_experiment_name}
"""
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
experiment_data_root: {experiment_data_root}
research_program_root: {research_program_root}
worktree:
  create: {str(worktree_create).lower()}
{mlflow_block}
implementation:
  max_repairs: {max_repairs}
stop_on_prerequisites_failed: {str(stop_on_prerequisites_failed).lower()}
""",
        encoding="utf-8",
    )
    return path


def init_repo_if_needed(path: Path) -> None:
    if (path / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def valid_research_spec_payload() -> dict[str, object]:
    return {
        "hypothesis": "Peer residuals forecast next-month returns.",
        "target": "next_month_return",
        "prediction_horizon": "1M",
        "universe": "hyperliquid_perps",
        "label": "forward_return_1m",
        "feature_availability_assumptions": ["features lagged one bar"],
        "split": {"train": "2020-01:2024-12", "test": "2025-01:2026-01"},
        "primary_metric": "information_coefficient",
        "secondary_metrics": ["turnover"],
        "baselines": ["market_neutral_null"],
        "null_tests": ["symbol_shuffle"],
        "transaction_cost_assumptions": "5 bps",
        "success_gates": {"information_coefficient": 0.03},
        "failure_gates": {"information_coefficient": 0.0},
        "inconclusive_gates": {"min_observations": 100},
    }


def run_experiment_flow(
    request: ExperimentFlowRequest,
    *,
    selection: ExperimentFlowSelection | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    result = _run_experiment_flow(
        request,
        selection=selection,
        agent_runtime=agent_runtime,
    )
    if result.get("outcome") in COMPLETED_OUTCOMES:
        _write_completed_merge_artifacts(request, result)
    return result


def usage_limit_wait(seconds: float) -> UsageLimitWait:
    detected_at = datetime.fromisoformat("2026-06-01T10:00:00+10:00")
    return UsageLimitWait(
        UsageLimitEvent(
            role="research-controller-test",
            detected_at=detected_at,
            suggested_retry_at=detected_at + timedelta(seconds=seconds),
            sleep_seconds=seconds,
            message="Usage limit reached.",
        )
    )


def _write_completed_merge_artifacts(
    request: ExperimentFlowRequest,
    result: dict[str, Any],
) -> None:
    experiment_dir = request.experiment_directory
    if not (experiment_dir / "research_spec.json").exists():
        write_json(experiment_dir / "research_spec.json", valid_research_spec_payload())
    if not (experiment_dir / "confirmatory_evaluation_result.json").exists():
        write_json(
            experiment_dir / "confirmatory_evaluation_result.json",
            {
                "outcome": result["outcome"],
                "outcome_reason": result["outcome_reason"],
                "failed_stage": result["failed_stage"],
                "failure_classification": result["failure_classification"],
                "metrics": {},
                "gate_results": {},
                "pre_registered_evidence": [],
            },
        )
    if not (experiment_dir / "lineage.json").exists():
        write_json(
            experiment_dir / "lineage.json",
            {
                "research_run_id": request.research_run_id,
                "experiment_id": request.experiment_id,
                "experiment_dir": str(experiment_dir),
                "worktree_path": None,
                "worktree_branch": None,
                "changed_files": [],
                "implementation_summary": None,
                "reusable_for_followups": False,
            },
        )
    if not (experiment_dir / "plan_update.json").exists():
        write_json(
            experiment_dir / "plan_update.json",
            {
                "followups": [],
                "learning_updates": [],
                "blockers": [],
                "reusable_components": [],
                "superseded_idea_ids": [],
            },
        )


def _empty_research_state_payload(program_id: str) -> dict[str, object]:
    return {
        "artifact_kind": "research_state",
        "schema_version": 1,
        "program_id": program_id,
        "next_idea_number": 1,
        "idea_index": {},
        "experiment_index": {},
        "learning_updates": {},
        "known_blockers": {},
        "reusable_components": {},
        "metric_observations": [],
    }


def _write_importable_prior_experiment(prior_run: Path) -> Path:
    prior_dir = prior_run / "experiments" / "EXP-0001"
    prior_dir.mkdir(parents=True)
    worktree_root = (
        prior_run.parent.parent / "worktrees"
        if prior_run.parent.name == "runs"
        else prior_run.parent / "worktrees"
    )
    worktree = worktree_root / "prior-run" / "EXP-0001"
    write_json(
        prior_run / "state.json",
        {
            "research_run_id": "prior-run",
            "experiments": {
                "EXP-0001": {"experiment_directory": str(prior_dir)}
            },
        },
    )
    write_json(
        prior_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate.",
        },
    )
    write_json(
        prior_dir / "selected_plan.json",
        {
            "selected": True,
            "plan_id": "prior-plan",
            "rationale": "Prior selected plan.",
            "fresh_selection_reason": "Prior fresh idea.",
        },
    )
    write_json(prior_dir / "research_spec.json", valid_research_spec_payload())
    write_json(
        prior_dir / "lineage.json",
        {
            "research_run_id": "prior-run",
            "experiment_id": "EXP-0001",
            "experiment_dir": str(prior_dir),
            "worktree_path": str(worktree),
            "worktree_branch": "research/prior-run/EXP-0001",
            "changed_files": ["research/feature.py"],
            "implementation_summary": "Built prior feature.",
            "reusable_for_followups": True,
        },
    )
    write_json(
        prior_dir / "confirmatory_evaluation_result.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "metrics": {"information_coefficient": 0.04},
            "gate_results": {"information_coefficient": "passed"},
            "pre_registered_evidence": ["IC passed."],
        },
    )
    write_json(
        prior_dir / "plan_update.json",
        {
            "followups": [
                {
                    "dedupe_key": "prior-followup",
                    "title": "prior followup",
                    "kind": "direct_followup",
                    "evidence_basis": ["prior-run/EXP-0001"],
                    "mechanism": "Prior candidate opened a followup.",
                    "axis_to_vary": "turnover gate",
                    "specific_change": "Add turnover gate.",
                    "falsifying_evidence": ["Gate fails."],
                    "priority": 0.8,
                    "priority_reason": "Best prior followup.",
                    "seed_component_ids": ["prior-component"],
                }
            ],
            "learning_updates": [],
            "blockers": [],
            "reusable_components": [
                {
                    "component_key": "prior-component",
                    "summary": "Built prior feature.",
                    "reusable_for": ["prior followup"],
                    "risk_notes": [],
                }
            ],
            "superseded_idea_ids": [],
        },
    )
    return prior_dir


def valid_feature_spec_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "feature_id": "peer_residual_21d",
        "feature_name": "Peer residual 21d",
        "feature_family": "peer_residual",
        "data_source": "daily_bars_v1",
        "inputs": ["returns", "peer_groups"],
        "transformation": "Regress returns on peer basket.",
        "transformation_logic": "Regress returns on peer basket.",
        "lookback_window": "21 trading days",
        "data_timing": "Point-in-time before label.",
        "lag": "1 trading day",
        "normalization": "z-score by timestamp",
        "backfill_range": "2020-01 through 2026-01",
        "missing_data_policy": "Drop missing symbols.",
        "failure_modes": ["future constituents"],
        "availability_at_decision_time_proof": (
            "Uses timestamps <= decision timestamp."
        ),
        "expected_failure_modes": ["future constituents"],
    }
    return payload | overrides


class FlowFakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.run_inputs: list[str] = []

    def run(self, input: str, config) -> object:
        del config
        self.run_inputs.append(input)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "repair_attempt": len(self.run_inputs),
                    "summary": "Tried repair.",
                    "changed_files": [],
                }
            },
        )()


class FlowFakeRuntime:
    def __init__(self) -> None:
        self.configs = []
        self.threads: dict[str, FlowFakeThread] = {}

    def open_thread(self, config) -> FlowFakeThread:
        self.configs.append(config)
        thread_id = config.thread_id or "research-implementer-thread-1"
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = FlowFakeThread(thread_id)
            self.threads[thread_id] = thread
        return thread


class BoundaryViolatingRepairThread(FlowFakeThread):
    def run(self, input: str, config) -> object:
        (Path(config.cwd) / "outside.py").write_text("VALUE = 1\n", encoding="utf-8")
        return super().run(input, config)


class BoundaryViolatingRepairRuntime(FlowFakeRuntime):
    def open_thread(self, config) -> BoundaryViolatingRepairThread:
        self.configs.append(config)
        thread_id = config.thread_id or "research-implementer-thread-1"
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = BoundaryViolatingRepairThread(thread_id)
            self.threads[thread_id] = thread
        return thread


class EvaluationFakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.run_inputs: list[str] = []

    def run(self, input: str, config) -> object:
        self.run_inputs.append(input)
        write_evaluation_result_files(Path(config.cwd))
        return type(
            "TurnResult",
            (),
            {"final_response": {"ignored": True}},
        )()


class EvaluationFakeRuntime:
    def __init__(self) -> None:
        self.configs = []
        self.threads: dict[str, EvaluationFakeThread] = {}

    def open_thread(self, config) -> EvaluationFakeThread:
        self.configs.append(config)
        thread_id = config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = EvaluationFakeThread(thread_id)
            self.threads[thread_id] = thread
        return thread


class ResponseOnlyEvaluationThread:
    id = "research-evaluator-response-only"

    def run(self, input: str, config) -> object:
        del input, config
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "confirmatory_evaluation_result": {
                        "outcome": "completed_candidate",
                        "outcome_reason": "Ignored response.",
                        "failed_stage": None,
                        "failure_classification": None,
                        "metrics": {},
                        "gate_results": {},
                        "pre_registered_evidence": [],
                    },
                    "exploratory_diagnostics_result": {},
                    "analysis_ledger": {"entries": []},
                }
            },
        )()


class ResponseOnlyEvaluationRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config) -> ResponseOnlyEvaluationThread:
        self.configs.append(config)
        return ResponseOnlyEvaluationThread()


class MaterialCriticThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.run_inputs: list[str] = []
        self.run_configs = []

    def run(self, input: str, config) -> object:
        self.run_inputs.append(input)
        self.run_configs.append(config)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "decision": "approve",
                    "fatal_issues": [],
                    "required_revisions": [],
                    "material_revision_categories": ["split"],
                    "leakage_risks": [],
                    "baseline_concerns": [],
                    "gate_concerns": [],
                }
            },
        )()


class MaterialCriticRuntime:
    def __init__(self) -> None:
        self.configs = []
        self.threads: list[MaterialCriticThread] = []

    def open_thread(self, config) -> MaterialCriticThread:
        self.configs.append(config)
        thread = MaterialCriticThread(f"{config.role}-thread-{len(self.configs)}")
        self.threads.append(thread)
        return thread


class RejectingMaterialCriticThread(MaterialCriticThread):
    def run(self, input: str, config) -> object:
        self.run_inputs.append(input)
        self.run_configs.append(config)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "decision": "reject",
                    "fatal_issues": ["leakage risk"],
                    "required_revisions": ["restore locked split"],
                    "material_revision_categories": ["split"],
                    "leakage_risks": ["future labels"],
                    "baseline_concerns": [],
                    "gate_concerns": [],
                }
            },
        )()


class RejectingMaterialCriticRuntime(MaterialCriticRuntime):
    def open_thread(self, config) -> RejectingMaterialCriticThread:
        self.configs.append(config)
        thread = RejectingMaterialCriticThread(
            f"{config.role}-thread-{len(self.configs)}"
        )
        self.threads.append(thread)
        return thread


class DecisionMaterialCriticThread(MaterialCriticThread):
    def __init__(self, thread_id: str, decision: str) -> None:
        super().__init__(thread_id)
        self.decision = decision

    def run(self, input: str, config) -> object:
        self.run_inputs.append(input)
        self.run_configs.append(config)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "decision": self.decision,
                    "fatal_issues": [],
                    "required_revisions": [],
                    "material_revision_categories": ["split"],
                    "leakage_risks": [],
                    "baseline_concerns": [],
                    "gate_concerns": [],
                }
            },
        )()


class DecisionMaterialCriticRuntime(MaterialCriticRuntime):
    def __init__(self, decision: str) -> None:
        super().__init__()
        self.decision = decision

    def open_thread(self, config) -> DecisionMaterialCriticThread:
        self.configs.append(config)
        thread = DecisionMaterialCriticThread(
            f"{config.role}-thread-{len(self.configs)}",
            self.decision,
        )
        self.threads.append(thread)
        return thread


class FailingEvaluationThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id

    def run(self, input: str, config) -> object:
        del input, config
        raise RuntimeError("evaluation crashed")


class FailingEvaluationRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config) -> FailingEvaluationThread:
        self.configs.append(config)
        return FailingEvaluationThread(
            config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        )


class MutatingEvaluationThread(EvaluationFakeThread):
    def run(self, input: str, config) -> object:
        manifest = read_json_object(Path(config.cwd) / "manifest.json")
        selected_plan = Path(manifest["canonical_artifacts"]["selected_plan"])
        selected_plan.write_text(
            '{"selected": false, "rationale": "mutated"}\n',
            encoding="utf-8",
        )
        return super().run(input, config)


class MutatingEvaluationRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config) -> MutatingEvaluationThread:
        self.configs.append(config)
        return MutatingEvaluationThread(
            config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        )


class MutatingCrashingEvaluationThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id

    def run(self, input: str, config) -> object:
        del input
        manifest = read_json_object(Path(config.cwd) / "manifest.json")
        selected_plan = Path(manifest["canonical_artifacts"]["selected_plan"])
        selected_plan.write_text(
            '{"selected": false, "rationale": "mutated"}\n',
            encoding="utf-8",
        )
        raise RuntimeError("evaluation crashed after mutation")


class MutatingCrashingEvaluationRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config) -> MutatingCrashingEvaluationThread:
        self.configs.append(config)
        return MutatingCrashingEvaluationThread(
            config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        )


class MutatingMalformedEvaluationThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id

    def run(self, input: str, config) -> object:
        del input
        manifest = read_json_object(Path(config.cwd) / "manifest.json")
        selected_plan = Path(manifest["canonical_artifacts"]["selected_plan"])
        selected_plan.write_text(
            '{"selected": false, "rationale": "mutated"}\n',
            encoding="utf-8",
        )
        (Path(config.cwd) / "confirmatory_evaluation_result.json").write_text(
            '{"outcome": "completed_candidate"}\n',
            encoding="utf-8",
        )
        write_json(Path(config.cwd) / "exploratory_diagnostics_result.json", {})
        write_json(Path(config.cwd) / "analysis_ledger.json", {"entries": []})
        return type(
            "TurnResult",
            (),
            {"final_response": {"ignored": True}},
        )()


class MutatingMalformedEvaluationRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config) -> MutatingMalformedEvaluationThread:
        self.configs.append(config)
        return MutatingMalformedEvaluationThread(
            config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        )


def test_start_research_run_creates_run_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)

    run = start_research_run(spec_path)

    assert run.research_run_id == "peer-residual-v1"
    assert (
        run.run_directory
        == (
            tmp_path / "programs" / "peer-residual-v1" / "runs" / "peer-residual-v1"
        ).resolve()
    )
    assert run.spec_snapshot_path == run.run_directory / "research_run_spec.yaml"
    assert run.state_path == run.run_directory / "state.json"
    assert run.ledger_path == run.run_directory / "ledger.jsonl"
    assert run.experiments_directory == run.run_directory / "experiments"
    assert run.spec_snapshot_path.exists()
    assert run.state_path.exists()
    assert run.ledger_path.exists()
    assert run.experiments_directory.is_dir()
    assert read_json_object(run.paths.memory / "research_state.json") == {
        "artifact_kind": "research_state",
        "schema_version": 1,
        "program_id": "peer-residual-v1",
        "next_idea_number": 1,
        "idea_index": {},
        "experiment_index": {},
        "learning_updates": {},
        "known_blockers": {},
        "reusable_components": {},
        "metric_observations": [],
    }


def test_start_research_run_imports_prior_run_dirs_into_research_state(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prior_run = tmp_path / "prior-run"
    _write_importable_prior_experiment(prior_run)
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8")
        + f"""
continuation:
  prior_run_dirs:
    - {prior_run}
""",
        encoding="utf-8",
    )

    run = start_research_run(spec_path)

    research_state = read_json_object(run.paths.memory / "research_state.json")
    assert list(research_state["experiment_index"]) == ["prior-run/EXP-0001"]
    assert list(research_state["idea_index"]) == ["IDEA-0001"]
    assert list(research_state["reusable_components"]) == ["prior-component"]


def test_start_research_run_uses_research_program_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo_if_needed(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    program_root = tmp_path / "programs" / "peer-residuals"
    spec_path = tmp_path / "program-run.yaml"
    spec_path.write_text(
        f"""
research_run_id: peer-residual-v1
target_repository: {repo}
research_program_root: {program_root}
max_experiments: 1
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {data_root}
experiment_data_root: {tmp_path / "experiment-data"}
worktree:
  create: true
""",
        encoding="utf-8",
    )

    run = start_research_run(spec_path)

    assert run.run_directory == (program_root / "runs" / "peer-residual-v1").resolve()
    assert (program_root / "runs").is_dir()
    assert (program_root / "worktrees").is_dir()
    assert (program_root / "memory").is_dir()
    snapshot = yaml.safe_load(run.spec_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["research_program_root"] == str(program_root.resolve())
    assert snapshot["worktree"] == {"create": True}


def test_start_research_run_writes_resolved_spec_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)

    run = start_research_run(spec_path)

    snapshot = yaml.safe_load(run.spec_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["version"] == 1
    assert snapshot["research_run_id"] == "peer-residual-v1"
    assert snapshot["target_repository"] == str(repo.resolve())
    assert snapshot["research_program_root"] == str(
        (tmp_path / "programs" / "peer-residual-v1").resolve()
    )
    assert snapshot["max_experiments"] == 1
    assert snapshot["worktree"] == {"create": True}
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

    run = start_research_run(spec_path)

    state = read_json_object(run.state_path)
    assert state["research_run_id"] == "peer-residual-v1"
    assert state["current_phase"] == "initialized"
    assert state["active_experiment_id"] is None
    assert state["experiment_count"] == 0
    assert state["max_experiments"] == 1
    assert "run_directory" not in state
    assert "spec_snapshot_path" not in state

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
    start_research_run(spec_path)

    with pytest.raises(ResearchRunError, match="already exists"):
        start_research_run(spec_path)


def test_duplicate_start_with_continuation_does_not_import_prior_runs(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    research_state_path = run.paths.memory / "research_state.json"
    original_research_state = read_json_object(research_state_path)

    prior_run_dir = tmp_path / "prior-run"
    _write_importable_prior_experiment(prior_run_dir)
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8")
        + f"""
continuation:
  prior_run_dirs:
    - {prior_run_dir}
""",
        encoding="utf-8",
    )

    with pytest.raises(ResearchRunError, match="already exists"):
        start_research_run(spec_path)

    assert read_json_object(research_state_path) == original_research_state


@pytest.mark.parametrize(
    ("selected_plan_kwargs", "expected_reason"),
    [
        (
            {"selected_idea_ids": ["IDEA-0001"]},
            "Selected idea does not exist: IDEA-0001",
        ),
        (
            {
                "fresh_selection_reason": "Fresh selected plan.",
                "seed_component_ids": ["prior-component"],
            },
            "Seed component does not exist: prior-component",
        ),
    ],
)
def test_selection_references_use_persisted_memory_not_prior_run_dirs(
    tmp_path: Path,
    selected_plan_kwargs: dict[str, object],
    expected_reason: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prior_run = tmp_path / "prior-run"
    _write_importable_prior_experiment(prior_run)
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8")
        + f"""
continuation:
  prior_run_dirs:
    - {prior_run}
""",
        encoding="utf-8",
    )
    run = start_research_run(spec_path)
    research_state_path = run.paths.memory / "research_state.json"
    imported_state = read_json_object(research_state_path)
    assert "IDEA-0001" in imported_state["idea_index"]
    assert "prior-component" in imported_state["reusable_components"]
    write_json(
        research_state_path,
        _empty_research_state_payload(run.research_program_root.name),
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="followup-plan",
                    rationale="Use prior followup.",
                    **selected_plan_kwargs,
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
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

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "run_failed"
    assert summary["failure_classification"] == "runner_exception"
    assert expected_reason in summary["outcome_reason"]


def test_load_research_run_uses_snapshot_and_state_after_source_spec_deleted(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    started = start_research_run(spec_path)
    snapshot_before = yaml.safe_load(
        started.spec_snapshot_path.read_text(encoding="utf-8")
    )
    state_before = read_json_object(started.state_path)

    spec_path.unlink()

    loaded = load_research_run(
        "peer-residual-v1",
        research_program_root=started.run_directory.parents[1],
    )

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
    run = start_research_run(spec_path)
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
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
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
        research_program_root=run.run_directory.parents[1],
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


def test_memory_merge_failure_prevents_terminal_state_and_ledger_persistence(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_json(
            request.experiment_directory / "summary.json",
            {
                "outcome": "completed_candidate",
                "outcome_reason": "Locked gates passed.",
                "failed_stage": None,
                "failure_classification": None,
                "summary": "Candidate.",
            },
        )
        write_json(
            request.experiment_directory / "selected_plan.json",
            {
                "selected": True,
                "plan_id": "candidate-plan",
                "rationale": "Admissible bounded experiment.",
                "fresh_selection_reason": "Fresh selected plan.",
                "seed_component_ids": [],
            },
        )
        write_json(
            request.experiment_directory / "research_spec.json",
            valid_research_spec_payload(),
        )
        write_json(
            request.experiment_directory / "lineage.json",
            {
                "research_run_id": request.research_run_id,
                "experiment_id": request.experiment_id,
                "experiment_dir": str(request.experiment_directory),
                "worktree_path": None,
                "worktree_branch": None,
                "changed_files": [],
                "implementation_summary": None,
                "reusable_for_followups": False,
            },
        )
        write_json(
            request.experiment_directory / "confirmatory_evaluation_result.json",
            {
                "outcome": "completed_candidate",
                "outcome_reason": "Locked gates passed.",
                "failed_stage": None,
                "failure_classification": None,
                "metrics": {},
                "gate_results": {},
                "pre_registered_evidence": [],
            },
        )
        write_json(
            request.experiment_directory / "plan_update.json",
            {"followups": ["old loose followup"]},
        )
        return {"status": "experiment_completed"}

    with pytest.raises(ValidationError):
        run_research_loop(
            run.research_run_id,
            research_program_root=run.run_directory.parents[1],
            experiment_runner=experiment_runner,
        )

    state = read_json_object(run.state_path)
    events = read_ledger_events(run.ledger_path)
    research_state = read_json_object(run.paths.memory / "research_state.json")
    assert state["current_phase"] == "running_experiment"
    assert state["active_experiment_id"] == "EXP-0001"
    assert state["experiments"] == {}
    assert not any(event["event_type"] == "experiment_completed" for event in events)
    assert research_state["experiment_index"] == {}


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
    run = start_research_run(spec_path)

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
        research_program_root=run.run_directory.parents[1],
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
    run = start_research_run(spec_path)

    result = run_research_loop(
        run.research_run_id, research_program_root=run.run_directory.parents[1]
    )

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
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="plan-without-commands",
                    rationale="Design is interesting but not executable.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
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


def test_exploratory_only_design_is_blocked_without_evaluation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = EvaluationFakeRuntime()
    exploratory_design = ExperimentDesign(
        exploratory_commands=[
            {"name": "diag", "argv": [sys.executable, "diag.py"]}
        ],
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="exploratory-only-plan",
                    rationale="Diagnostics are interesting but not confirmatory.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=exploratory_design,
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")

    assert summary["outcome"] == "blocked"
    assert summary["failed_stage"] == "selection"
    assert summary["failure_classification"] == "no_deterministic_commands"
    assert runtime.configs == []
    assert not (experiment_dir / "evaluation" / "manifest.json").exists()


def test_selected_plan_cannot_return_no_op_terminal_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="selected-plan",
                    rationale="Plan selected.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
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
        research_program_root=run.run_directory.parents[1],
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
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="needs-data",
                    rationale="Plan needs data audit.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
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
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="bad-schema",
                    rationale="Plan needs schema audit.",
                    fresh_selection_reason="Fresh selected plan.",
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
        research_program_root=run.run_directory.parents[1],
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
    assert (experiment_dir / "logs" / "data_audit-1-schema-check.stdout.log").exists()
    assert (experiment_dir / "logs" / "data_audit-1-schema-check.stderr.log").exists()


def test_prerequisites_failed_stops_research_run_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        max_experiments=3,
        data_root=tmp_path / "missing-data",
    )
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"needs-data-{request.experiment_id}",
                    rationale="Plan needs data audit.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
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
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"needs-data-{request.experiment_id}",
                    rationale="Plan needs data audit.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
                ),
            ),
        )

    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    assert result["experiments_completed"] == 2
    assert state["status"] == "completed"
    assert state["experiments"]["EXP-0001"]["outcome"] == "prerequisites_failed"
    assert state["experiments"]["EXP-0002"]["outcome"] == "prerequisites_failed"


def test_worktree_create_false_rejects_selected_design_that_needs_edits(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        worktree_create=False,
    )
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="editing-plan",
                    rationale="Needs implementation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    allowed_write_paths=["src"],
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "invalid"
    assert summary["failed_stage"] == "implementation"
    assert summary["failure_classification"] == "worktree_disabled_for_editing"
    assert not (
        run.run_directory.parents[1] / "worktrees" / run.research_run_id
    ).exists()


def test_worktree_create_false_allows_read_only_selected_design(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        worktree_create=False,
    )
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="read-only-plan",
                    rationale="Evaluate locked artifacts only.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Read-only evaluation inconclusive.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Read-only evaluation inconclusive.",
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "completed_inconclusive"
    assert not (
        run.run_directory.parents[1] / "worktrees" / run.research_run_id
    ).exists()


def test_experiment_data_root_uses_experiment_name_and_run_name(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(
        tmp_path,
        repo,
        mlflow_experiment_name="peer residual / alpha v1",
    )
    run = start_research_run(spec_path)
    expected_root = (
        tmp_path
        / "experiment-data"
        / "peer-residual-alpha-v1"
        / "peer-residual-v1-EXP-0001"
    ).resolve()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="panel-plan",
                    rationale="Materialize signal panel for evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {
                            "name": "write-panel",
                            "argv": [
                                sys.executable,
                                "-c",
                                (
                                    "import os, pathlib; "
                                    "root = pathlib.Path(os.environ['RESEARCH_EXPERIMENT_DATA_ROOT']); "
                                    f"assert root == pathlib.Path({str(expected_root)!r}); "
                                    "(root / 'runtime-data').mkdir(parents=True, exist_ok=True); "
                                    "(root / 'signal_panel.parquet').write_bytes(b'PAR1')"
                                ),
                            ],
                        }
                    ],
                    expected_outputs=[
                        "$RESEARCH_EXPERIMENT_DATA_ROOT/signal_panel.parquet"
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Panel materialized.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Panel materialized.",
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    assert (expected_root / "signal_panel.parquet").read_bytes() == b"PAR1"
    assert not (
        tmp_path / "experiment-data" / "peer-residual-v1" / "peer-residual-v1-EXP-0001"
    ).exists()


def test_agent_declared_material_revision_gets_fresh_critic_review(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MaterialCriticRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="revised-plan",
                    rationale="Split changed after critique.",
                    fresh_selection_reason="Fresh selected plan.",
                    material_revision_categories=["split"],
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                prior_research_spec=valid_research_spec_payload(),
                research_spec=valid_research_spec_payload(),
                feature_specs=FeatureSpecs(
                    features=[
                        FeatureSpec(
                            feature_id="peer_residual_21d",
                            feature_name="Peer residual 21d",
                            feature_family="peer_residual",
                            data_source="daily_bars_v1",
                            inputs=["returns", "peer_groups"],
                            transformation="Regress returns on peer basket.",
                            transformation_logic="Regress returns on peer basket.",
                            lookback_window="21 trading days",
                            data_timing="Point-in-time before label.",
                            lag="1 trading day",
                            normalization="z-score by timestamp",
                            backfill_range="2020-01 through 2026-01",
                            missing_data_policy="Drop missing symbols.",
                            failure_modes=["future constituents"],
                            availability_at_decision_time_proof=(
                                "Uses timestamps <= decision timestamp."
                            ),
                            expected_failure_modes=["future constituents"],
                        )
                    ]
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Read-only evaluation inconclusive.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Read-only evaluation inconclusive.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    critique = read_json_object(experiment_dir / "material_revision_critique.json")
    summary = read_json_object(experiment_dir / "summary.json")
    events = read_ledger_events(run.ledger_path)

    assert critique["decision"] == "approve"
    assert summary["outcome"] == "completed_inconclusive"
    assert any(
        event["event_type"] == "material_revision_critic_review"
        and event["critic_thread_id"] == "research-critic-thread-1"
        and event["material_revision_categories"] == ["split"]
        for event in events
    )


def test_controller_detected_material_revision_gets_fresh_critic_review(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MaterialCriticRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="metric-revision",
                    rationale="Primary metric revised.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                prior_research_spec=valid_research_spec_payload(),
                research_spec={
                    **valid_research_spec_payload(),
                    "primary_metric": "rank_information_coefficient",
                },
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Verification passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Verification passed.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    events = read_ledger_events(run.ledger_path)
    experiment_dir = run.experiments_directory / "EXP-0001"
    critique = read_json_object(experiment_dir / "material_revision_critique.json")

    assert critique["decision"] == "approve"
    assert any(
        event["event_type"] == "material_revision_critic_review"
        and event["material_revision_categories"] == ["primary_metric"]
        for event in events
    )


@pytest.mark.parametrize(
    ("field", "old_value", "new_value"),
    [
        ("data_source", "daily_bars_v1", "daily_bars_v2"),
        ("feature_family", "peer_residual", "volume_residual"),
    ],
)
def test_controller_detects_feature_spec_material_revision(
    tmp_path: Path,
    field: str,
    old_value: str,
    new_value: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MaterialCriticRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"{field}-revision",
                    rationale="Feature spec changed.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                prior_research_spec=valid_research_spec_payload(),
                research_spec=valid_research_spec_payload(),
                prior_feature_specs=FeatureSpecs(
                    features=[
                        FeatureSpec(**valid_feature_spec_payload(**{field: old_value}))
                    ]
                ),
                feature_specs=FeatureSpecs(
                    features=[
                        FeatureSpec(**valid_feature_spec_payload(**{field: new_value}))
                    ]
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Verification passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Verification passed.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    events = read_ledger_events(run.ledger_path)
    experiment_dir = run.experiments_directory / "EXP-0001"
    critique = read_json_object(experiment_dir / "material_revision_critique.json")

    assert critique["decision"] == "approve"
    assert any(
        event["event_type"] == "material_revision_critic_review"
        and event["material_revision_categories"] == [field]
        for event in events
    )


def test_rejected_material_revision_blocks_experiment(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = RejectingMaterialCriticRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="bad-revision",
                    rationale="Split changed after critique.",
                    fresh_selection_reason="Fresh selected plan.",
                    material_revision_categories=["split"],
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_candidate,
                    outcome_reason="Should not run.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Should not run.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    critique = read_json_object(experiment_dir / "material_revision_critique.json")
    summary = read_json_object(experiment_dir / "summary.json")

    assert critique["decision"] == "reject"
    assert summary["outcome"] == "invalid"
    assert summary["failed_stage"] == "critic_review"
    assert summary["failure_classification"] == "material_revision_rejected"
    assert "leakage risk" in summary["outcome_reason"]
    assert "restore locked split" in summary["outcome_reason"]
    assert not (experiment_dir / "data_audit.json").exists()


@pytest.mark.parametrize(
    "decision",
    ["revision_required", "revision-required", "requires revision", "fatal"],
)
def test_revision_required_material_critic_decisions_block_experiment(
    tmp_path: Path,
    decision: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = DecisionMaterialCriticRuntime(decision)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id=f"{decision}-revision",
                    rationale="Split changed after critique.",
                    fresh_selection_reason="Fresh selected plan.",
                    material_revision_categories=["split"],
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_candidate,
                    outcome_reason="Should not run.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Should not run.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")

    assert summary["outcome"] == "invalid"
    assert summary["failed_stage"] == "critic_review"
    assert summary["failure_classification"] == "material_revision_rejected"
    assert not (experiment_dir / "data_audit.json").exists()


def test_non_material_revision_does_not_get_fresh_critic_review(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MaterialCriticRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="formatting-revision",
                    rationale="Command formatting changed only.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                prior_research_spec={
                    "target": "return_1m",
                    "command_formatting": "python eval.py",
                },
                research_spec={
                    "target": "return_1m",
                    "command_formatting": "python ./eval.py",
                },
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_inconclusive,
                    outcome_reason="Verification passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Verification passed.",
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"

    assert runtime.configs == []
    assert not (experiment_dir / "material_revision_critique.json").exists()


def test_material_revision_without_runtime_is_invalid(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="unreviewed-revision",
                    rationale="Revision declared material.",
                    fresh_selection_reason="Fresh selected plan.",
                    material_revision_categories=["success gate"],
                ),
                experiment_design=ExperimentDesign(
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")

    assert summary["outcome"] == "invalid"
    assert summary["failed_stage"] == "critic_review"
    assert summary["failure_classification"] == "material_revision_unreviewed"


def test_selected_confirmatory_only_experiment_gets_default_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked confirmatory commands.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_candidate,
                    outcome_reason="Confirmatory result passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Confirmatory result passed.",
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    worktree = (
        run.run_directory.parents[1] / "worktrees" / "peer-residual-v1" / "EXP-0001"
    )
    assert worktree.is_dir()


def test_selected_editable_experiment_gets_preserved_worktree_by_default(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="editing-plan",
                    rationale="Needs implementation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    allowed_write_paths=["src"],
                    verification_commands=[
                        {"name": "unit", "argv": [sys.executable, "-c", "pass"]}
                    ],
                ),
                terminal_summary=Summary(
                    outcome=ResearchOutcome.completed_candidate,
                    outcome_reason="Verification passed.",
                    failed_stage=None,
                    failure_classification=None,
                    summary="Candidate ready.",
                ),
            ),
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    worktree = (
        run.run_directory.parents[1] / "worktrees" / "peer-residual-v1" / "EXP-0001"
    )
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "completed_candidate"
    assert worktree.is_dir()
    assert (worktree / "README.md").read_text(encoding="utf-8") == "ready\n"


def test_verification_repairs_reuse_same_implementer_thread_until_limit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo, max_repairs=2)
    run = start_research_run(spec_path)
    runtime = FlowFakeRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="editing-plan",
                    rationale="Needs implementation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    allowed_write_paths=["src"],
                    verification_commands=[
                        {
                            "name": "unit",
                            "argv": [sys.executable, "-c", "raise SystemExit(4)"],
                        }
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    metrics = read_json_object(experiment_dir / "command_metrics.json")
    events = read_ledger_events(run.ledger_path)

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "verification"
    assert summary["failure_classification"] == "verification_command_failed"
    assert metrics["command_count"] == 3
    assert metrics["failed_count"] == 3
    assert (experiment_dir / "implementation_repair_1.json").exists()
    assert (experiment_dir / "implementation_repair_2.json").exists()
    repair_events = [
        event
        for event in events
        if event["event_type"] == "implementation_repair_attempt"
    ]
    assert repair_events == [
        {
            "event_type": "implementation_repair_attempt",
            "research_run_id": "peer-residual-v1",
            "experiment_id": "EXP-0001",
            "repair_attempt": 1,
            "verification_attempt": 0,
            "failed_command_count": 1,
            "implementer_thread_id": "research-implementer-thread-1",
        },
        {
            "event_type": "implementation_repair_attempt",
            "research_run_id": "peer-residual-v1",
            "experiment_id": "EXP-0001",
            "repair_attempt": 2,
            "verification_attempt": 1,
            "failed_command_count": 1,
            "implementer_thread_id": "research-implementer-thread-1",
        },
    ]


def test_selection_path_audits_repair_boundary_before_verification_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo, max_repairs=1)
    run = start_research_run(spec_path)
    runtime = BoundaryViolatingRepairRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="editing-plan",
                    rationale="Needs implementation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    allowed_write_paths=["src"],
                    verification_commands=[
                        {
                            "name": "unit",
                            "argv": [sys.executable, "-c", "raise SystemExit(4)"],
                        }
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    diff_summary = read_json_object(experiment_dir / "implementation_diff_summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "implementation_boundary_audit"
    assert summary["failure_classification"] == "allowed_path_violation"
    assert diff_summary["allowed_path_violations"] == ["outside.py"]


def test_evaluator_runs_in_workspace_and_writes_result_artifacts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = EvaluationFakeRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                    exploratory_commands=[
                        {"name": "diag", "argv": [sys.executable, "diag.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    evaluation_dir = experiment_dir / "evaluation"
    summary = read_json_object(experiment_dir / "summary.json")
    confirmatory = read_json_object(
        experiment_dir / "confirmatory_evaluation_result.json"
    )
    exploratory = read_json_object(
        experiment_dir / "exploratory_diagnostics_result.json"
    )
    analysis_ledger = read_json_object(experiment_dir / "analysis_ledger.json")

    assert [config.role for config in runtime.configs] == ["research-evaluator"]
    assert runtime.configs[0].cwd == evaluation_dir
    assert confirmatory["outcome"] == "completed_candidate"
    assert exploratory["findings"] == ["turnover stable"]
    assert analysis_ledger["entries"][0]["phase"] == "evaluation"
    assert summary["outcome"] == "completed_candidate"
    assert summary["confirmatory_findings"] == ["confirmatory command eval"]
    assert summary["exploratory_findings"] == ["turnover stable"]


def test_evaluation_requires_workspace_result_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = ResponseOnlyEvaluationRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")

    assert [config.role for config in runtime.configs] == ["research-evaluator"]
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation"
    assert summary["failure_classification"] == "evaluation_runtime_defect"
    assert "confirmatory_evaluation_result.json" in summary["outcome_reason"]
    assert not (experiment_dir / "confirmatory_evaluation_result.json").exists()


@pytest.mark.parametrize("usage_limit_mode", ["result", "exception"])
def test_usage_limit_pause_removes_external_signal_panel_before_retry(
    tmp_path: Path,
    usage_limit_mode: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    attempts: list[str] = []
    paused_signal_panels: list[Path] = []
    selection = ExperimentFlowSelection(
        selected_plan=SelectedPlan(
            selected=True,
            plan_id="confirmatory-plan",
            rationale="Run locked evaluation.",
            fresh_selection_reason="Fresh selected plan.",
        ),
        experiment_design=ExperimentDesign(
            confirmatory_commands=[
                {"name": "eval", "argv": [sys.executable, "eval.py"]}
            ],
        ),
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        attempts.append(request.experiment_id)
        if len(attempts) == 1:
            paused_signal_panels.append(write_signal_panel(request))
            if usage_limit_mode == "exception":
                raise usage_limit_wait(0.0)
            return {"status": "usage_limit_wait", "sleep_seconds": 0.0}
        return run_experiment_flow(request, selection=selection)

    paused = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )
    assert paused["status"] == "usage_limit_wait"
    assert not paused_signal_panels[0].exists()

    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result["status"] == "completed"
    assert attempts == ["EXP-0001", "EXP-0001"]
    assert summary["outcome"] == "invalid"
    assert summary["failure_classification"] == "missing_terminal_summary"


def test_feature_specs_are_written_and_locked_for_evaluation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = EvaluationFakeRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="feature-plan",
                    rationale="Evaluate material signal feature.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
                research_spec=valid_research_spec_payload(),
                prior_research_spec=valid_research_spec_payload(),
                feature_specs=FeatureSpecs(
                    features=[
                        FeatureSpec(
                            feature_id="peer_residual_21d",
                            feature_name="Peer residual 21d",
                            feature_family="peer_residual",
                            data_source="daily_bars_v1",
                            inputs=["returns", "peer_groups"],
                            transformation="Regress returns on peer basket.",
                            transformation_logic="Regress returns on peer basket.",
                            lookback_window="21 trading days",
                            data_timing="Point-in-time before label.",
                            lag="1 trading day",
                            normalization="z-score by timestamp",
                            backfill_range="2020-01 through 2026-01",
                            missing_data_policy="Drop missing symbols.",
                            failure_modes=["future constituents"],
                            availability_at_decision_time_proof=(
                                "Uses timestamps <= decision timestamp."
                            ),
                            expected_failure_modes=["future constituents"],
                        )
                    ]
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    feature_specs_path = experiment_dir / "feature_specs.json"
    research_spec_path = experiment_dir / "research_spec.json"
    feature_specs = read_json_object(feature_specs_path)
    research_spec = read_json_object(research_spec_path)
    manifest = read_json_object(experiment_dir / "evaluation" / "manifest.json")

    assert research_spec["primary_metric"] == "information_coefficient"
    assert feature_specs["features"][0]["feature_id"] == "peer_residual_21d"
    assert manifest["canonical_artifacts"]["research_spec"] == str(
        research_spec_path.resolve()
    )
    assert manifest["canonical_artifacts"]["feature_specs"] == str(
        feature_specs_path.resolve()
    )
    assert str(research_spec_path.resolve()) in manifest["locked_artifact_hashes"]
    assert str(feature_specs_path.resolve()) in manifest["locked_artifact_hashes"]


def test_partial_research_spec_is_rejected_before_evaluation_lock(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = EvaluationFakeRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="partial-spec-plan",
                    rationale="Evaluate partial research spec.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
                research_spec={
                    "target": "return_1m",
                    "label": "forward_return_1m",
                    "universe": "top_200",
                    "primary_metric": "ic",
                },
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failure_classification"] == "runner_exception"
    assert "hypothesis" in summary["outcome_reason"]
    assert runtime.configs == []
    assert not (experiment_dir / "research_spec.json").exists()
    assert not (experiment_dir / "evaluation" / "manifest.json").exists()


def test_evaluation_runtime_defect_records_run_failed_without_implementer_reroute(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = FailingEvaluationRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert [config.role for config in runtime.configs] == ["research-evaluator"]
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation"
    assert summary["failure_classification"] == "evaluation_runtime_defect"
    assert summary["outcome_reason"] == "evaluation crashed"


def test_evaluation_boundary_failure_records_run_failed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MutatingEvaluationRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    research_state = read_json_object(run.paths.memory / "research_state.json")
    assert [config.role for config in runtime.configs] == ["research-evaluator"]
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation_boundary_audit"
    assert summary["failure_classification"] == "evaluation_boundary_violation"
    assert not (experiment_dir / "confirmatory_evaluation_result.json").exists()
    assert not (experiment_dir / "exploratory_diagnostics_result.json").exists()
    assert not (experiment_dir / "analysis_ledger.json").exists()
    assert research_state["metric_observations"] == []


def test_evaluation_boundary_failure_wins_after_malformed_evaluator_file(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MutatingMalformedEvaluationRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation_boundary_audit"
    assert summary["failure_classification"] == "evaluation_boundary_violation"


def test_evaluation_boundary_failure_wins_after_evaluator_crash(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)
    runtime = MutatingCrashingEvaluationRuntime()

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="confirmatory-plan",
                    rationale="Run locked evaluation.",
                    fresh_selection_reason="Fresh selected plan.",
                ),
                experiment_design=ExperimentDesign(
                    confirmatory_commands=[
                        {"name": "eval", "argv": [sys.executable, "eval.py"]}
                    ],
                ),
            ),
            agent_runtime=runtime,
        )

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation_boundary_audit"
    assert summary["failure_classification"] == "evaluation_boundary_violation"


def test_terminal_summary_routes_to_experiment_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        write_signal_panel(request)
        return run_experiment_flow(
            request,
            selection=ExperimentFlowSelection(
                selected_plan=SelectedPlan(
                    selected=True,
                    plan_id="candidate-plan",
                    rationale="Admissible bounded experiment.",
                    fresh_selection_reason="Fresh selected plan.",
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
        research_program_root=run.run_directory.parents[1],
        experiment_runner=experiment_runner,
    )

    state = read_json_object(run.state_path)
    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    assert state["experiments"]["EXP-0001"] == {
        "id": "EXP-0001",
        "status": "terminal",
        "experiment_directory": str(experiment_dir),
        "outcome": "completed_candidate",
        "outcome_reason": "Locked gates passed.",
        "failed_stage": None,
        "failure_classification": None,
        "lineage_path": str(experiment_dir / "lineage.json"),
        "worktree_path": str(
            run.run_directory.parents[1] / "worktrees" / "peer-residual-v1" / "EXP-0001"
        ),
        "worktree_branch": "research/peer-residual-v1/EXP-0001",
        "changed_files": [],
    }
    assert summary["outcome"] == "completed_candidate"
    assert summary["confirmatory_findings"] == ["IC 0.04"]


def test_non_completed_runner_result_records_run_failed_experiment(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_research_run_spec(tmp_path, repo)
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return {
            "status": "agent_unavailable",
            "outcome_reason": "Strategist did not return a selected plan.",
        }

    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
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
    run = start_research_run(spec_path)

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        raise RuntimeError("agent crashed")

    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
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
