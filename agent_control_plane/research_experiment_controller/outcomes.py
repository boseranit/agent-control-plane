from __future__ import annotations

from agent_control_plane.research_experiment_controller.artifacts import (
    ResearchOutcome,
    Summary,
)

COMPLETED_OUTCOMES = frozenset(
    {
        ResearchOutcome.completed_rejected,
        ResearchOutcome.completed_inconclusive,
        ResearchOutcome.completed_candidate,
    }
)

DATA_AUDIT_FAILURE_CLASSIFICATIONS = frozenset(
    {
        "data_root_missing",
        "feature_family_missing",
        "schema_mismatch",
        "artifact_missing",
        "point_in_time_invalid",
        "prerequisite_command_failed",
    }
)


def classify_data_audit_failure(failure_classification: str) -> Summary:
    if failure_classification not in DATA_AUDIT_FAILURE_CLASSIFICATIONS:
        raise ValueError(
            f"Unknown data-audit failure classification: {failure_classification}"
        )
    reason = f"Data/prerequisite audit failed: {failure_classification}."
    return Summary(
        outcome=ResearchOutcome.prerequisites_failed,
        outcome_reason=reason,
        failed_stage="data_audit",
        failure_classification=failure_classification,
        summary=reason,
    )


def classify_no_op(reason: str) -> Summary:
    return Summary(
        outcome=ResearchOutcome.no_op,
        outcome_reason=reason,
        failed_stage=None,
        failure_classification=None,
        summary=reason,
    )


def classify_blocked(
    failure_classification: str,
    reason: str,
    *,
    failed_stage: str = "controller",
) -> Summary:
    return Summary(
        outcome=ResearchOutcome.blocked,
        outcome_reason=reason,
        failed_stage=failed_stage,
        failure_classification=failure_classification,
        summary=reason,
    )


def classify_invalid(
    reason: str,
    *,
    failure_classification: str = "invalid_design",
    failed_stage: str = "selection",
) -> Summary:
    return Summary(
        outcome=ResearchOutcome.invalid,
        outcome_reason=reason,
        failed_stage=failed_stage,
        failure_classification=failure_classification,
        summary=reason,
    )


def classify_run_failed(
    reason: str,
    *,
    failure_classification: str = "run_failed",
    failed_stage: str = "controller",
) -> Summary:
    return Summary(
        outcome=ResearchOutcome.run_failed,
        outcome_reason=reason,
        failed_stage=failed_stage,
        failure_classification=failure_classification,
        summary=reason,
    )


def classify_completed(outcome: ResearchOutcome, reason: str) -> Summary:
    if outcome not in COMPLETED_OUTCOMES:
        raise ValueError(f"Outcome is not terminal completed: {outcome.value}")
    return Summary(
        outcome=outcome,
        outcome_reason=reason,
        failed_stage=None,
        failure_classification=None,
        summary=reason,
    )


def classify_selected_without_commands() -> Summary:
    return classify_blocked(
        "no_deterministic_commands",
        "A selected plan declared no deterministic verification or confirmatory commands.",
        failed_stage="selection",
    )


def should_stop_research_run(
    *,
    outcome: str,
    stop_on_prerequisites_failed: bool,
) -> bool:
    return bool(
        stop_on_prerequisites_failed
        and outcome == ResearchOutcome.prerequisites_failed.value
    )
