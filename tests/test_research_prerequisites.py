from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.outcomes import (
    DATA_AUDIT_FAILURE_CLASSIFICATIONS,
    classify_data_audit_failure,
)
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
    run_data_audit_phase,
)


@pytest.mark.parametrize(
    "failure_classification",
    sorted(DATA_AUDIT_FAILURE_CLASSIFICATIONS),
)
def test_approved_data_audit_classifications_are_prerequisites_failed(
    failure_classification: str,
) -> None:
    summary = classify_data_audit_failure(failure_classification)
    expected_reason = f"Data/prerequisite audit failed: {failure_classification}."

    assert summary.model_dump(mode="json")["outcome"] == "prerequisites_failed"
    assert summary.failed_stage == "data_audit"
    assert summary.failure_classification == failure_classification
    assert summary.outcome_reason == expected_reason
    assert summary.summary == expected_reason


def test_unknown_data_audit_classification_uses_canonical_fallback() -> None:
    summary = classify_data_audit_failure("network_flake")
    expected_reason = (
        "Data/prerequisite audit failed: prerequisite_command_failed "
        "(declared failure_classification: network_flake)."
    )

    assert summary.model_dump(mode="json")["outcome"] == "prerequisites_failed"
    assert summary.failed_stage == "data_audit"
    assert summary.failure_classification == "prerequisite_command_failed"
    assert summary.outcome_reason == expected_reason
    assert summary.summary == expected_reason


def test_failed_data_audit_command_records_prerequisite_failure_and_metrics(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    experiment_data_root = tmp_path / "experiment-data" / "run" / "EXP-0001"
    run_dir = tmp_path / "run"
    repo.mkdir()
    data_root.mkdir()

    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=data_root,
            experiment_data_root=experiment_data_root,
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
                            "print(os.environ['RESEARCH_EXPERIMENT_DATA_ROOT']); "
                            "print(os.environ['HLM_DATA_ROOT']); "
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
    stdout = run_dir / "logs" / "data_audit-1-schema-check.stdout.log"
    stderr = run_dir / "logs" / "data_audit-1-schema-check.stderr.log"

    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "prerequisites_failed"
    assert result["failed_stage"] == "data_audit"
    assert result["failure_classification"] == "prerequisite_command_failed"
    assert result["data_audit"]["passed"] is False
    assert result["data_audit"]["command_results"][0]["status"] == "failed"
    assert metrics["failed_count"] == 1
    assert metrics["commands"][0]["name"] == "schema-check"
    assert metrics["commands"][0]["stdout_path"] == str(stdout.resolve())
    assert metrics["commands"][0]["stderr_path"] == str(stderr.resolve())
    assert stdout.read_text(encoding="utf-8").splitlines() == [
        str(data_root),
        str(experiment_data_root),
        str(data_root),
    ]
    assert experiment_data_root.is_dir()
    assert "schema failed" in stderr.read_text(encoding="utf-8")


def test_failed_data_audit_command_can_declare_failure_classification(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    experiment_data_root = tmp_path / "experiment-data" / "run" / "EXP-0001"
    run_dir = tmp_path / "run"
    repo.mkdir()
    data_root.mkdir()

    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=data_root,
            experiment_data_root=experiment_data_root,
            prerequisite_commands=[],
            data_audit_commands=[
                {
                    "name": "schema-check",
                    "argv": [sys.executable, "-c", "raise SystemExit(9)"],
                    "failure_classification": "schema_mismatch",
                }
            ],
            cwd=repo,
            run_dir=run_dir,
            timeout_seconds=60,
        )
    )

    assert result["outcome"] == "prerequisites_failed"
    assert result["failed_stage"] == "data_audit"
    assert result["failure_classification"] == "schema_mismatch"
    assert result["data_audit"]["failure_classification"] == "schema_mismatch"


def test_failed_data_audit_command_normalizes_unknown_failure_classification(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    experiment_data_root = tmp_path / "experiment-data" / "run" / "EXP-0001"
    run_dir = tmp_path / "run"
    repo.mkdir()
    data_root.mkdir()

    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=data_root,
            experiment_data_root=experiment_data_root,
            prerequisite_commands=[],
            data_audit_commands=[
                {
                    "name": "audit-or-hash-check",
                    "argv": [sys.executable, "-c", "raise SystemExit(9)"],
                    "failure_classification": "audit_or_hash_failure",
                }
            ],
            cwd=repo,
            run_dir=run_dir,
            timeout_seconds=60,
        )
    )

    expected_reason = (
        "Data/prerequisite audit failed: prerequisite_command_failed "
        "(declared failure_classification: audit_or_hash_failure)."
    )
    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "prerequisites_failed"
    assert result["failure_classification"] == "prerequisite_command_failed"
    assert result["data_audit"]["failure_classification"] == (
        "prerequisite_command_failed"
    )
    assert result["outcome_reason"] == expected_reason
    assert result["summary"] == expected_reason
    assert result["data_audit"]["outcome_reason"] == expected_reason
    assert result["data_audit"]["command_results"][0]["status"] == "failed"


def test_prerequisite_logs_do_not_collide_for_duplicate_command_names(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    experiment_data_root = tmp_path / "experiment-data" / "run" / "EXP-0001"
    run_dir = tmp_path / "run"
    repo.mkdir()
    data_root.mkdir()

    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=data_root,
            experiment_data_root=experiment_data_root,
            prerequisite_commands=[
                {
                    "name": "same-name",
                    "argv": [sys.executable, "-c", "print('prereq')"],
                }
            ],
            data_audit_commands=[
                {
                    "name": "same-name",
                    "argv": [sys.executable, "-c", "print('audit')"],
                }
            ],
            cwd=repo,
            run_dir=run_dir,
            timeout_seconds=60,
        )
    )

    assert result["status"] == "data_audit_passed"
    assert (
        run_dir / "logs" / "prerequisite-1-same-name.stdout.log"
    ).read_text(encoding="utf-8") == "prereq\n"
    assert (
        run_dir / "logs" / "data_audit-1-same-name.stdout.log"
    ).read_text(encoding="utf-8") == "audit\n"
