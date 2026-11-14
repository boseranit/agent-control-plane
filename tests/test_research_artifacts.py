from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_control_plane.research_experiment_controller.artifacts import (
    AnalysisLedger,
    CommandDeclaration,
    ConfirmatoryEvaluationResult,
    ContextSummary,
    Critique,
    DataAudit,
    EmpiricalCritique,
    ExperimentDesign,
    FeatureSpec,
    FeatureSpecs,
    ExploratoryDiagnosticsResult,
    Implementation,
    ImplementationDiffSummary,
    ImplementationRepair,
    Lineage,
    PlanUpdate,
    Proposal,
    ResearchOutcome,
    ResearchSpec,
    SelectedPlan,
    Summary,
)


def test_research_outcome_values_serialize_as_json_strings() -> None:
    assert [item.value for item in ResearchOutcome] == [
        "no_op",
        "blocked",
        "prerequisites_failed",
        "invalid",
        "run_failed",
        "completed_rejected",
        "completed_inconclusive",
        "completed_candidate",
    ]

    result = ConfirmatoryEvaluationResult(
        outcome=ResearchOutcome.completed_candidate,
        outcome_reason="Locked gates passed.",
        failed_stage=None,
        failure_classification=None,
        metrics={"ic": 0.04},
        gate_results={"information_coefficient": "passed"},
        pre_registered_evidence=["confirmatory command eval"],
    )

    assert result.model_dump(mode="json")["outcome"] == "completed_candidate"


def test_core_research_artifacts_validate_canonical_payloads() -> None:
    spec = ResearchSpec(
        hypothesis="Peer residuals forecast next-month returns.",
        target="next_month_return",
        prediction_horizon="1M",
        universe="hyperliquid_perps",
        label="forward_return_1m",
        feature_availability_assumptions=["features lagged one bar"],
        split={"train": "2020-01:2024-12", "test": "2025-01:2026-01"},
        primary_metric="information_coefficient",
        secondary_metrics=["turnover"],
        baselines=["market_neutral_null"],
        null_tests=["symbol_shuffle"],
        transaction_cost_assumptions="5 bps",
        success_gates={"information_coefficient": 0.03},
        failure_gates={"information_coefficient": 0.0},
        inconclusive_gates={"min_observations": 100},
    )
    design = ExperimentDesign(
        prerequisite_commands=[],
        data_audit_commands=[],
        verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
        confirmatory_commands=[{"name": "eval", "argv": ["python", "eval.py"]}],
        exploratory_commands=[],
        expected_outputs=["metrics.json"],
        allowed_write_paths=["research/experiments"],
        timeout_seconds=300,
        resource_budgets={"budget": "smoke"},
        failure_routing={"data": "prerequisites_failed"},
    )
    selected = SelectedPlan(
        selected=True,
        plan_id="plan-1",
        rationale="Best admissible design.",
        fresh_selection_reason="Fresh selected plan.",
        material_revision_categories=[],
        seed_component_ids=[],
    )
    result = ConfirmatoryEvaluationResult(
        outcome=ResearchOutcome.completed_candidate,
        outcome_reason="Locked gates passed.",
        failed_stage=None,
        failure_classification=None,
        metrics={"ic": 0.04},
        gate_results={"information_coefficient": "passed"},
        pre_registered_evidence=["confirmatory command eval"],
    )

    assert spec.success_gates == {"information_coefficient": 0.03}
    assert design.verification_commands[0].argv == ["pytest", "-q"]
    assert selected.selected is True
    assert selected.fresh_selection_reason == "Fresh selected plan."
    assert result.outcome is ResearchOutcome.completed_candidate


