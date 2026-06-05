from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    BlockerCard,
    ConfirmatoryEvaluationResult,
    Lineage,
    PlanUpdate,
    ResearchSpec,
    ReusableComponentCard,
    SelectedPlan,
    Summary,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)


COMPLETED_OUTCOMES = {
    "completed_rejected",
    "completed_inconclusive",
    "completed_candidate",
}
BLOCKING_OUTCOMES = {"prerequisites_failed", "blocked", "invalid"}
IDEA_ID_PATTERN = re.compile(r"^IDEA-(\d{4})$")
ResearchOutcomeValue = Literal[
    "no_op",
    "blocked",
    "prerequisites_failed",
    "invalid",
    "run_failed",
    "completed_rejected",
    "completed_inconclusive",
    "completed_candidate",
]


class ResearchStateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IdeaRecord(ResearchStateRecord):
    dedupe_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    evidence_basis: list[str] = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    axis_to_vary: str = Field(min_length=1)
    specific_change: str = Field(min_length=1)
    falsifying_evidence: list[str] = Field(min_length=1)
    priority: float = Field(ge=0.0, le=1.0)
    priority_reason: str = Field(min_length=1)
    seed_component_ids: list[str]
    source_experiments: list[str] = Field(min_length=1)
    status: Literal["pending", "completed", "blocked", "superseded"] = "pending"


class ExperimentRecord(ResearchStateRecord):
    experiment_dir: str = Field(min_length=1)
    outcome: ResearchOutcomeValue
    outcome_reason: str | None = None
    failed_stage: str | None = None
    failure_classification: str | None = None
    hypothesis: str | None = None
    primary_metric: str | None = None
    prediction_horizon: str | None = None
    label: str | None = None
    selected_plan_rationale: str | None = None
    selected_idea_ids: list[str] = Field(default_factory=list)
    fresh_selection_reason: str | None = None
    seed_component_ids: list[str] = Field(default_factory=list)
    worktree_path: str | None = None
    worktree_branch: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    implementation_summary: str | None = None
    lineage_path: str | None = None


class LearningRecord(ResearchStateRecord):
    evidence_basis: list[str] = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    implication: str = Field(min_length=1)
    metric_paths: list[str]
    source_experiments: list[str] = Field(min_length=1)


class BlockerRecord(ResearchStateRecord):
    blocker_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    resolution_condition: str = Field(min_length=1)
    affected_idea_ids: list[str]
    source_experiments: list[str] = Field(min_length=1)


class ReusableComponentRecord(ResearchStateRecord):
    worktree_path: str = Field(min_length=1)
    changed_files: list[str]
    summary: str = Field(min_length=1)
    reusable_for: list[str] = Field(min_length=1)
    risk_notes: list[str]
    source_experiments: list[str] = Field(min_length=1)


class MetricObservation(ResearchStateRecord):
    source_experiment: str = Field(min_length=1)
    metric_path: str = Field(min_length=1)
    value: int | float

    @field_validator("value")
    @classmethod
    def _finite_number(cls, value: int | float) -> int | float:
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("metric observation value must be finite numeric")
        return value


