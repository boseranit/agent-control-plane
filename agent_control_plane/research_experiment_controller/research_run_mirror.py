from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchRunMirrorRequest:
    run_dir: str | Path
    tracking_uri: str | None
    experiment_name: str | None
    research_run_id: str
    experiment_id: str
    outcome: str
    failed_stage: str | None
    failure_classification: str | None
    git_sha: str


ResearchRunMirror = Callable[[ResearchRunMirrorRequest], dict[str, Any]]


def mirror_research_run(
    request: ResearchRunMirrorRequest,
    *,
    ledger_path: str | Path,
    mirror: ResearchRunMirror | None = None,
) -> dict[str, Any]:
    mirror_fn = mirror or _default_research_run_mirror
    try:
        return mirror_fn(request)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        from agent_control_plane.research_experiment_controller.ledger import (
            append_ledger_event,
        )

        append_ledger_event(
            ledger_path,
            event_type="mlflow_mirror_failed",
            research_run_id=request.research_run_id,
            experiment_id=request.experiment_id,
            message=message,
        )
        return {"status": "mlflow_mirror_failed", "message": message}


def _default_research_run_mirror(
    request: ResearchRunMirrorRequest,
) -> dict[str, Any]:
    from agent_control_plane.research_experiment_controller.mlflow_mirror import (
        mirror_to_mlflow,
    )

    return mirror_to_mlflow(request)