def test_research_spec_preserves_json_planning_values() -> None:
    payload = {
        "hypothesis": "Funding dislocations forecast short-horizon reversals.",
        "target": "next_day_return",
        "prediction_horizon": "1D",
        "universe": "hyperliquid_perps",
        "label": "forward_return_1d",
        "feature_availability_assumptions": ["Funding is known before entry."],
        "split": "Train through June; test from July.",
        "primary_metric": "net_information_coefficient",
        "secondary_metrics": ["turnover"],
        "baselines": ["zero_signal"],
        "null_tests": ["timestamp_shuffle"],
        "transaction_cost_assumptions": [
            "Charge 5 bps per side.",
            {"market_impact": None},
        ],
        "success_gates": {"minimum_ic": 0.03, "required": True},
        "failure_gates": "Net information coefficient is at most zero.",
        "inconclusive_gates": ["Fewer than 100 observations remain."],
    }

    assert ResearchSpec.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "field",
    [
        "split",
        "transaction_cost_assumptions",
        "success_gates",
        "failure_gates",
        "inconclusive_gates",
    ],
)
def test_research_spec_rejects_non_json_planning_values(field: str) -> None:
    payload = {
        "hypothesis": "Funding dislocations forecast short-horizon reversals.",
        "target": "next_day_return",
        "prediction_horizon": "1D",
        "universe": "hyperliquid_perps",
        "label": "forward_return_1d",
        "feature_availability_assumptions": [],
        "split": {},
        "primary_metric": "information_coefficient",
        "secondary_metrics": [],
        "baselines": [],
        "null_tests": [],
        "transaction_cost_assumptions": "5 bps",
        "success_gates": {},
        "failure_gates": {},
        "inconclusive_gates": {},
    }
    payload[field] = object()

    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": "success"},
        {"outcome": ResearchOutcome.completed_candidate, "metrics": {}, "extra": True},
    ],
)
def test_invalid_confirmatory_evaluation_results_are_rejected(
    payload: dict[str, object],
) -> None:
    data = {
        "outcome": ResearchOutcome.completed_candidate,
        "outcome_reason": "Locked gates passed.",
        "failed_stage": None,
        "failure_classification": None,
        "metrics": {},
        "gate_results": {},
        "pre_registered_evidence": [],
        **payload,
    }

    with pytest.raises(ValidationError):
        ConfirmatoryEvaluationResult(**data)


def test_invalid_artifact_shapes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CommandDeclaration(name="empty", argv=[])

    with pytest.raises(ValidationError):
        ResearchSpec(
            hypothesis="missing locked target fields",
            target="next_month_return",
            prediction_horizon="1M",
            universe="hyperliquid_perps",
            label="forward_return_1m",
            feature_availability_assumptions=[],
            split={},
            primary_metric="information_coefficient",
            secondary_metrics=[],
            baselines=[],
            null_tests=[],
            transaction_cost_assumptions="5 bps",
            success_gates={},
            failure_gates={},
        )

    with pytest.raises(ValidationError):
        ExperimentDesign(unknown_field=True)


def test_plan_update_schema_excludes_selected_ideas_from_supersession() -> None:
    description = PlanUpdate.model_json_schema()["properties"]["superseded_idea_ids"][
        "description"
    ]

    assert "Pending, unselected idea IDs" in description
    assert "Selected ideas transition from the official outcome" in description


def test_feature_specs_validate_material_signal_contract() -> None:
    feature = FeatureSpec(
        feature_id="peer_residual_21d",
        feature_name="Peer residual 21d",
        feature_family="peer_residual",
        data_source="daily_bars_v1",
        inputs=["returns", "peer_groups"],
        transformation="Regress returns on peer basket and z-score residual.",
        transformation_logic="Regress returns on peer basket and z-score residual.",
        lookback_window="21 trading days",
        data_timing="Uses only data available before prediction timestamp.",
        lag="1 trading day",
        normalization="cross-sectional z-score by timestamp",
        backfill_range="2020-01 through 2026-01",
        missing_data_policy="Drop symbols with fewer than 60 observations.",
        availability_at_decision_time_proof="Uses timestamps <= decision timestamp.",
        failure_modes=[
            "Peer basket composition may include future constituents.",
            "Sparse symbols can create unstable residuals.",
        ],
        expected_failure_modes=[
            "Peer basket composition may include future constituents.",
            "Sparse symbols can create unstable residuals.",
        ],
    )
    bundle = FeatureSpecs(features=[feature])

    assert bundle.model_dump(mode="json")["features"][0]["lag"] == "1 trading day"

    with pytest.raises(ValidationError):
        FeatureSpec(
            feature_id="",
            feature_name="Peer residual 21d",
            feature_family="peer_residual",
            data_source="daily_bars_v1",
            inputs=["returns", "peer_groups"],
            transformation="Regress returns on peer basket.",
            transformation_logic="Regress returns on peer basket.",
            lookback_window="21 trading days",
            data_timing="Point-in-time before label.",
            lag="1 trading day",
            normalization="z-score",
            backfill_range="2020-01 through 2026-01",
            missing_data_policy="Drop missing symbols.",
            availability_at_decision_time_proof="Uses timestamps <= decision time.",
            failure_modes=["future constituents"],
            expected_failure_modes=["future constituents"],
        )

    with pytest.raises(ValidationError):
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
            normalization="z-score",
            backfill_range="2020-01 through 2026-01",
            failure_modes=["future constituents"],
            expected_failure_modes=["future constituents"],
        )

    with pytest.raises(ValidationError):
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
            normalization="z-score",
            backfill_range="2020-01 through 2026-01",
            missing_data_policy="Drop missing symbols.",
            availability_at_decision_time_proof="Uses timestamps <= decision time.",
            failure_modes=["future constituents"],
            expected_failure_modes=["future constituents"],
            extra=True,
        )


