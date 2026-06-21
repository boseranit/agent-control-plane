from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller.experiment_flow import (
    ExperimentFlowRequest,
)


def experiment_signal_panel_path(
    experiment_data_root: Path,
    *,
    experiment_name: str | None,
    research_run_id: str,
    experiment_id: str,
) -> Path:
    experiment_name_component = _safe_path_component(
        experiment_name or research_run_id,
        fallback="research-experiment",
    )
    run_name = _safe_path_component(
        f"{research_run_id}-{experiment_id}",
        fallback="run",
    )
    return experiment_data_root / experiment_name_component / run_name / (
        "signal_panel.parquet"
    )


def write_signal_panel(request: ExperimentFlowRequest) -> Path:
    signal_panel = request.experiment_data_directory / "signal_panel.parquet"
    signal_panel.parent.mkdir(parents=True, exist_ok=True)
    signal_panel.write_bytes(b"PAR1")
    return signal_panel


def signal_panel_writer_command() -> str:
    return (
        "import os; "
        "from pathlib import Path; "
        "root = Path(os.environ['RESEARCH_EXPERIMENT_DATA_ROOT']); "
        "root.mkdir(parents=True, exist_ok=True); "
        "(root / 'signal_panel.parquet').write_bytes(b'PAR1'); "
    )


def _safe_path_component(value: str, *, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return safe or fallback


def write_evaluation_result_files(
    evaluation_dir: Path,
    *,
    outcome: str = "completed_candidate",
    outcome_reason: str = "Locked gates passed.",
    failed_stage: str | None = None,
    failure_classification: str | None = None,
    ic: float = 0.04,
    evidence: str = "confirmatory command eval",
    exploratory_result: dict[str, Any] | None = None,
    analysis_ledger: dict[str, Any] | None = None,
) -> None:
    write_json(
        evaluation_dir / "confirmatory_evaluation_result.json",
        {
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            "failed_stage": failed_stage,
            "failure_classification": failure_classification,
            "metrics": {"ic": ic},
            "gate_results": {"ic": "passed"},
            "pre_registered_evidence": [evidence],
        },
    )
    write_json(
        evaluation_dir / "exploratory_diagnostics_result.json",
        exploratory_result
        if exploratory_result is not None
        else {
            "findings": ["turnover stable"],
            "metrics": {"turnover": 0.2},
            "plots": ["eval_outputs/turnover.png"],
            "future_experiment_ideas": ["lock turnover gate"],
        },
    )
    write_json(
        evaluation_dir / "analysis_ledger.json",
        analysis_ledger
        if analysis_ledger is not None
        else {"entries": [{"phase": "evaluation", "status": "completed"}]},
    )
