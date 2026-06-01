from __future__ import annotations

from agent_control_plane.research_experiment_controller.materiality import (
    DEFAULT_MATERIAL_CATEGORIES,
    assess_material_revision,
    requires_fresh_critic,
)
from agent_control_plane.research_experiment_controller.artifacts import ResearchSpec


def test_default_material_fields_require_fresh_critic() -> None:
    before = {
        "target": "return_1m",
        "label": "forward_return_1m",
        "universe": "top_200",
        "data_source": "bars_v1",
        "feature_family": "peer_residual",
        "split": {"train": "2020:2024", "test": "2025"},
        "primary_metric": "ic",
        "success_gates": {"ic": 0.03},
        "baselines": ["market_neutral"],
        "transaction_cost_assumptions": "5 bps",
        "holding_period": "1 month",
        "rebalance_frequency": "weekly",
        "neutralization_policy": "sector neutral",
    }

    for category in DEFAULT_MATERIAL_CATEGORIES:
        after = dict(before)
        key = {
            "success_gate": "success_gates",
            "baseline_set": "baselines",
            "transaction_cost_model": "transaction_cost_assumptions",
        }.get(category, category)
        after[key] = f"changed-{category}"

        decision = assess_material_revision(before, after)

        assert decision.requires_fresh_critic is True
        assert decision.material_categories == [category]
        assert requires_fresh_critic(before, after) is True


def test_agent_declared_materiality_is_conservative() -> None:
    before = {"target": "return_1m", "notes": "old"}
    after = {"target": "return_1m", "notes": "new"}

    assert (
        assess_material_revision(
            before,
            after,
            agent_declared_categories=[""],
        ).requires_fresh_critic
        is False
    )

    decision = assess_material_revision(
        before,
        after,
        agent_declared_categories=["Novel Exposure Bucket"],
    )

    assert decision.requires_fresh_critic is True
    assert decision.material_categories == ["novel_exposure_bucket"]


def test_empty_agent_declarations_do_not_override_controller_material_changes() -> None:
    decision = assess_material_revision(
        {"target": "return_1m"},
        {"target": "return_1w"},
        agent_declared_categories=[""],
    )

    assert decision.requires_fresh_critic is True
    assert decision.material_categories == ["target"]


def test_materiality_accepts_pydantic_artifacts() -> None:
    before = ResearchSpec(
        hypothesis="Peer residuals forecast returns.",
        target="return",
        prediction_horizon="1M",
        universe="top_200",
        label="forward_return_1m",
        feature_availability_assumptions=["lagged daily bars"],
        split={"train": "2020:2024", "test": "2025"},
        primary_metric="ic",
        secondary_metrics=[],
        baselines=["market_neutral"],
        null_tests=[],
        transaction_cost_assumptions="5 bps",
        success_gates={"ic": 0.03},
        failure_gates={"ic": 0.0},
        inconclusive_gates={"min_observations": 100},
    )
    after = before.model_copy(update={"prediction_horizon": "1W"})

    decision = assess_material_revision(before, after)

    assert decision.material_categories == ["holding_period"]


def test_non_material_command_formatting_change_is_ignored() -> None:
    before = {
        "target": "return_1m",
        "success_gates": {"ic": 0.03},
        "commands": [{"name": "eval", "argv": ["python", "eval.py"]}],
    }
    after = {
        "target": "return_1m",
        "success_gates": {"ic": 0.03},
        "commands": [{"name": "eval", "argv": ["python", "./eval.py"]}],
    }

    decision = assess_material_revision(
        before,
        after,
        agent_declared_categories=[],
    )

    assert decision.requires_fresh_critic is False
    assert decision.material_categories == []


def test_material_revision_policy_can_override_material_fields() -> None:
    before = {"target": "return_1m", "notes": "old"}
    after = {"target": "return_1w", "notes": "new"}

    target_ignored = assess_material_revision(
        before,
        after,
        material_fields=["notes"],
    )
    notes_ignored = assess_material_revision(
        before,
        after,
        material_fields=["target"],
    )

    assert target_ignored.material_categories == ["notes"]
    assert requires_fresh_critic(before, after, material_fields=["notes"]) is True
    assert notes_ignored.material_categories == ["target"]

    decision = assess_material_revision(
        {"target": "return_1m"},
        {"target": "return_1w"},
        material_fields=["label"],
    )

    assert decision.requires_fresh_critic is False
    assert decision.material_categories == []