def test_feature_spec_records_point_in_time_validity() -> None:
    feature = FeatureSpec(
        feature_id="peer_residual_lookback_30d",
        inputs=["returns", "peer_groups"],
        transformation_logic="Rolling residual against peer basket.",
        lookback_window="30d",
        lag="1 bar",
        normalization="zscore by timestamp",
        missing_data_policy="drop if peer group has fewer than 5 assets",
        backfill_range="2020-01:2026-01",
        availability_at_decision_time_proof="Uses only timestamps <= decision timestamp.",
        expected_failure_modes=["thin peer group", "missing returns"],
    )

    assert feature.feature_id == "peer_residual_lookback_30d"
    assert "decision timestamp" in feature.availability_at_decision_time_proof

    with pytest.raises(ValidationError):
        FeatureSpec(
            feature_id="peer_residual_lookback_30d",
            inputs=[],
            transformation_logic="Rolling residual against peer basket.",
            lookback_window="30d",
            lag="1 bar",
            normalization="zscore by timestamp",
            missing_data_policy="drop if peer group has fewer than 5 assets",
            backfill_range="2020-01:2026-01",
            availability_at_decision_time_proof="Uses timestamps <= decision timestamp.",
            expected_failure_modes=["thin peer group"],
        )

    with pytest.raises(ValidationError):
        FeatureSpec(
            feature_id="peer_residual_lookback_30d",
            inputs=["returns", "peer_groups"],
            transformation_logic="Rolling residual against peer basket.",
            lookback_window="30d",
            lag="1 bar",
            normalization="zscore by timestamp",
            missing_data_policy="drop if peer group has fewer than 5 assets",
            backfill_range="2020-01:2026-01",
            expected_failure_modes=["thin peer group"],
        )


