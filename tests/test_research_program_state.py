from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    PlanUpdate,
    SelectedPlan,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.research_state import (
    IdeaRecord,
    ResearchState,
    ensure_research_state,
    load_research_state,
    merge_terminal_experiment,
    research_state_path,
    write_research_state,
)


def test_old_string_plan_update_followups_are_rejected() -> None:
    payload = _typed_plan_update_payload()
    payload["followups"] = ["loose text"]

    with pytest.raises(ValidationError):
        PlanUpdate.model_validate(payload)


def test_plan_update_requires_all_typed_card_lists() -> None:
    with pytest.raises(ValidationError):
        PlanUpdate.model_validate({"followups": []})


def test_typed_plan_update_rejects_coercion() -> None:
    payload = _typed_plan_update_payload()
    payload["followups"][0]["priority"] = "0.8"

    with pytest.raises(ValidationError):
        PlanUpdate.model_validate(payload)


def test_selected_plan_requires_frontier_ids_or_fresh_reason() -> None:
    with pytest.raises(ValidationError):
        SelectedPlan(selected=True, rationale="Missing selection source.")

    with pytest.raises(ValidationError):
        SelectedPlan(
            selected=True,
            rationale="Conflicting selection source.",
            selected_idea_ids=["IDEA-0001"],
            fresh_selection_reason="Fresh too.",
        )

    with pytest.raises(ValidationError):
        SelectedPlan.model_validate(
            {
                "selected": "true",
                "rationale": "Coerced bool.",
                "fresh_selection_reason": "Fresh.",
            }
        )

    with pytest.raises(ValidationError):
        SelectedPlan(
            selected=False,
            rationale="No-op cannot carry frontier refs.",
            selected_idea_ids=["IDEA-0001"],
        )


def test_malformed_research_state_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "research_state.json"
    write_json(path, {"artifact_kind": "wrong"})

    with pytest.raises(ValidationError):
        load_research_state(path)

    write_json(path, {"artifact_kind": "research_state", "schema_version": 1})

    with pytest.raises(ValidationError):
        load_research_state(path)


def test_research_state_rejects_missing_seed_component(tmp_path: Path) -> None:
    path = tmp_path / "research_state.json"
    write_json(
        path,
        {
            "artifact_kind": "research_state",
            "schema_version": 1,
            "ideas": {
                "IDEA-0001": {
                    "dedupe_key": "bad-seed",
                    "title": "Bad seed",
                    "kind": "direct_followup",
                    "evidence_basis": ["run-1/EXP-0001"],
                    "mechanism": "Bad seed.",
                    "axis_to_vary": "seed",
                    "specific_change": "Use missing component.",
                    "falsifying_evidence": ["Missing component."],
                    "priority": 0.1,
                    "priority_reason": "Malformed fixture.",
                    "seed_component_ids": ["missing-component"],
                    "source_experiments": ["run-1/EXP-0001"],
                    "status": "pending",
                }
            },
            "experiments": {
                "run-1/EXP-0001": {
                    "experiment_dir": "/tmp/run-1/EXP-0001",
                    "outcome": "completed_candidate",
                }
            },
            "learning_updates": {},
            "known_blockers": {},
            "reusable_components": {},
            "metric_observations": [],
        },
    )

    with pytest.raises(ValidationError):
        load_research_state(path)


