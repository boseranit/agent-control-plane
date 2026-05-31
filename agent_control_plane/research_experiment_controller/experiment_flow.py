from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller.artifacts import (
    ExperimentDesign,
    ResearchOutcome,
    SelectedPlan,
    Summary,
)
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_invalid,
    classify_no_op,
    classify_selected_without_commands,
)
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
    run_data_audit_phase,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    ResearchRunSpec,
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


class ExperimentFlowError(RuntimeError):
    """Raised when one bounded Research Experiment cannot finish."""


def run_experiment_flow(
    request: ExperimentFlowRequest,
    *,
    selection: ExperimentFlowSelection | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    del agent_runtime

    experiment_dir = Path(request.experiment_directory)
    experiment_dir.mkdir(parents=True, exist_ok=True)
    selection = selection or _default_no_op_selection()
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

    summary_model = _selection_failure_summary(selection)
    if summary_model is None:
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
            summary_model = _terminal_summary_after_data_audit(selection)

    summary = summary_model.model_dump(mode="json")
    _write_artifact_once(
        experiment_dir / "summary.json",
        request.experiment_id,
        summary,
    )
    return {
        "status": "experiment_completed",
        "experiment_id": request.experiment_id,
        **summary,
    }


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
        {field: result[field] for field in Summary.model_fields}
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