def test_remaining_prd_artifacts_validate_minimum_payloads() -> None:
    context = ContextSummary(
        summary="Prior runs found missing features.",
        prior_blockers=["feature_family_missing"],
        completed_prerequisites=["raw bars backfilled"],
        metric_hints=["IC was unstable"],
        assumptions=["Use smoke budget"],
    )
    proposal = Proposal(
        hypothesis="Cross-sectional residuals persist.",
        rationale="Residual reversal can survive simple baselines.",
        signal_family="peer_residual",
        expected_mechanism="temporary liquidity imbalance",
        known_risks=["leakage"],
        falsification_evidence=["shuffle null passes"],
        experiment_kind="controlled_variation",
        builds_on_experiments=["prior-run/EXP-0003"],
        prior_evidence_used=["ic=0.04"],
        novelty_vs_prior="Adds turnover gate.",
    )
    critique = Critique(
        decision="revise",
        fatal_issues=[],
        required_revisions=["lock split"],
        material_revision_categories=["split"],
        leakage_risks=["future bars"],
        baseline_concerns=[],
        gate_concerns=[],
    )
    data_audit = DataAudit(
        passed=False,
        outcome=ResearchOutcome.prerequisites_failed,
        outcome_reason="Feature family missing.",
        failed_stage="data_audit",
        failure_classification="feature_family_missing",
        command_results=[{"name": "audit", "status": "failed"}],
    )
    implementation = Implementation(
        status="implemented",
        summary="Added feature builder.",
        changed_files=["research/experiments/peer.py"],
        commands_declared=[{"name": "unit", "argv": ["pytest", "-q"]}],
        risks=["slow backfill"],
        inspected_prior_worktrees=["/tmp/worktrees/prior-run/EXP-0003"],
        reused_or_adapted_items=["feature builder"],
        rewritten_items=["evaluation wrapper"],
        reuse_risks=["prior split assumptions"],
    )
    repair = ImplementationRepair(
        repair_attempt=1,
        summary="Fixed import.",
        changed_files=["research/experiments/peer.py"],
    )
    diff = ImplementationDiffSummary(
        changed_files=["research/experiments/peer.py"],
        allowed_path_violations=[],
        evaluation_logic_changed=False,
        data_handling_changed=True,
        high_risk=False,
        notes=["Only allowed paths changed."],
    )
    diagnostics = ExploratoryDiagnosticsResult(
        findings=["Works only in high-volume symbols."],
        metrics={"ic": 0.02},
        plots=["evaluation/eval_outputs/ic.png"],
        future_experiment_ideas=["pre-register liquidity-conditioned gate"],
    )
    analysis_ledger = AnalysisLedger(entries=[{"phase": "evaluation"}])
    empirical = EmpiricalCritique(
        status_supported=True,
        concerns=[],
        overclaiming_risks=["small sample"],
        recommended_outcome=ResearchOutcome.completed_inconclusive,
    )
    summary = Summary(
        outcome=ResearchOutcome.completed_inconclusive,
        outcome_reason="Directionally positive but below gate.",
        failed_stage=None,
        failure_classification=None,
        summary="Experiment was inconclusive.",
        confirmatory_findings=["IC 0.02"],
        exploratory_findings=["Volume conditioning may matter"],
    )
    plan_update = PlanUpdate(
        followups=[
            {
                "dedupe_key": "liquidity-conditioned-residual",
                "title": "Test liquidity-conditioned residual.",
                "kind": "controlled_variation",
                "evidence_basis": ["EXP-0001 IC 0.02"],
                "mechanism": "Liquidity may reduce noisy residuals.",
                "axis_to_vary": "liquidity gate",
                "specific_change": "Require higher median notional volume.",
                "falsifying_evidence": ["IC stays below 0.0 after gate."],
                "priority": 0.8,
                "priority_reason": "Directly tests observed weakness.",
                "seed_component_ids": ["peer-residual-feature"],
            }
        ],
        learning_updates=[
            {
                "learning_key": "residual-needs-liquidity",
                "evidence_basis": ["EXP-0001"],
                "claim": "Residual signal is liquidity sensitive.",
                "evidence": ["IC weakened in illiquid names."],
                "implication": "Condition next run on liquidity.",
                "metric_paths": ["ic"],
            }
        ],
        blockers=[
            {
                "blocker_key": "illiquid-universe",
                "blocker_type": "data_quality",
                "description": "Illiquid universe too noisy.",
                "resolution_condition": "Add liquidity filter.",
                "affected_idea_ids": [],
            }
        ],
        reusable_components=[
            {
                "component_key": "peer-residual-feature",
                "summary": "Reusable peer residual builder.",
                "reusable_for": ["liquidity-conditioned residual"],
                "risk_notes": ["Check data timing."],
            }
        ],
        superseded_idea_ids=[],
    )
    lineage = Lineage(
        research_run_id="peer-residual-v1",
        experiment_id="EXP-0001",
        experiment_dir="/tmp/run/experiments/EXP-0001",
        worktree_path="/tmp/worktrees/peer-residual-v1/EXP-0001",
        worktree_branch="research/peer-residual-v1/EXP-0001",
        target_repo_head_at_start="abc",
        worktree_head_after_implementation="abc",
        changed_files=["research/experiments/peer_residual.py"],
        implementation_summary="Implemented candidate.",
        reusable_for_followups=True,
    )

    assert context.summary.startswith("Prior runs")
    assert proposal.signal_family == "peer_residual"
    assert proposal.experiment_kind == "controlled_variation"
    assert critique.material_revision_categories == ["split"]
    assert data_audit.model_dump(mode="json")["outcome"] == "prerequisites_failed"
    assert implementation.commands_declared[0].argv == ["pytest", "-q"]
    assert repair.repair_attempt == 1
    assert diff.data_handling_changed is True
    assert diagnostics.metrics == {"ic": 0.02}
    assert analysis_ledger.entries == [{"phase": "evaluation"}]
    assert empirical.recommended_outcome is ResearchOutcome.completed_inconclusive
    assert summary.failed_stage is None
    assert plan_update.followups[0].title == "Test liquidity-conditioned residual."
    assert plan_update.reusable_components[0].component_key == "peer-residual-feature"
    assert lineage.reusable_for_followups is True