class ResearchState(ResearchStateRecord):
    artifact_kind: Literal["research_state"]
    schema_version: Literal[1]
    program_id: str = Field(min_length=1)
    next_idea_number: int = Field(ge=1)
    idea_index: dict[str, IdeaRecord]
    experiment_index: dict[str, ExperimentRecord]
    learning_updates: dict[str, LearningRecord]
    known_blockers: dict[str, BlockerRecord]
    reusable_components: dict[str, ReusableComponentRecord]
    metric_observations: list[MetricObservation]

    @model_validator(mode="after")
    def _validate_keys(self) -> "ResearchState":
        current_max_idea_number = 0
        for idea_id in self.idea_index:
            match = IDEA_ID_PATTERN.match(idea_id)
            if match is None:
                raise ValueError(f"Invalid idea id: {idea_id}")
            current_max_idea_number = max(
                current_max_idea_number,
                int(match.group(1)),
            )
        if self.next_idea_number <= current_max_idea_number:
            raise ValueError("next_idea_number must exceed existing idea ids")
        for source_experiment in self.experiment_index:
            if "/" not in source_experiment:
                raise ValueError(f"Invalid source experiment id: {source_experiment}")
        for label, records in (
            ("learning_updates", self.learning_updates),
            ("known_blockers", self.known_blockers),
            ("reusable_components", self.reusable_components),
        ):
            for key in records:
                if not key.strip():
                    raise ValueError(f"{label} keys must not be blank")
        for idea_id, idea in self.idea_index.items():
            for source_experiment in idea.source_experiments:
                if source_experiment not in self.experiment_index:
                    raise ValueError(
                        f"Idea {idea_id} source experiment does not exist: "
                        f"{source_experiment}"
                    )
            for component_id in idea.seed_component_ids:
                if component_id not in self.reusable_components:
                    raise ValueError(
                        f"Idea {idea_id} seed component does not exist: {component_id}"
                    )
        for source_experiment, experiment in self.experiment_index.items():
            for idea_id in experiment.selected_idea_ids:
                if idea_id not in self.idea_index:
                    raise ValueError(
                        f"Experiment {source_experiment} selected idea does not exist: "
                        f"{idea_id}"
                    )
            for component_id in experiment.seed_component_ids:
                if component_id not in self.reusable_components:
                    raise ValueError(
                        f"Experiment {source_experiment} seed component does not "
                        f"exist: {component_id}"
                    )
        for blocker_key, blocker in self.known_blockers.items():
            for idea_id in blocker.affected_idea_ids:
                if idea_id not in self.idea_index:
                    raise ValueError(
                        f"Blocker {blocker_key} affected idea does not exist: {idea_id}"
                    )
        for label, records in (
            ("learning update", self.learning_updates),
            ("blocker", self.known_blockers),
            ("reusable component", self.reusable_components),
        ):
            for key, record in records.items():
                for source_experiment in record.source_experiments:
                    if source_experiment not in self.experiment_index:
                        raise ValueError(
                            f"{label} {key} source experiment does not exist: "
                            f"{source_experiment}"
                        )
        for observation in self.metric_observations:
            if observation.source_experiment not in self.experiment_index:
                raise ValueError(
                    "Metric observation source experiment does not exist: "
                    f"{observation.source_experiment}"
                )
        return self


def research_state_path(paths: ResearchProgramPaths) -> Path:
    return paths.memory / "research_state.json"


def ensure_research_state(
    paths: ResearchProgramPaths,
    *,
    program_id: str | None = None,
) -> ResearchState:
    resolved_program_id = program_id if program_id is not None else paths.root.name
    path = research_state_path(paths)
    if not path.exists():
        state = ResearchState(
            artifact_kind="research_state",
            schema_version=1,
            program_id=resolved_program_id,
            next_idea_number=1,
            idea_index={},
            experiment_index={},
            learning_updates={},
            known_blockers={},
            reusable_components={},
            metric_observations=[],
        )
        write_research_state(path, state)
        return state
    state = load_research_state(path)
    if state.program_id != resolved_program_id:
        raise ValueError(
            f"Research state program_id mismatch: {state.program_id} != "
            f"{resolved_program_id}"
        )
    return state


def load_research_state(path: str | Path) -> ResearchState:
    return ResearchState.model_validate(read_json_object(path))


def write_research_state(path: str | Path, state: ResearchState) -> None:
    state = ResearchState.model_validate(state.model_dump(mode="json"))
    write_json(path, state.model_dump(mode="json"))


