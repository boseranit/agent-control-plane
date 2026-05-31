from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from agent_control_plane.research_experiment_controller.research_run_mirror import (
    ResearchRunMirrorRequest,
)


METRIC_SOURCES = (
    ("command_metrics", "command_metrics.json"),
    ("metrics", "metrics.json"),
    ("confirmatory_evaluation_result", "confirmatory_evaluation_result.json"),
)


class MLflowClient(Protocol):
    def set_tracking_uri(self, uri: str) -> None: ...
    def set_experiment(self, name: str) -> None: ...
    def start_run(self, *, run_name: str): ...
    def log_params(self, params: dict[str, object]) -> None: ...
    def set_tags(self, tags: dict[str, object]) -> None: ...
    def log_metric(self, key: str, value: float) -> None: ...
    def log_artifact(
        self, local_path: str, artifact_path: str | None = None
    ) -> None: ...


def mirror_to_mlflow(
    request: ResearchRunMirrorRequest,
    *,
    mlflow_client: MLflowClient | None = None,
) -> dict[str, str]:
    client = mlflow_client or _default_mlflow_client()
    run_dir = Path(request.run_dir)
    if request.tracking_uri:
        client.set_tracking_uri(request.tracking_uri)
    if request.experiment_name:
        client.set_experiment(request.experiment_name)
    with client.start_run(run_name=request.experiment_id):
        client.log_params(
            {
                "research_run_id": request.research_run_id,
                "experiment_id": request.experiment_id,
            }
        )
        client.set_tags(
            {
                "outcome": request.outcome,
                "failed_stage": request.failed_stage or "",
                "failure_classification": request.failure_classification or "",
                "git_sha": request.git_sha,
            }
        )
        for metric_name, metric_value in _iter_metrics(run_dir):
            client.log_metric(metric_name, metric_value)
        for artifact_path in _iter_artifacts(run_dir):
            relative_parent = artifact_path.parent.relative_to(run_dir)
            client.log_artifact(
                str(artifact_path),
                artifact_path=None
                if relative_parent == Path(".")
                else relative_parent.as_posix(),
            )
    return {"status": "mirrored"}


def _default_mlflow_client() -> MLflowClient:
    import mlflow

    return mlflow


def _iter_metrics(run_dir: Path) -> Iterator[tuple[str, float]]:
    for source_name, filename in METRIC_SOURCES:
        path = run_dir / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        yield from _flatten_numeric(data, prefix=source_name)


def _iter_artifacts(run_dir: Path) -> Iterator[Path]:
    yield from sorted(
        (path for path in run_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(run_dir).as_posix(),
    )


def _flatten_numeric(data: object, *, prefix: str) -> Iterator[tuple[str, float]]:
    if isinstance(data, dict):
        for key in sorted(data):
            yield from _flatten_numeric(data[key], prefix=f"{prefix}.{key}")
        return
    if isinstance(data, list):
        for index, item in enumerate(data):
            yield from _flatten_numeric(item, prefix=f"{prefix}.{index}")
        return
    if isinstance(data, bool) or not isinstance(data, (int, float)):
        return
    value = float(data)
    if math.isfinite(value):
        yield prefix, value
