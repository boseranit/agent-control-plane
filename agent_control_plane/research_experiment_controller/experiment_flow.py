from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_control_plane.control_plane.boundary_audit import git_snapshot
from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.control_plane.usage_limit import (
    UsageLimitEvent,
    UsageLimitWait,
    run_with_usage_limit_retry,
)
from agent_control_plane.research_experiment_controller.agents import (
    ResearchAgentRole,
    agent_config,
    open_critic_thread,
    open_evaluator_thread,
    open_implementer_thread,
    open_strategist_thread,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    AnalysisLedger,
    ConfirmatoryEvaluationResult,
    Critique,
    ExperimentDesign,
    EmpiricalCritique,
    FeatureSpecs,
    Implementation,
    ImplementationDiffSummary,
    ExploratoryDiagnosticsResult,
    PlanUpdate,
    Proposal,
    ResearchOutcome,
    ResearchSpec,
    SelectedPlan,
    Summary,
    command_declaration_records,
)
from agent_control_plane.research_experiment_controller.context import (
    write_context_outputs,
)
from agent_control_plane.research_experiment_controller.evaluation import (
    EvaluationBoundaryError,
    create_evaluator_workspace,
    run_evaluation_boundary_audit,
)
from agent_control_plane.research_experiment_controller.implementation_boundary import (
    audit_implementation_paths,
)
from agent_control_plane.research_experiment_controller.outcomes import (
    COMPLETED_OUTCOMES,
    classify_invalid,
    classify_no_op,
    classify_run_failed,
    classify_selected_without_commands,
)
from agent_control_plane.research_experiment_controller.ledger import (
    append_ledger_event,
)
from agent_control_plane.research_experiment_controller.materiality import (
    MaterialRevisionDecision,
    assess_material_revision,
)
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
    run_data_audit_phase,
)
from agent_control_plane.research_experiment_controller.research_run_mirror import (
    ResearchRunMirrorRequest,
    mirror_research_run,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    ResearchRunSpec,
)
from agent_control_plane.research_experiment_controller.verification import (
    VerificationRepairRequest,
    run_verification_commands,
)
from agent_control_plane.research_experiment_controller.worktree import (
    ExperimentWorktree,
    prepare_experiment_worktree,
)


@dataclass(frozen=True)
class ExperimentFlowRequest:
    research_run_id: str
    experiment_id: str
    run_directory: Path
    experiment_directory: Path
    ledger_path: Path
    spec: ResearchRunSpec
    state: dict[str, Any]


@dataclass(frozen=True)
class ExperimentFlowSelection:
    selected_plan: SelectedPlan
    experiment_design: ExperimentDesign | None
    terminal_summary: Summary | None = None
    prior_research_spec: Any | None = None
    research_spec: Any | None = None
    prior_feature_specs: FeatureSpecs | None = None
    feature_specs: FeatureSpecs | None = None


@dataclass(frozen=True)
class _ExperimentPipeline:
    selection: ExperimentFlowSelection
    run_design_critique: bool = False
    run_implementation: bool = False
    run_empirical_closeout: bool = False


class ExperimentFlowError(RuntimeError):
    """Raised when one bounded Research Experiment cannot finish."""


