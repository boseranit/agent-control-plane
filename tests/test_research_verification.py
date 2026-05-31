from __future__ import annotations

import sys
from pathlib import Path

from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.research_experiment_controller.verification import (
    run_verification_commands,
)


def test_verification_commands_pass_without_repair(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    result = run_verification_commands(
        verification_commands=[
            {"name": "unit", "argv": [sys.executable, "-c", "print('ok')"]}
        ],
        cwd=tmp_path,
        run_dir=run_dir,
        timeout_seconds=60,
        max_repairs=0,
    )

    metrics = read_json_object(run_dir / "command_metrics.json")
    assert result["status"] == "passed"
    assert result["attempts"] == 1
    assert metrics["command_count"] == 1
    assert metrics["failed_count"] == 0
    assert (run_dir / "verification" / "attempt_0" / "unit_stdout.log").exists()


def test_verification_commands_receive_research_environment(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    data_root = tmp_path / "data"
    data_root.mkdir()

    result = run_verification_commands(
        verification_commands=[
            {
                "name": "env-check",
                "argv": [
                    sys.executable,
                    "-c",
                    (
                        "import os, pathlib; "
                        "assert os.environ['RESEARCH_DATA_ROOT'] == "
                        "str(pathlib.Path('data').resolve()); "
                        "assert os.environ['RESEARCH_RUN_DIR'] == "
                        "str(pathlib.Path('run').resolve()); "
                        "assert os.environ['RESEARCH_REPO_ROOT'] == "
                        "str(pathlib.Path('.').resolve())"
                    ),
                ],
            }
        ],
        cwd=tmp_path,
        run_dir=run_dir,
        data_root=data_root,
        repo_root=tmp_path,
        timeout_seconds=60,
        max_repairs=0,
    )

    assert result["status"] == "passed"


def test_verification_failure_repairs_and_retries_until_pass(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    calls: list[int] = []

    def repair(request) -> None:
        calls.append(request.attempt)
        assert request.failed_results[0]["status"] == "failed"
        (tmp_path / "fixed.txt").write_text("fixed\n", encoding="utf-8")

    result = run_verification_commands(
        verification_commands=[
            {
                "name": "unit",
                "argv": [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; import sys; "
                        "sys.exit(0 if Path('fixed.txt').exists() else 2)"
                    ),
                ],
            }
        ],
        cwd=tmp_path,
        run_dir=run_dir,
        timeout_seconds=60,
        max_repairs=1,
        repair_callback=repair,
    )

    metrics = read_json_object(run_dir / "command_metrics.json")
    assert result["status"] == "passed"
    assert result["attempts"] == 2
    assert result["repairs"] == 1
    assert calls == [1]
    assert metrics["command_count"] == 2
    assert metrics["failed_count"] == 1
    assert (run_dir / "verification" / "attempt_1" / "unit_stdout.log").exists()


def test_verification_failure_exhausts_max_repairs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    calls: list[int] = []

    result = run_verification_commands(
        verification_commands=[
            {
                "name": "unit",
                "argv": [sys.executable, "-c", "raise SystemExit(3)"],
            }
        ],
        cwd=tmp_path,
        run_dir=run_dir,
        timeout_seconds=60,
        max_repairs=2,
        repair_callback=lambda request: calls.append(request.attempt),
    )

    assert result["status"] == "failed"
    assert result["outcome"] == "run_failed"
    assert result["outcome_reason"] == "Verification commands failed after 2 repairs."
    assert result["failed_stage"] == "verification"
    assert result["failure_classification"] == "verification_command_failed"
    assert result["attempts"] == 3
    assert result["repairs"] == 2
    assert calls == [1, 2]