def test_merge_terminal_experiment_updates_research_state_once(
    tmp_path: Path,
) -> None:
    paths = ResearchProgramPaths(tmp_path / "program")
    paths.create_directories()
    ensure_research_state(paths)
    experiment_dir = paths.experiment_directory("run-1", "EXP-0001")
    worktree = paths.worktree_directory("run-1", "EXP-0001")
    _write_terminal_artifacts(experiment_dir, worktree)

    state = merge_terminal_experiment(
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
        experiment_dir=experiment_dir,
    )
    state = merge_terminal_experiment(
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
        experiment_dir=experiment_dir,
    )

    persisted = read_json_object(research_state_path(paths))
    assert list(state.experiments) == ["run-1/EXP-0001"]
    assert list(state.ideas) == ["IDEA-0001"]
    assert state.ideas["IDEA-0001"].dedupe_key == "vary-liquidity"
    assert state.reusable_components["component-current"].changed_files == [
        "research/feature.py"
    ]
    assert persisted["metric_observations"] == [
        {
            "metric_path": "ic",
            "source_experiment": "run-1/EXP-0001",
            "value": 0.04,
        },
        {
            "metric_path": "nested.ir",
            "source_experiment": "run-1/EXP-0001",
            "value": 1.2,
        },
    ]


def test_selected_idea_status_transition_is_canonical(tmp_path: Path) -> None:
    paths = ResearchProgramPaths(tmp_path / "program")
    paths.create_directories()
    write_research_state(
        research_state_path(paths),
        ResearchState(
            artifact_kind="research_state",
            schema_version=1,
            experiments={
                "run-0/EXP-0001": {
                    "experiment_dir": str(
                        paths.experiment_directory("run-0", "EXP-0001")
                    ),
                    "outcome": "completed_inconclusive",
                }
            },
            ideas={
                "IDEA-0001": IdeaRecord(
                    dedupe_key="existing",
                    title="Existing idea",
                    kind="direct_followup",
                    evidence_basis=["run-0/EXP-0001"],
                    mechanism="Known mechanism.",
                    axis_to_vary="gate",
                    specific_change="Run existing idea.",
                    falsifying_evidence=["Gate fails."],
                    priority=0.5,
                    priority_reason="Existing frontier.",
                    seed_component_ids=[],
                    source_experiments=["run-0/EXP-0001"],
                )
            },
            learning_updates={},
            known_blockers={},
            reusable_components={},
            metric_observations=[],
        ),
    )
    experiment_dir = paths.experiment_directory("run-1", "EXP-0001")
    _write_minimal_terminal_artifacts(
        experiment_dir,
        selected_plan={
            "selected": True,
            "rationale": "Use existing idea.",
            "selected_idea_ids": ["IDEA-0001"],
            "fresh_selection_reason": None,
            "seed_component_ids": [],
        },
    )

    state = merge_terminal_experiment(
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
        experiment_dir=experiment_dir,
    )

    assert state.ideas["IDEA-0001"].status == "completed"


def test_selected_idea_cannot_be_superseded_in_same_merge(tmp_path: Path) -> None:
    paths = ResearchProgramPaths(tmp_path / "program")
    paths.create_directories()
    write_research_state(
        research_state_path(paths),
        ResearchState(
            artifact_kind="research_state",
            schema_version=1,
            experiments={
                "run-0/EXP-0001": {
                    "experiment_dir": str(
                        paths.experiment_directory("run-0", "EXP-0001")
                    ),
                    "outcome": "completed_inconclusive",
                }
            },
            ideas={
                "IDEA-0001": IdeaRecord(
                    dedupe_key="existing",
                    title="Existing idea",
                    kind="direct_followup",
                    evidence_basis=["run-0/EXP-0001"],
                    mechanism="Known mechanism.",
                    axis_to_vary="gate",
                    specific_change="Run existing idea.",
                    falsifying_evidence=["Gate fails."],
                    priority=0.5,
                    priority_reason="Existing frontier.",
                    seed_component_ids=[],
                    source_experiments=["run-0/EXP-0001"],
                )
            },
            learning_updates={},
            known_blockers={},
            reusable_components={},
            metric_observations=[],
        ),
    )
    experiment_dir = paths.experiment_directory("run-1", "EXP-0001")
    _write_minimal_terminal_artifacts(
        experiment_dir,
        selected_plan={
            "selected": True,
            "rationale": "Use existing idea.",
            "selected_idea_ids": ["IDEA-0001"],
            "fresh_selection_reason": None,
            "seed_component_ids": [],
        },
    )
    write_json(
        experiment_dir / "plan_update.json",
        {
            "followups": [],
            "learning_updates": [],
            "blockers": [],
            "reusable_components": [],
            "superseded_idea_ids": ["IDEA-0001"],
        },
    )

    with pytest.raises(ValueError, match="Selected idea cannot be superseded"):
        merge_terminal_experiment(
            paths=paths,
            research_run_id="run-1",
            experiment_id="EXP-0001",
            experiment_dir=experiment_dir,
        )

    persisted = load_research_state(research_state_path(paths))
    assert "run-1/EXP-0001" not in persisted.experiments
    assert persisted.ideas["IDEA-0001"].status == "pending"