def run_experiment_flow(
    request: ExperimentFlowRequest,
    *,
    selection: ExperimentFlowSelection | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    experiment_dir = Path(request.experiment_directory)
    experiment_dir.mkdir(parents=True, exist_ok=True)
    pipeline = _resolve_experiment_pipeline(
        request=request,
        selection=selection,
        agent_runtime=agent_runtime,
    )
    return _run_selected_experiment_pipeline(
        request=request,
        pipeline=pipeline,
        agent_runtime=agent_runtime,
    )


def _resolve_experiment_pipeline(
    *,
    request: ExperimentFlowRequest,
    selection: ExperimentFlowSelection | None,
    agent_runtime: Any | None,
) -> _ExperimentPipeline:
    if selection is not None:
        return _ExperimentPipeline(selection=selection)
    if agent_runtime is None:
        return _ExperimentPipeline(selection=_default_no_op_selection())
    return _select_agent_driven_experiment(request, agent_runtime)


def _select_agent_driven_experiment(
    request: ExperimentFlowRequest,
    agent_runtime: Any,
) -> _ExperimentPipeline:
    write_context_outputs(
        request.run_directory,
        output_directory=request.experiment_directory,
        current_experiment_id=request.experiment_id,
    )

    strategist = open_strategist_thread(
        agent_runtime,
        request.state,
        request.experiment_directory,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    proposal = _run_agent_model(
        thread=strategist,
        role=ResearchAgentRole.STRATEGIST,
        cwd=request.experiment_directory,
        request=request,
        model_cls=Proposal,
        turn_input=(
            "Read context_pack.md and return proposal.json for the next bounded "
            f"Research Experiment {request.experiment_id}."
        ),
    )
    _write_model_artifact(request.experiment_directory / "proposal.json", proposal)
    research_spec = _run_agent_model(
        thread=strategist,
        role=ResearchAgentRole.STRATEGIST,
        cwd=request.experiment_directory,
        request=request,
        model_cls=ResearchSpec,
        turn_input="Return locked research_spec.json for the selected proposal.",
    )
    experiment_design = _run_agent_model(
        thread=strategist,
        role=ResearchAgentRole.STRATEGIST,
        cwd=request.experiment_directory,
        request=request,
        model_cls=ExperimentDesign,
        turn_input="Return experiment_design.json with deterministic commands.",
    )
    selected_plan = _run_agent_model(
        thread=strategist,
        role=ResearchAgentRole.STRATEGIST,
        cwd=request.experiment_directory,
        request=request,
        model_cls=SelectedPlan,
        turn_input="Return selected_plan.json for exactly one admissible plan.",
    )
    return _ExperimentPipeline(
        selection=ExperimentFlowSelection(
            selected_plan=selected_plan,
            experiment_design=experiment_design,
            research_spec=research_spec,
        ),
        run_design_critique=True,
        run_implementation=True,
        run_empirical_closeout=True,
    )


def _run_selected_experiment_pipeline(
    *,
    request: ExperimentFlowRequest,
    pipeline: _ExperimentPipeline,
    agent_runtime: Any | None,
) -> dict[str, Any]:
    selection = pipeline.selection
    experiment_dir = Path(request.experiment_directory)
    _write_artifact_once(
        experiment_dir / "selected_plan.json",
        request.experiment_id,
        selection.selected_plan.model_dump(mode="json"),
    )
    experiment_design = selection.experiment_design
    if experiment_design is not None:
        _write_artifact_once(
            experiment_dir / "experiment_design.json",
            request.experiment_id,
            experiment_design.model_dump(mode="json"),
        )
    if selection.research_spec is not None:
        _write_artifact_once(
            experiment_dir / "research_spec.json",
            request.experiment_id,
            ResearchSpec.model_validate(selection.research_spec).model_dump(
                mode="json"
            ),
        )
    if selection.feature_specs is not None:
        _write_artifact_once(
            experiment_dir / "feature_specs.json",
            request.experiment_id,
            selection.feature_specs.model_dump(mode="json"),
        )

    summary_model = _selection_failure_summary(selection)
    if summary_model is None:
        summary_model = _run_material_revision_review_if_needed(
            request=request,
            selection=selection,
            agent_runtime=agent_runtime,
        )

    if summary_model is None and pipeline.run_design_critique:
        if agent_runtime is None:
            summary_model = classify_invalid(
                "Design critique requires an agent runtime.",
                failed_stage="critic_review",
                failure_classification="critic_runtime_missing",
            )
        else:
            critique = _run_design_critique(
                request=request,
                agent_runtime=agent_runtime,
            )
            if _critic_blocks_experiment(critique):
                summary_model = classify_invalid(
                    "Critic rejected selected design.",
                    failed_stage="critic_review",
                    failure_classification="critic_rejected_design",
                )

    if summary_model is None:
        assert experiment_design is not None
        summary_model = _worktree_policy_failure(request.spec, experiment_design)

    if summary_model is None:
        assert experiment_design is not None
        data_audit_result = run_data_audit_phase(
            PrerequisiteAuditRequest(
                data_root=request.spec.data_root,
                prerequisite_commands=experiment_design.prerequisite_commands,
                data_audit_commands=experiment_design.data_audit_commands,
                cwd=request.spec.target_repository,
                run_dir=experiment_dir,
                timeout_seconds=_data_audit_timeout_seconds(
                    request.spec, experiment_design
                ),
            )
        )
        _write_artifact_once(
            experiment_dir / "data_audit.json",
            request.experiment_id,
            data_audit_result["data_audit"],
        )
        if data_audit_result.get("status") == "experiment_completed":
            summary_model = _summary_from_result(data_audit_result)
        else:
            worktree = _prepare_experiment_worktree_if_needed(
                request.spec, request, experiment_design
            )
            implementation_summary = (
                _run_implementation_phase(
                    request=request,
                    experiment_design=experiment_design,
                    worktree=worktree,
                    agent_runtime=agent_runtime,
                )
                if pipeline.run_implementation
                else _write_skipped_implementation_if_needed(request, worktree)
            )
            if implementation_summary is not None:
                summary_model = implementation_summary
            else:
                verification_result = _run_verification_if_needed(
                    request=request,
                    experiment_design=experiment_design,
                    worktree=worktree,
                    agent_runtime=agent_runtime,
                )
                boundary_summary = _audit_implementation_boundary(
                    request=request,
                    experiment_design=experiment_design,
                    worktree=worktree,
                    replace_existing=(
                        request.experiment_directory
                        / "implementation_diff_summary.json"
                    ).exists(),
                )
                if boundary_summary is not None:
                    summary_model = boundary_summary
                elif (
                    verification_result is not None
                    and verification_result["status"] == "failed"
                ):
                    summary_model = _summary_from_result(verification_result)
            if summary_model is None:
                summary_model = _run_evaluation_if_needed(
                    request=request,
                    experiment_design=experiment_design,
                    worktree=worktree,
                    agent_runtime=agent_runtime,
                )
            if summary_model is None:
                if pipeline.run_empirical_closeout:
                    summary_model = classify_invalid(
                        "Agent-driven selected plan did not produce evaluation results.",
                        failure_classification="missing_evaluation_result",
                        failed_stage="evaluation",
                    )
                else:
                    summary_model = _terminal_summary_after_data_audit(selection)

    if pipeline.run_empirical_closeout and summary_model.outcome in COMPLETED_OUTCOMES:
        assert agent_runtime is not None
        _run_empirical_critique(
            request=request,
            agent_runtime=agent_runtime,
        )
        summary_model = _run_strategist_closeout(
            request=request,
            agent_runtime=agent_runtime,
            official_summary=summary_model,
        )

    return _complete_with_summary(request, summary_model)


def _complete_with_summary(
    request: ExperimentFlowRequest,
    summary_model: Summary,
) -> dict[str, Any]:
    summary = summary_model.model_dump(mode="json")
    _write_artifact_once(
        request.experiment_directory / "summary.json",
        request.experiment_id,
        summary,
    )
    _mirror_experiment_if_enabled(request, summary_model)
    return {
        "status": "experiment_completed",
        "experiment_id": request.experiment_id,
        **summary,
    }


def _run_design_critique(
    *,
    request: ExperimentFlowRequest,
    agent_runtime: Any,
) -> Critique:
    thread = open_critic_thread(
        agent_runtime,
        request.state,
        request.experiment_directory,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    append_ledger_event(
        request.ledger_path,
        event_type="design_critique",
        research_run_id=request.research_run_id,
        experiment_id=request.experiment_id,
        critic_thread_id=thread.id,
    )
    critique = _run_agent_model(
        thread=thread,
        role=ResearchAgentRole.CRITIC,
        cwd=request.experiment_directory,
        request=request,
        model_cls=Critique,
        turn_input=(
            "Review proposal.json, research_spec.json, experiment_design.json, "
            "and selected_plan.json. Return critique.json."
        ),
    )
    _write_model_artifact(request.experiment_directory / "critique.json", critique)
    return critique


def _run_implementation_phase(
    *,
    request: ExperimentFlowRequest,
    experiment_design: ExperimentDesign,
    worktree: ExperimentWorktree | None,
    agent_runtime: Any | None,
) -> Summary | None:
    if agent_runtime is None:
        return classify_invalid(
            "Implementation requires an agent runtime.",
            failed_stage="implementation",
            failure_classification="implementation_runtime_missing",
        )
    if worktree is None:
        _write_model_artifact(
            request.experiment_directory / "implementation.json",
            Implementation(
                status="skipped",
                summary="No Experiment Worktree required.",
                changed_files=[],
            ),
        )
        _write_model_artifact(
            request.experiment_directory / "implementation_diff_summary.json",
            ImplementationDiffSummary(changed_files=[]),
        )
        return None

    thread = open_implementer_thread(
        agent_runtime,
        request.state,
        worktree.path,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    append_ledger_event(
        request.ledger_path,
        event_type="implementation_attempt",
        research_run_id=request.research_run_id,
        experiment_id=request.experiment_id,
        implementer_thread_id=thread.id,
        worktree=str(worktree.path),
    )
    implementation = _run_agent_model(
        thread=thread,
        role=ResearchAgentRole.IMPLEMENTER,
        cwd=worktree.path,
        request=request,
        model_cls=Implementation,
        turn_input=(
            "Implement the selected plan in the Experiment Worktree. "
            "Return implementation.json."
        ),
    )
    _write_model_artifact(
        request.experiment_directory / "implementation.json",
        implementation,
    )
    return _audit_implementation_boundary(
        request=request,
        experiment_design=experiment_design,
        worktree=worktree,
        replace_existing=False,
    )


def _write_skipped_implementation_if_needed(
    request: ExperimentFlowRequest,
    worktree: ExperimentWorktree | None,
) -> Summary | None:
    implementation_path = request.experiment_directory / "implementation.json"
    if not implementation_path.exists():
        _write_model_artifact(
            implementation_path,
            Implementation(
                status="skipped",
                summary="No Implementer Agent run for supplied selection.",
                changed_files=[],
            ),
        )
    if worktree is None:
        diff_path = request.experiment_directory / "implementation_diff_summary.json"
        if not diff_path.exists():
            _write_model_artifact(
                diff_path, ImplementationDiffSummary(changed_files=[])
            )
    return None


def _audit_implementation_boundary(
    *,
    request: ExperimentFlowRequest,
    experiment_design: ExperimentDesign,
    worktree: ExperimentWorktree | None,
    replace_existing: bool,
) -> Summary | None:
    if worktree is None:
        if not replace_existing:
            _write_model_artifact(
                request.experiment_directory / "implementation_diff_summary.json",
                ImplementationDiffSummary(changed_files=[]),
            )
        return None
    changed_files = sorted(git_snapshot(worktree.path).changed_files)
    audit = audit_implementation_paths(
        changed_files=changed_files,
        allowed_write_paths=experiment_design.allowed_write_paths,
    )
    path = request.experiment_directory / "implementation_diff_summary.json"
    if replace_existing:
        write_json(path, audit.diff_summary.model_dump(mode="json"))
    else:
        _write_model_artifact(path, audit.diff_summary)
    return audit.failure_summary


def _run_empirical_critique(
    *,
    request: ExperimentFlowRequest,
    agent_runtime: Any,
) -> EmpiricalCritique:
    thread = open_critic_thread(
        agent_runtime,
        request.state,
        request.experiment_directory,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    append_ledger_event(
        request.ledger_path,
        event_type="empirical_critique",
        research_run_id=request.research_run_id,
        experiment_id=request.experiment_id,
        critic_thread_id=thread.id,
    )
    critique = _run_agent_model(
        thread=thread,
        role=ResearchAgentRole.CRITIC,
        cwd=request.experiment_directory,
        request=request,
        model_cls=EmpiricalCritique,
        turn_input=(
            "Review confirmatory_evaluation_result.json and "
            "exploratory_diagnostics_result.json. Return empirical_critique.json."
        ),
    )
    _write_model_artifact(
        request.experiment_directory / "empirical_critique.json",
        critique,
    )
    return critique


def _run_strategist_closeout(
    *,
    request: ExperimentFlowRequest,
    agent_runtime: Any,
    official_summary: Summary,
) -> Summary:
    thread = open_strategist_thread(
        agent_runtime,
        request.state,
        request.experiment_directory,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    try:
        summary = _run_agent_model(
            thread=thread,
            role=ResearchAgentRole.STRATEGIST,
            cwd=request.experiment_directory,
            request=request,
            model_cls=Summary,
            turn_input=(
                "Use empirical_critique.json and evaluation artifacts. "
                "Return summary.json."
            ),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        summary = official_summary
    plan_update = _run_agent_model(
        thread=thread,
        role=ResearchAgentRole.STRATEGIST,
        cwd=request.experiment_directory,
        request=request,
        model_cls=PlanUpdate,
        turn_input="Return plan_update.json for future Research Experiments.",
    )
    _write_model_artifact(
        request.experiment_directory / "plan_update.json",
        plan_update,
    )
    return _preserve_official_outcome(official_summary, summary)


def _preserve_official_outcome(
    official_summary: Summary,
    closeout_summary: Summary,
) -> Summary:
    return Summary(
        outcome=official_summary.outcome,
        outcome_reason=official_summary.outcome_reason,
        failed_stage=official_summary.failed_stage,
        failure_classification=official_summary.failure_classification,
        summary=closeout_summary.summary,
        confirmatory_findings=official_summary.confirmatory_findings,
        exploratory_findings=official_summary.exploratory_findings,
    )


def _run_agent_model(
    *,
    thread: Any,
    role: ResearchAgentRole,
    cwd: str | Path,
    request: ExperimentFlowRequest,
    model_cls: Any,
    turn_input: str,
) -> Any:
    turn_result = _run_agent_turn_with_usage_limit(
        role=role,
        run=lambda: thread.run(
            turn_input,
            agent_config(
                role,
                cwd,
                model=request.spec.codex.model,
                effort=request.spec.codex.effort,
                output_schema=model_cls.model_json_schema(),
            ),
        ),
    )
    final_response = getattr(turn_result, "final_response", None)
    if isinstance(final_response, model_cls):
        return final_response
    return model_cls.model_validate(_response_mapping(final_response))


def _write_model_artifact(path: Path, model: Any) -> None:
    if path.exists():
        raise ExperimentFlowError(f"Research Experiment already has {path.name}.")
    write_json(path, model.model_dump(mode="json"))


def _run_material_revision_review_if_needed(
    *,
    request: ExperimentFlowRequest,
    selection: ExperimentFlowSelection,
    agent_runtime: Any | None,
) -> Summary | None:
    decision = _material_revision_decision(selection)
    if not decision.requires_fresh_critic:
        return None
    if agent_runtime is None:
        return classify_invalid(
            "Material revision requires Critic review but no agent runtime is available.",
            failed_stage="critic_review",
            failure_classification="material_revision_unreviewed",
        )

    critic_cwd = request.experiment_directory
    thread = open_critic_thread(
        agent_runtime,
        request.state,
        critic_cwd,
        model=request.spec.codex.model,
        effort=request.spec.codex.effort,
    )
    append_ledger_event(
        request.ledger_path,
        event_type="material_revision_critic_review",
        research_run_id=request.research_run_id,
        experiment_id=request.experiment_id,
        critic_thread_id=thread.id,
        material_revision_categories=decision.material_categories,
    )
    turn_result = _run_agent_turn_with_usage_limit(
        role=ResearchAgentRole.CRITIC,
        run=lambda: thread.run(
            _material_revision_critic_input(request, decision),
            agent_config(
                ResearchAgentRole.CRITIC,
                critic_cwd,
                model=request.spec.codex.model,
                effort=request.spec.codex.effort,
            ),
        ),
    )
    critique = Critique.model_validate(
        _response_mapping(getattr(turn_result, "final_response", None))
    )
    write_json(
        request.experiment_directory / "material_revision_critique.json",
        critique.model_dump(mode="json"),
    )
    return _material_revision_rejection_summary(critique)


def _selection_failure_summary(
    selection: ExperimentFlowSelection,
) -> Summary | None:
    selected_plan = selection.selected_plan
    experiment_design = selection.experiment_design
    if not selected_plan.selected:
        return classify_no_op(selected_plan.rationale)
    if experiment_design is None:
        return classify_invalid(
            "A selected plan did not include a valid experiment design.",
            failure_classification="missing_experiment_design",
        )
    if (
        not experiment_design.verification_commands
        and not experiment_design.confirmatory_commands
    ):
        return classify_selected_without_commands()
    return None


def _material_revision_decision(
    selection: ExperimentFlowSelection,
) -> MaterialRevisionDecision:
    before = _material_revision_payload(
        (
            selection.prior_research_spec
            if selection.research_spec is not None
            else None
        ),
        (
            selection.prior_feature_specs
            if selection.feature_specs is not None
            else None
        ),
    )
    after = _material_revision_payload(
        (
            selection.research_spec
            if selection.prior_research_spec is not None
            else None
        ),
        (
            selection.feature_specs
            if selection.prior_feature_specs is not None
            else None
        ),
    )
    return assess_material_revision(
        before,
        after,
        agent_declared_categories=selection.selected_plan.material_revision_categories,
    )


def _material_revision_payload(
    research_spec: Any | None,
    feature_specs: FeatureSpecs | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if research_spec is not None:
        if hasattr(research_spec, "model_dump"):
            payload.update(research_spec.model_dump(mode="json"))
        elif isinstance(research_spec, dict):
            payload.update(research_spec)
    if feature_specs is not None:
        features = feature_specs.model_dump(mode="json")["features"]
        payload["data_source"] = [
            feature.get("data_source")
            for feature in features
            if feature.get("data_source")
        ]
        payload["feature_family"] = [
            feature.get("feature_family")
            for feature in features
            if feature.get("feature_family")
        ]
    return payload


def _material_revision_rejection_summary(critique: Critique) -> Summary | None:
    if not _critic_blocks_experiment(critique):
        return None
    details = [*critique.fatal_issues, *critique.required_revisions]
    reason = "Material revision Critic rejected revision."
    if details:
        reason = f"{reason} {'; '.join(details)}."
    return classify_invalid(
        reason,
        failed_stage="critic_review",
        failure_classification="material_revision_rejected",
    )


_BLOCKING_CRITIC_DECISIONS = frozenset(
    {
        "fatal",
        "reject",
        "rejected",
        "revise",
        "requires_revision",
        "revision_required",
    }
)


def _critic_blocks_experiment(critique: Critique) -> bool:
    return (
        _normalized_critic_decision(critique.decision) in _BLOCKING_CRITIC_DECISIONS
        or bool(critique.fatal_issues)
        or bool(critique.required_revisions)
    )


def _normalized_critic_decision(decision: str) -> str:
    return "_".join(decision.strip().lower().replace("-", " ").split())


def _worktree_policy_failure(
    spec: ResearchRunSpec,
    experiment_design: ExperimentDesign,
) -> Summary | None:
    if spec.worktree.create or not _design_requires_editable_worktree(
        experiment_design
    ):
        return None
    return classify_invalid(
        "worktree.create:false is allowed only for read-only selected designs.",
        failure_classification="worktree_disabled_for_editing",
        failed_stage="implementation",
    )


def _design_requires_editable_worktree(
    experiment_design: ExperimentDesign,
) -> bool:
    return bool(
        experiment_design.allowed_write_paths or experiment_design.verification_commands
    )


def _prepare_experiment_worktree_if_needed(
    spec: ResearchRunSpec,
    request: ExperimentFlowRequest,
    experiment_design: ExperimentDesign,
) -> ExperimentWorktree | None:
    del experiment_design
    if not spec.worktree.create:
        return None
    return prepare_experiment_worktree(
        target_repository=spec.target_repository,
        worktree_root=spec.worktree.root,
        research_run_id=request.research_run_id,
        experiment_id=request.experiment_id,
    )


def _run_verification_if_needed(
    *,
    request: ExperimentFlowRequest,
    experiment_design: ExperimentDesign,
    worktree: ExperimentWorktree | None,
    agent_runtime: Any | None,
) -> dict[str, Any] | None:
    if not experiment_design.verification_commands:
        return None
    if worktree is None:
        return classify_invalid(
            "Verification commands require an Experiment Worktree.",
            failure_classification="missing_experiment_worktree",
            failed_stage="implementation",
        ).model_dump(mode="json") | {"status": "failed"}
    return run_verification_commands(
        verification_commands=experiment_design.verification_commands,
        cwd=worktree.path,
        run_dir=request.experiment_directory,
        data_root=request.spec.data_root,
        repo_root=worktree.path,
        timeout_seconds=_data_audit_timeout_seconds(request.spec, experiment_design),
        max_repairs=request.spec.implementation.max_repairs,
        repair_callback=_repair_callback(request, worktree, agent_runtime),
    )


def _run_evaluation_if_needed(
    *,
    request: ExperimentFlowRequest,
    experiment_design: ExperimentDesign,
    worktree: ExperimentWorktree | None,
    agent_runtime: Any | None,
) -> Summary | None:
    if not (
        experiment_design.confirmatory_commands
        or experiment_design.exploratory_commands
    ):
        return None

    worktree_path = (
        worktree.path if worktree is not None else request.spec.target_repository
    )
    workspace = create_evaluator_workspace(
        experiment_dir=request.experiment_directory,
        worktree_path=worktree_path,
        data_root=request.spec.data_root,
        git_sha=git_snapshot(worktree_path).head or "",
        canonical_artifacts=_canonical_artifacts(request.experiment_directory),
        locked_artifacts=_locked_artifacts(request),
        confirmatory_commands=_command_records(experiment_design.confirmatory_commands),
        exploratory_commands=_command_records(experiment_design.exploratory_commands),
    )
    if agent_runtime is None:
        return None

    summary: Summary | None = None
    try:
        thread = open_evaluator_thread(
            agent_runtime,
            request.state,
            workspace.path,
            model=request.spec.codex.model,
            effort=request.spec.codex.effort,
        )
        append_ledger_event(
            request.ledger_path,
            event_type="evaluation_attempt",
            research_run_id=request.research_run_id,
            experiment_id=request.experiment_id,
            evaluator_thread_id=thread.id,
            evaluator_workspace=str(workspace.path),
        )
        turn_result = _run_agent_turn_with_usage_limit(
            role=ResearchAgentRole.EVALUATOR,
            run=lambda: thread.run(
                _evaluation_input(request, workspace.manifest_path),
                agent_config(
                    ResearchAgentRole.EVALUATOR,
                    workspace.path,
                    model=request.spec.codex.model,
                    effort=request.spec.codex.effort,
                ),
            ),
        )
        summary = _write_evaluation_artifacts(
            request.experiment_directory,
            _response_mapping(getattr(turn_result, "final_response", None)),
        )
    except UsageLimitWait:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        summary = classify_run_failed(
            str(exc) or type(exc).__name__,
            failed_stage="evaluation",
            failure_classification="evaluation_runtime_defect",
        )
    except Exception as exc:
        summary = classify_run_failed(
            str(exc) or type(exc).__name__,
            failed_stage="evaluation",
            failure_classification="evaluation_runtime_defect",
        )
    try:
        run_evaluation_boundary_audit(workspace)
    except EvaluationBoundaryError as exc:
        return classify_run_failed(
            str(exc),
            failed_stage="evaluation_boundary_audit",
            failure_classification="evaluation_boundary_violation",
        )
    return summary


def _canonical_artifacts(experiment_dir: Path) -> dict[str, Path]:
    candidates = {
        "selected_plan": experiment_dir / "selected_plan.json",
        "research_spec": experiment_dir / "research_spec.json",
        "feature_specs": experiment_dir / "feature_specs.json",
        "experiment_design": experiment_dir / "experiment_design.json",
        "data_audit": experiment_dir / "data_audit.json",
        "implementation": experiment_dir / "implementation.json",
        "implementation_diff_summary": experiment_dir
        / "implementation_diff_summary.json",
    }
    return {name: path for name, path in candidates.items() if path.exists()}


def _locked_artifacts(request: ExperimentFlowRequest) -> list[Path]:
    candidates = [
        request.run_directory / "research_run_spec.yaml",
        request.experiment_directory / "selected_plan.json",
        request.experiment_directory / "research_spec.json",
        request.experiment_directory / "feature_specs.json",
        request.experiment_directory / "experiment_design.json",
    ]
    return [path for path in candidates if path.exists()]


def _command_records(commands: list[Any]) -> list[dict[str, Any]]:
    return command_declaration_records(commands)


def _evaluation_input(
    request: ExperimentFlowRequest,
    manifest_path: Path,
) -> str:
    return "\n".join(
        [
            f"Evaluate Research Experiment {request.experiment_id}.",
            f"Read manifest: {manifest_path.name}",
            "Write scripts under eval_scratch and outputs under eval_outputs.",
            "Return confirmatory_evaluation_result, exploratory_diagnostics_result, and analysis_ledger.",
        ]
    )


def _material_revision_critic_input(
    request: ExperimentFlowRequest,
    decision: MaterialRevisionDecision,
) -> str:
    return "\n".join(
        [
            f"Review material revision for {request.experiment_id}.",
            f"Material categories: {', '.join(decision.material_categories)}.",
            "Review artifacts:",
            *_material_revision_review_artifacts(request),
        ]
    )


def _material_revision_review_artifacts(request: ExperimentFlowRequest) -> list[str]:
    artifact_names = [
        "selected_plan.json",
        "experiment_design.json",
        "research_spec.json",
        "feature_specs.json",
    ]
    return [
        name
        for name in artifact_names
        if (request.experiment_directory / name).exists()
    ]


def _response_mapping(final_response: Any) -> dict[str, Any]:
    if isinstance(final_response, dict):
        return final_response
    if isinstance(final_response, str):
        parsed = json.loads(final_response)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Evaluator response must be a JSON object.")


def _write_evaluation_artifacts(
    experiment_dir: Path,
    payload: dict[str, Any],
) -> Summary:
    confirmatory = ConfirmatoryEvaluationResult.model_validate(
        payload["confirmatory_evaluation_result"]
    )
    exploratory = ExploratoryDiagnosticsResult.model_validate(
        payload.get("exploratory_diagnostics_result", {})
    )
    analysis_ledger = AnalysisLedger.model_validate(
        payload.get("analysis_ledger", {"entries": []})
    )
    write_json(
        experiment_dir / "confirmatory_evaluation_result.json",
        confirmatory.model_dump(mode="json"),
    )
    write_json(
        experiment_dir / "exploratory_diagnostics_result.json",
        exploratory.model_dump(mode="json"),
    )
    write_json(
        experiment_dir / "analysis_ledger.json",
        analysis_ledger.model_dump(mode="json"),
    )
    return Summary(
        outcome=confirmatory.outcome,
        outcome_reason=confirmatory.outcome_reason,
        failed_stage=confirmatory.failed_stage,
        failure_classification=confirmatory.failure_classification,
        summary=confirmatory.outcome_reason,
        confirmatory_findings=confirmatory.pre_registered_evidence,
        exploratory_findings=exploratory.findings,
    )


def _repair_callback(
    request: ExperimentFlowRequest,
    worktree: ExperimentWorktree,
    agent_runtime: Any | None,
):
    if agent_runtime is None:
        return None

    def repair(repair_request: VerificationRepairRequest) -> None:
        thread = open_implementer_thread(
            agent_runtime,
            request.state,
            worktree.path,
            model=request.spec.codex.model,
            effort=request.spec.codex.effort,
        )
        append_ledger_event(
            request.ledger_path,
            event_type="implementation_repair_attempt",
            research_run_id=request.research_run_id,
            experiment_id=request.experiment_id,
            repair_attempt=repair_request.attempt,
            verification_attempt=repair_request.attempt - 1,
            failed_command_count=len(repair_request.failed_results),
            implementer_thread_id=thread.id,
        )
        turn_result = _run_agent_turn_with_usage_limit(
            role=ResearchAgentRole.IMPLEMENTER,
            run=lambda: thread.run(
                _verification_repair_input(request, repair_request),
                agent_config(
                    ResearchAgentRole.IMPLEMENTER,
                    worktree.path,
                    model=request.spec.codex.model,
                    effort=request.spec.codex.effort,
                ),
            ),
        )
        final_response = getattr(turn_result, "final_response", None)
        if isinstance(final_response, dict):
            write_json(
                request.experiment_directory
                / f"implementation_repair_{repair_request.attempt}.json",
                final_response,
            )

    return repair


def _run_agent_turn_with_usage_limit(
    *,
    role: ResearchAgentRole,
    run: Callable[[], Any],
) -> Any:
    try:
        return run()
    except UsageLimitWait:
        raise
    except Exception as exc:
        first_exception: Exception | None = exc

    wait_event: UsageLimitEvent | None = None

    def replay_first_exception_then_run() -> Any:
        nonlocal first_exception
        if first_exception is not None:
            exc = first_exception
            first_exception = None
            raise exc
        return run()

    def record_wait(event: UsageLimitEvent) -> None:
        nonlocal wait_event
        wait_event = event

    def propagate_wait(_sleep_seconds: float) -> None:
        if wait_event is not None:
            raise UsageLimitWait(wait_event)

    return run_with_usage_limit_retry(
        role=f"research-{role.value}",
        run=replay_first_exception_then_run,
        record_wait=record_wait,
        sleep=propagate_wait,
    )


def _verification_repair_input(
    request: ExperimentFlowRequest,
    repair_request: VerificationRepairRequest,
) -> str:
    failed_logs = [
        result["stderr_path"]
        for result in repair_request.failed_results
        if isinstance(result.get("stderr_path"), str)
    ]
    return "\n".join(
        [
            f"Verification failed for {request.experiment_id}.",
            "Repair execution defects only; do not change research semantics.",
            f"Repair attempt: {repair_request.attempt}",
            "Failed stderr logs:",
            *failed_logs,
        ]
    )


def _terminal_summary_after_data_audit(selection: ExperimentFlowSelection) -> Summary:
    if selection.terminal_summary is None:
        return classify_invalid(
            "A selected plan did not produce a terminal summary.",
            failure_classification="missing_terminal_summary",
        )
    if selection.terminal_summary.outcome is ResearchOutcome.no_op:
        return classify_invalid(
            "A selected plan cannot produce a no-op terminal outcome.",
            failure_classification="selected_plan_returned_no_op",
        )
    return selection.terminal_summary


def _summary_from_result(result: dict[str, Any]) -> Summary:
    return Summary.model_validate(
        {field: result[field] for field in Summary.model_fields if field in result}
    )


def _data_audit_timeout_seconds(
    spec: ResearchRunSpec,
    experiment_design: ExperimentDesign,
) -> float:
    if experiment_design.timeout_seconds is not None:
        return experiment_design.timeout_seconds
    return float(spec.selected_budget.default_command_timeout_seconds)


def _default_no_op_selection() -> ExperimentFlowSelection:
    return ExperimentFlowSelection(
        selected_plan=SelectedPlan(
            selected=False,
            rationale="No admissible experiment selected.",
        ),
        experiment_design=None,
    )


def _write_artifact_once(
    path: Path,
    experiment_id: str,
    data: dict[str, Any],
) -> None:
    if path.exists():
        raise ExperimentFlowError(
            f"Research Experiment {experiment_id} already has {path.name}."
        )
    write_json(path, data)


def _mirror_experiment_if_enabled(
    request: ExperimentFlowRequest,
    summary: Summary,
) -> None:
    if not request.spec.mlflow.enabled:
        return
    mirror_research_run(
        ResearchRunMirrorRequest(
            run_dir=request.experiment_directory,
            tracking_uri=request.spec.mlflow.tracking_uri,
            experiment_name=request.spec.mlflow.experiment_name,
            research_run_id=request.research_run_id,
            experiment_id=request.experiment_id,
            outcome=summary.outcome.value,
            failed_stage=summary.failed_stage,
            failure_classification=summary.failure_classification,
            git_sha=_mirror_git_sha(request.spec.target_repository),
        ),
        ledger_path=request.ledger_path,
    )


def _mirror_git_sha(repo: Path) -> str:
    try:
        return git_snapshot(repo).head or ""
    except Exception:
        return ""
