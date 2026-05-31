from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_data_audit_failure,
)
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
    run_data_audit_phase,
)


@pytest.mark.parametrize(
    "failure_classification",
    [
        "data_root_missing",
        "feature_family_missing",
        "schema_mismatch",
        "artifact_missing",
        "point_in_time_invalid",
        "prerequisite_command_failed",
    ],
)
def test_approved_data_audit_classifications_are_prerequisites_failed(
    failure_classification: str,
) -> None:
    summary = classify_data_audit_failure(failure_classification)

    assert summary.model_dump(mode="json")["outcome"] == "prerequisites_failed"
    assert summary.failed_stage == "data_audit"
    assert summary.failure_classification == failure_classification


def test_unknown_data_audit_classification_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown data-audit failure classification"):
        classify_data_audit_failure("network_flake")


def test_failed_data_audit_command_records_prerequisite_failure_and_metrics(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    run_dir = tmp_path / "run"
    repo.mkdir()
    data_root.mkdir()

    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=data_root,
            prerequisite_commands=[],
            data_audit_commands=[
                {
                    "name": "schema-check",
                    "argv": [
                        sys.executable,
                        "-c",
                        (
                            "import os, sys; "
                            "print(os.environ['RESEARCH_DATA_ROOT']); "
                            "print('schema failed', file=sys.stderr); "
                            "raise SystemExit(9)"
                        ),
                    ],
                }
            ],
            cwd=repo,
            run_dir=run_dir,
            timeout_seconds=60,
        )
    )

    metrics = read_json_object(run_dir / "command_metrics.json")
    stdout = run_dir / "commands" / "data_audit_1_stdout.log"
    stderr = run_dir / "commands" / "data_audit_1_stderr.log"

    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "prerequisites_failed"
    assert result["failed_stage"] == "data_audit"
    assert result["failure_classification"] == "prerequisite_command_failed"
    assert result["data_audit"]["passed"] is False
    assert result["data_audit"]["command_results"][0]["status"] == "failed"
    assert metrics["failed_count"] == 1
    assert metrics["commands"][0]["name"] == "schema-check"
    assert stdout.read_text(encoding="utf-8").strip() == str(data_root)
    assert "schema failed" in stderr.read_text(encoding="utf-8")