def merge_terminal_experiment(
    *,
    paths: ResearchProgramPaths,
    research_run_id: str,
    experiment_id: str,
    experiment_dir: str | Path,
) -> ResearchState:
    experiment_path = Path(experiment_dir)
    source_experiment = f"{research_run_id}/{experiment_id}"
    state_path = research_state_path(paths)
    state = load_research_state(state_path)
    if source_experiment in state.experiment_index:
        return state

    summary = Summary.model_validate(read_json_object(experiment_path / "summary.json"))
    completed = summary.outcome.value in COMPLETED_OUTCOMES

    selected_plan_path = experiment_path / "selected_plan.json"
    if completed:
        selected_plan = SelectedPlan.model_validate(
            read_json_object(selected_plan_path)
        )
    elif selected_plan_path.exists():
        selected_plan = SelectedPlan.model_validate(read_json_object(selected_plan_path))
    else:
        selected_plan = None

    research_spec_path = experiment_path / "research_spec.json"
    if completed:
        research_spec = ResearchSpec.model_validate(read_json_object(research_spec_path))
    elif research_spec_path.exists():
        research_spec = ResearchSpec.model_validate(read_json_object(research_spec_path))
    else:
        research_spec = None

    plan_update_path = experiment_path / "plan_update.json"
    if completed:
        plan_update = PlanUpdate.model_validate(read_json_object(plan_update_path))
    elif plan_update_path.exists():
        plan_update = PlanUpdate.model_validate(read_json_object(plan_update_path))
    else:
        plan_update = None

    lineage_path = experiment_path / "lineage.json"
    if completed:
        lineage = Lineage.model_validate(read_json_object(lineage_path))
    elif lineage_path.exists():
        lineage = Lineage.model_validate(read_json_object(lineage_path))
    else:
        lineage = None

    confirmatory_path = experiment_path / "confirmatory_evaluation_result.json"
    if completed:
        confirmatory = ConfirmatoryEvaluationResult.model_validate(
            read_json_object(confirmatory_path)
        )
    elif confirmatory_path.exists():
        confirmatory = ConfirmatoryEvaluationResult.model_validate(
            read_json_object(confirmatory_path)
        )
    else:
        confirmatory = None

    selected_idea_ids = (
        list(selected_plan.selected_idea_ids) if selected_plan is not None else []
    )
    if selected_plan is not None:
        validate_selected_plan_references(state, selected_plan)

    if plan_update is not None:
        _validate_superseded_ideas(
            state,
            plan_update.superseded_idea_ids,
            selected_idea_ids=selected_idea_ids,
        )
        _merge_reusable_components(
            state,
            plan_update.reusable_components,
            source_experiment=source_experiment,
            lineage=lineage,
        )
    if plan_update is not None:
        _validate_followup_seed_components(state, plan_update)

    experiment_record = ExperimentRecord(
        experiment_dir=str(experiment_path),
        outcome=summary.outcome.value,
        outcome_reason=summary.outcome_reason,
        failed_stage=summary.failed_stage,
        failure_classification=summary.failure_classification,
        hypothesis=research_spec.hypothesis if research_spec is not None else None,
        primary_metric=research_spec.primary_metric
        if research_spec is not None
        else None,
        prediction_horizon=(
            research_spec.prediction_horizon if research_spec is not None else None
        ),
        label=research_spec.label if research_spec is not None else None,
        selected_plan_rationale=(
            selected_plan.rationale if selected_plan is not None else None
        ),
        selected_idea_ids=selected_idea_ids,
        fresh_selection_reason=(
            selected_plan.fresh_selection_reason if selected_plan is not None else None
        ),
        seed_component_ids=(
            list(selected_plan.seed_component_ids) if selected_plan is not None else []
        ),
        worktree_path=lineage.worktree_path if lineage is not None else None,
        worktree_branch=lineage.worktree_branch if lineage is not None else None,
        changed_files=list(lineage.changed_files) if lineage is not None else [],
        implementation_summary=(
            lineage.implementation_summary if lineage is not None else None
        ),
        lineage_path=str(lineage_path) if lineage is not None else None,
    )
    state.experiment_index[source_experiment] = experiment_record

    _apply_selected_idea_outcome(
        state,
        selected_idea_ids=selected_idea_ids,
        source_experiment=source_experiment,
        summary=summary,
    )
    if plan_update is not None:
        _merge_plan_update(
            state,
            plan_update,
            source_experiment=source_experiment,
        )
    if confirmatory is not None:
        state.metric_observations.extend(
            MetricObservation(
                source_experiment=source_experiment,
                metric_path=metric_path,
                value=value,
            )
            for metric_path, value in _numeric_metric_leaves(confirmatory.metrics)
        )

    write_research_state(state_path, state)
    return state