def _write_terminal_artifacts(experiment_dir: Path, worktree: Path) -> None:
    _write_minimal_terminal_artifacts(
        experiment_dir,
        selected_plan={
            "selected": True,
            "rationale": "Fresh selected plan.",
            "fresh_selection_reason": "No pending frontier fit.",
            "seed_component_ids": [],
        },
    )
    write_json(
        experiment_dir / "research_spec.json",
        {
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
        },
    )
    write_json(
        experiment_dir / "lineage.json",
        {
            "research_run_id": "run-1",
            "experiment_id": "EXP-0001",
            "experiment_dir": str(experiment_dir),
            "worktree_path": str(worktree),
            "worktree_branch": "research/run-1/EXP-0001",
            "changed_files": ["research/feature.py"],
            "implementation_summary": "Built feature.",
            "reusable_for_followups": True,
        },
    )
    write_json(
        experiment_dir / "confirmatory_evaluation_result.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "metrics": {
                "ic": 0.04,
                "passed": True,
                "bad": float("nan"),
                "huge": float("inf"),
                "nested": {"ir": 1.2},
            },
            "gate_results": {},
            "pre_registered_evidence": [],
        },
    )
    write_json(
        experiment_dir / "plan_update.json",
        {
            **_typed_plan_update_payload(),
            "reusable_components": [
                {
                    "component_key": "component-current",
                    "worktree_path": str(worktree),
                    "changed_files": ["agent/claimed.py"],
                    "summary": "Reusable feature.",
                    "reusable_for": ["liquidity followup"],
                    "risk_notes": [],
                }
            ],
            "superseded_idea_ids": [],
        },
    )


def _write_minimal_terminal_artifacts(
    experiment_dir: Path,
    *,
    selected_plan: dict,
) -> None:
    write_json(
        experiment_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate.",
        },
    )
    write_json(experiment_dir / "selected_plan.json", selected_plan)


def _typed_plan_update_payload() -> dict:
    return {
        "followups": [
            {
                "dedupe_key": "vary-liquidity",
                "title": "Vary liquidity gate",
                "kind": "controlled_variation",
                "evidence_basis": ["run-1/EXP-0001"],
                "mechanism": "Liquidity may condition residual quality.",
                "axis_to_vary": "liquidity",
                "specific_change": "Raise median notional threshold.",
                "falsifying_evidence": ["IC does not improve."],
                "priority": 0.8,
                "priority_reason": "Direct followup.",
                "seed_component_ids": ["component-current"],
            }
        ],
        "learning_updates": [
            {
                "learning_key": "liquidity-matters",
                "evidence_basis": ["run-1/EXP-0001"],
                "claim": "Liquidity affects signal quality.",
                "evidence": ["Candidate passed initial gate."],
                "implication": "Test liquidity gate.",
                "metric_paths": ["ic"],
            }
        ],
        "blockers": [
            {
                "blocker_key": "none",
                "blocker_type": "data",
                "description": "No blocker.",
                "resolution_condition": "No action.",
                "affected_idea_ids": [],
            }
        ],
        "reusable_components": [],
        "superseded_idea_ids": [],
    }
