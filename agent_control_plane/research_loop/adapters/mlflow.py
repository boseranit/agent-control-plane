from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..mirror import MirrorRequest


class MLflowMirror:
    def mirror(self, request: MirrorRequest) -> None:
        import mlflow

        if request.tracking_uri is not None:
            mlflow.set_tracking_uri(request.tracking_uri)
        if request.experiment_name is not None:
            mlflow.set_experiment(request.experiment_name)

        with mlflow.start_run(run_name=request.exp_id):
            mlflow.log_param("research_run_id", request.research_run_id)
            mlflow.log_param("exp_id", request.exp_id)

            for key, value in _tags(request).items():
                mlflow.set_tag(key, value)

            for key, value in flatten_numeric_metrics(request.result_path).items():
                mlflow.log_metric(key, value)

            for path in iter_artifact_files(request):
                mlflow.log_artifact(str(path))


def flatten_numeric_metrics(result_path: Path) -> dict[str, float]:
    payload = _load_json(result_path)
    if not isinstance(payload, dict):
        return {}

    metrics: dict[str, float] = {}
    _add_metric(metrics, "gate.value", payload.get("gate_value"))
    scorecard = payload.get("metrics")
    if isinstance(scorecard, dict):
        for key in ("ic", "rank_ic", "sharpe", "coverage"):
            _add_metric(metrics, f"scorecard.{key}", scorecard.get(key))
    _add_metric(metrics, "bh_adjusted_p", payload.get("bh_adjusted_p"))
    return metrics


def iter_artifact_files(request: MirrorRequest) -> list[Path]:
    return [
        path
        for path in (
            request.spec_path,
            request.run_path,
            request.result_path,
            request.hypothesis_path,
        )
        if Path(path).is_file()
    ]


def _tags(request: MirrorRequest) -> dict[str, Any]:
    payload = _load_json(request.result_path)
    tags: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key in ("verdict", "looks_positive", "hypothesis_id"):
            value = payload.get(key)
            if value is not None:
                tags[key] = value
    if request.git_sha is not None:
        tags["git_sha"] = request.git_sha
    return tags


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _add_metric(metrics: dict[str, float], key: str, value: Any) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and math.isfinite(value):
        metrics[key] = float(value)