def next_idea_id(state: ResearchState) -> str:
    idea_id = f"IDEA-{state.next_idea_number:04d}"
    state.next_idea_number += 1
    return idea_id


def validate_selected_plan_references(
    state: ResearchState,
    selected_plan: SelectedPlan,
) -> None:
    for idea_id in selected_plan.selected_idea_ids:
        idea = state.idea_index.get(idea_id)
        if idea is None:
            raise ValueError(f"Selected idea does not exist: {idea_id}")
        if idea.status != "pending":
            raise ValueError(f"Selected idea is not pending: {idea_id}")
    for component_id in selected_plan.seed_component_ids:
        if component_id not in state.reusable_components:
            raise ValueError(f"Seed component does not exist: {component_id}")


def _validate_superseded_ideas(
    state: ResearchState,
    superseded_idea_ids: list[str],
    *,
    selected_idea_ids: list[str],
) -> None:
    selected_idea_id_set = set(selected_idea_ids)
    for idea_id in superseded_idea_ids:
        if idea_id in selected_idea_id_set:
            raise ValueError(f"Selected idea cannot be superseded: {idea_id}")
        idea = state.idea_index.get(idea_id)
        if idea is None:
            raise ValueError(f"Superseded idea does not exist: {idea_id}")
        if idea.status != "pending":
            raise ValueError(f"Superseded idea is not pending: {idea_id}")


def _merge_reusable_components(
    state: ResearchState,
    cards: list[ReusableComponentCard],
    *,
    source_experiment: str,
    lineage: Lineage | None,
) -> None:
    if not cards:
        return
    if lineage is None or lineage.worktree_path is None or not lineage.changed_files:
        raise ValueError("Reusable components require lineage worktree and changed files.")
    for card in cards:
        existing = state.reusable_components.get(card.component_key)
        if existing is not None:
            _validate_reusable_component_match(
                existing,
                worktree_path=lineage.worktree_path,
                changed_files=lineage.changed_files,
                summary=card.summary,
                reusable_for=card.reusable_for,
                risk_notes=card.risk_notes,
            )
            _append_unique(existing.source_experiments, source_experiment)
            continue
        state.reusable_components[card.component_key] = ReusableComponentRecord(
            worktree_path=lineage.worktree_path,
            changed_files=list(lineage.changed_files),
            summary=card.summary,
            reusable_for=list(card.reusable_for),
            risk_notes=list(card.risk_notes),
            source_experiments=[source_experiment],
        )


def _validate_reusable_component_match(
    existing: ReusableComponentRecord,
    *,
    worktree_path: str,
    changed_files: list[str],
    summary: str,
    reusable_for: list[str],
    risk_notes: list[str],
) -> None:
    if (
        existing.worktree_path != worktree_path
        or existing.changed_files != changed_files
        or existing.summary != summary
        or existing.reusable_for != reusable_for
        or existing.risk_notes != risk_notes
    ):
        raise ValueError("Reusable component key conflicts with existing component.")


def _validate_followup_seed_components(
    state: ResearchState,
    plan_update: PlanUpdate,
) -> None:
    for followup in plan_update.followups:
        for component_id in followup.seed_component_ids:
            if component_id not in state.reusable_components:
                raise ValueError(
                    f"Followup seed component does not exist: {component_id}"
                )


def _apply_selected_idea_outcome(
    state: ResearchState,
    *,
    selected_idea_ids: list[str],
    source_experiment: str,
    summary: Summary,
) -> None:
    if summary.outcome.value in COMPLETED_OUTCOMES:
        for idea_id in selected_idea_ids:
            state.idea_index[idea_id].status = "completed"
        return
    if summary.outcome.value in BLOCKING_OUTCOMES:
        for idea_id in selected_idea_ids:
            state.idea_index[idea_id].status = "blocked"
        return
    if summary.outcome.value == "run_failed":
        blocker_key = (
            f"operational:{source_experiment}:"
            f"{summary.failure_classification or summary.failed_stage or 'run_failed'}"
        )
        _merge_blocker_record(
            state,
            blocker_key=blocker_key,
            blocker_type="operational",
            description=summary.outcome_reason,
            resolution_condition="Resolve operational failure before retry.",
            affected_idea_ids=selected_idea_ids,
            source_experiment=source_experiment,
        )


