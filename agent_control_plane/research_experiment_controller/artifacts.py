from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchOutcome(str, Enum):
    no_op = "no_op"
    blocked = "blocked"
    prerequisites_failed = "prerequisites_failed"
    invalid = "invalid"
    run_failed = "run_failed"
    completed_rejected = "completed_rejected"
    completed_inconclusive = "completed_inconclusive"
    completed_candidate = "completed_candidate"


class CommandDeclaration(ResearchArtifact):
    name: str
    argv: list[str] = Field(min_length=1)
    timeout_seconds: float | None = None
    phase: str | None = None


class ContextSummary(ResearchArtifact):
    summary: str
    prior_blockers: list[str] = Field(default_factory=list)
    completed_prerequisites: list[str] = Field(default_factory=list)
    metric_hints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Proposal(ResearchArtifact):
    hypothesis: str
    rationale: str
    signal_family: str
    expected_mechanism: str
    known_risks: list[str] = Field(default_factory=list)
    falsification_evidence: list[str] = Field(default_factory=list)


class ResearchSpec(ResearchArtifact):
    hypothesis: str
    target: str
    prediction_horizon: str
    universe: str
    label: str
    feature_availability_assumptions: list[str]
    split: dict[str, Any]
    primary_metric: str
    secondary_metrics: list[str]
    baselines: list[str]
    null_tests: list[str]
    transaction_cost_assumptions: str
    success_gates: dict[str, Any]
    failure_gates: dict[str, Any]
    inconclusive_gates: dict[str, Any]


class ExperimentDesign(ResearchArtifact):
    prerequisite_commands: list[CommandDeclaration] = Field(default_factory=list)
    data_audit_commands: list[CommandDeclaration] = Field(default_factory=list)
    verification_commands: list[CommandDeclaration] = Field(default_factory=list)
    confirmatory_commands: list[CommandDeclaration] = Field(default_factory=list)
    exploratory_commands: list[CommandDeclaration] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    allowed_write_paths: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    resource_budgets: dict[str, Any] = Field(default_factory=dict)
    failure_routing: dict[str, Any] = Field(default_factory=dict)


class FeatureSpec(ResearchArtifact):
    feature_id: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    transformation_logic: str = Field(min_length=1)
    lookback_window: str = Field(min_length=1)
    lag: str = Field(min_length=1)
    normalization: str = Field(min_length=1)
    missing_data_policy: str = Field(min_length=1)
    backfill_range: str = Field(min_length=1)
    availability_at_decision_time_proof: str = Field(min_length=1)
    expected_failure_modes: list[str] = Field(min_length=1)
    feature_name: str | None = Field(default=None, min_length=1)
    feature_family: str | None = Field(default=None, min_length=1)
    data_source: str | None = Field(default=None, min_length=1)
    transformation: str | None = Field(default=None, min_length=1)
    data_timing: str | None = Field(default=None, min_length=1)
    failure_modes: list[str] = Field(default_factory=list)

    @field_validator(
        "feature_id",
        "transformation_logic",
        "lookback_window",
        "lag",
        "normalization",
        "missing_data_policy",
        "backfill_range",
        "availability_at_decision_time_proof",
        "feature_name",
        "feature_family",
        "data_source",
        "transformation",
        "data_timing",
    )
    @classmethod
    def _non_blank_string(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("inputs", "expected_failure_modes", "failure_modes")
    @classmethod
    def _non_blank_list(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("list must not include blank values")
        return value


class FeatureSpecs(ResearchArtifact):
    features: list[FeatureSpec] = Field(min_length=1)


class SelectedPlan(ResearchArtifact):
    selected: bool
    plan_id: str | None = None
    rationale: str
    material_revision_categories: list[str] = Field(default_factory=list)


class Critique(ResearchArtifact):
    decision: str
    fatal_issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)
    material_revision_categories: list[str] = Field(default_factory=list)
    leakage_risks: list[str] = Field(default_factory=list)
    baseline_concerns: list[str] = Field(default_factory=list)
    gate_concerns: list[str] = Field(default_factory=list)


class DataAudit(ResearchArtifact):
    passed: bool
    outcome: ResearchOutcome | None = None
    outcome_reason: str
    failed_stage: str | None
    failure_classification: str | None
    command_results: list[dict[str, Any]] = Field(default_factory=list)


class Implementation(ResearchArtifact):
    status: str
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    commands_declared: list[CommandDeclaration] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ImplementationRepair(ResearchArtifact):
    repair_attempt: int
    summary: str
    changed_files: list[str] = Field(default_factory=list)


class ImplementationDiffSummary(ResearchArtifact):
    changed_files: list[str]
    allowed_path_violations: list[str] = Field(default_factory=list)
    evaluation_logic_changed: bool = False
    data_handling_changed: bool = False
    high_risk: bool = False
    notes: list[str] = Field(default_factory=list)


class ConfirmatoryEvaluationResult(ResearchArtifact):
    outcome: ResearchOutcome
    outcome_reason: str
    failed_stage: str | None
    failure_classification: str | None
    metrics: dict[str, Any] = Field(default_factory=dict)
    gate_results: dict[str, Any] = Field(default_factory=dict)
    pre_registered_evidence: list[str] = Field(default_factory=list)


class ExploratoryDiagnosticsResult(ResearchArtifact):
    findings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    plots: list[str] = Field(default_factory=list)
    future_experiment_ideas: list[str] = Field(default_factory=list)


class AnalysisLedger(ResearchArtifact):
    entries: list[dict[str, Any]] = Field(default_factory=list)


class EmpiricalCritique(ResearchArtifact):
    status_supported: bool
    concerns: list[str] = Field(default_factory=list)
    overclaiming_risks: list[str] = Field(default_factory=list)
    recommended_outcome: ResearchOutcome


class Summary(ResearchArtifact):
    outcome: ResearchOutcome
    outcome_reason: str
    failed_stage: str | None
    failure_classification: str | None
    summary: str
    confirmatory_findings: list[str] = Field(default_factory=list)
    exploratory_findings: list[str] = Field(default_factory=list)


class PlanUpdate(ResearchArtifact):
    followups: list[str] = Field(default_factory=list)
    revisit_conditions: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