def _merge_plan_update(
    state: ResearchState,
    plan_update: PlanUpdate,
    *,
    source_experiment: str,
) -> None:
    for idea_id in plan_update.superseded_idea_ids:
        state.idea_index[idea_id].status = "superseded"

    for followup in plan_update.followups:
        existing_id = _idea_id_for_dedupe_key(state, followup.dedupe_key)
        if existing_id is not None:
            _append_unique(
                state.idea_index[existing_id].source_experiments, source_experiment
            )
            continue
        state.idea_index[next_idea_id(state)] = IdeaRecord(
            dedupe_key=followup.dedupe_key,
            title=followup.title,
            kind=followup.kind,
            evidence_basis=list(followup.evidence_basis),
            mechanism=followup.mechanism,
            axis_to_vary=followup.axis_to_vary,
            specific_change=followup.specific_change,
            falsifying_evidence=list(followup.falsifying_evidence),
            priority=followup.priority,
            priority_reason=followup.priority_reason,
            seed_component_ids=list(followup.seed_component_ids),
            source_experiments=[source_experiment],
        )

    for update in plan_update.learning_updates:
        existing = state.learning_updates.get(update.learning_key)
        if existing is not None:
            _append_unique(existing.source_experiments, source_experiment)
            continue
        state.learning_updates[update.learning_key] = LearningRecord(
            evidence_basis=list(update.evidence_basis),
            claim=update.claim,
            evidence=list(update.evidence),
            implication=update.implication,
            metric_paths=list(update.metric_paths),
            source_experiments=[source_experiment],
        )

    for blocker in plan_update.blockers:
        _validate_blocker_idea_references(state, blocker)
        _merge_blocker_record(
            state,
            blocker_key=blocker.blocker_key,
            blocker_type=blocker.blocker_type,
            description=blocker.description,
            resolution_condition=blocker.resolution_condition,
            affected_idea_ids=list(blocker.affected_idea_ids),
            source_experiment=source_experiment,
        )


def _validate_blocker_idea_references(
    state: ResearchState,
    blocker: BlockerCard,
) -> None:
    for idea_id in blocker.affected_idea_ids:
        if idea_id not in state.idea_index:
            raise ValueError(f"Blocker affected idea does not exist: {idea_id}")


def _merge_blocker_record(
    state: ResearchState,
    *,
    blocker_key: str,
    blocker_type: str,
    description: str,
    resolution_condition: str,
    affected_idea_ids: list[str],
    source_experiment: str,
) -> None:
    existing = state.known_blockers.get(blocker_key)
    if existing is not None:
        _append_unique(existing.source_experiments, source_experiment)
        return
    state.known_blockers[blocker_key] = BlockerRecord(
        blocker_type=blocker_type,
        description=description,
        resolution_condition=resolution_condition,
        affected_idea_ids=affected_idea_ids,
        source_experiments=[source_experiment],
    )


def _idea_id_for_dedupe_key(
    state: ResearchState,
    dedupe_key: str,
) -> str | None:
    for idea_id, idea in state.idea_index.items():
        if idea.dedupe_key == dedupe_key:
            return idea_id
    return None


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _numeric_metric_leaves(
    data: Any, prefix: str = ""
) -> list[tuple[str, int | float]]:
    if isinstance(data, dict):
        leaves: list[tuple[str, int | float]] = []
        for key in sorted(data):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.extend(_numeric_metric_leaves(data[key], child_prefix))
        return leaves
    if isinstance(data, list):
        leaves = []
        for index, item in enumerate(data):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            leaves.extend(_numeric_metric_leaves(item, child_prefix))
        return leaves
    if isinstance(data, bool):
        return []
    if isinstance(data, int | float) and math.isfinite(data):
        return [(prefix, data)]
    return []
