from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from agent_control_plane.control_plane.command_runner import (
    CommandResult,
    CommandSpec,
    run_command,
    run_command_combined_log,
    write_command_metrics,
)


@pytest.mark.parametrize(
    "argv",
    [
        "python -c 'print(1)'",
        [],
        ["python", 1],
    ],
)
def test_command_spec_rejects_shell_strings_empty_argv_and_non_string_parts(
    argv: object,
) -> None:
    with pytest.raises(ValueError):
        CommandSpec(name="bad", argv=argv)  # type: ignore[arg-type]


def test_run_command_uses_cwd_and_env_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACP_PARENT_VALUE", "parent")
    monkeypatch.setenv("ACP_OVERRIDE_VALUE", "old")
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    command = CommandSpec(
        name="env-cwd",
        argv=[
            sys.executable,
            "-c",
            (
                "import os, pathlib; "
                "print(pathlib.Path.cwd().resolve()); "
                "print(os.environ['ACP_PARENT_VALUE']); "
                "print(os.environ['ACP_OVERRIDE_VALUE'])"
            ),
        ],
    )

    result = run_command(
        command,
        cwd=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        env={"ACP_OVERRIDE_VALUE": "new"},
    )

    assert result.status == "passed"
    assert result.cwd == str(tmp_path.resolve())
    assert stdout_path.read_text(encoding="utf-8").splitlines() == [
        str(tmp_path.resolve()),
        "parent",
        "new",
    ]
    assert stderr_path.read_text(encoding="utf-8") == ""


def test_run_command_streams_stdout_and_stderr_to_persisted_logs(
    tmp_path: Path,
) -> None:
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    command = CommandSpec(
        name="stream",
        argv=[
            sys.executable,
            "-c",
            (
                "import sys, time; "
                "print('stdout-live', flush=True); "
                "print('stderr-live', file=sys.stderr, flush=True); "
                "time.sleep(1)"
            ),
        ],
    )
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            run_command(
                command,
                cwd=tmp_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        )
    )

    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        stdout_text = (
            stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
        )
        stderr_text = (
            stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
        )
        if "stdout-live" in stdout_text and "stderr-live" in stderr_text:
            break
        time.sleep(0.02)
    else:
        pytest.fail("command logs did not stream before process completion")

    assert worker.is_alive()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert results[0].status == "passed"
    assert "stdout-live" in stdout_path.read_text(encoding="utf-8")
    assert "stderr-live" in stderr_path.read_text(encoding="utf-8")


def test_run_command_records_nonzero_exit_as_failed(tmp_path: Path) -> None:
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    command = CommandSpec(
        name="nonzero",
        argv=[
            sys.executable,
            "-c",
            "import sys; print('bad', file=sys.stderr); raise SystemExit(7)",
        ],
    )

    result = run_command(
        command,
        cwd=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )

    assert result.status == "failed"
    assert result.exit_code == 7
    assert result.duration_seconds >= 0
    assert "bad" in stderr_path.read_text(encoding="utf-8")


def test_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    marker_path = tmp_path / "child-survived.txt"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    command = CommandSpec(
        name="timeout",
        argv=[
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                "subprocess.Popen(["
                "sys.executable, '-c', "
                "'import os, pathlib, time; "
                "time.sleep(0.6); "
                'pathlib.Path(os.environ["ACP_MARKER_PATH"]).write_text("alive")\''
                "]); "
                "time.sleep(2)"
            ),
        ],
        timeout_seconds=0.15,
    )

    started = time.monotonic()
    result = run_command(
        command,
        cwd=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        env={"ACP_MARKER_PATH": str(marker_path)},
    )
    elapsed = time.monotonic() - started

    assert result.status == "timed_out"
    assert result.exit_code is None
    assert result.timeout_seconds == 0.15
    assert elapsed < 1.5
    time.sleep(0.8)
    assert not marker_path.exists()
    assert stdout_path.exists()
    assert stderr_path.exists()


def test_write_command_metrics_writes_deterministic_summary(tmp_path: Path) -> None:
    metrics_path = tmp_path / "command_metrics.json"
    results = [
        CommandResult(
            name="ok",
            argv=["true"],
            cwd="/repo",
            status="passed",
            exit_code=0,
            duration_seconds=1.2,
            timeout_seconds=None,
            stdout_path="/logs/ok.out",
            stderr_path="/logs/ok.err",
        ),
        CommandResult(
            name="bad",
            argv=["false"],
            cwd="/repo",
            status="failed",
            exit_code=1,
            duration_seconds=0.3,
            timeout_seconds=None,
            stdout_path="/logs/bad.out",
            stderr_path="/logs/bad.err",
        ),
        CommandResult(
            name="slow",
            argv=["sleep", "10"],
            cwd="/repo",
            status="timed_out",
            exit_code=None,
            duration_seconds=0.5,
            timeout_seconds=0.1,
            stdout_path="/logs/slow.out",
            stderr_path="/logs/slow.err",
        ),
    ]

    write_command_metrics(metrics_path, results)
    first_write = metrics_path.read_text(encoding="utf-8")
    write_command_metrics(metrics_path, results)

    assert metrics_path.read_text(encoding="utf-8") == first_write
    assert (
        first_write
        == """\
{
  "command_count": 3,
  "commands": [
    {
      "argv": [
        "true"
      ],
      "cwd": "/repo",
      "duration_seconds": 1.2,
      "exit_code": 0,
      "name": "ok",
      "status": "passed",
      "stderr_path": "/logs/ok.err",
      "stdout_path": "/logs/ok.out",
      "timeout_seconds": null
    },
    {
      "argv": [
        "false"
      ],
      "cwd": "/repo",
      "duration_seconds": 0.3,
      "exit_code": 1,
      "name": "bad",
      "status": "failed",
      "stderr_path": "/logs/bad.err",
      "stdout_path": "/logs/bad.out",
      "timeout_seconds": null
    },
    {
      "argv": [
        "sleep",
        "10"
      ],
      "cwd": "/repo",
      "duration_seconds": 0.5,
      "exit_code": null,
      "name": "slow",
      "status": "timed_out",
      "stderr_path": "/logs/slow.err",
      "stdout_path": "/logs/slow.out",
      "timeout_seconds": 0.1
    }
  ],
  "failed_count": 2,
  "passed": 0,
  "status_counts": {
    "failed": 1,
    "passed": 1,
    "timed_out": 1
  },
  "total_duration_seconds": 2.0
}
"""
    )


def test_run_command_combined_log_writes_stdout_and_stderr_to_one_log(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "combined.log"
    command = CommandSpec(
        name="combined",
        argv=[
            sys.executable,
            "-c",
            "import sys; print('stdout-combined'); print('stderr-combined', file=sys.stderr)",
        ],
    )

    result = run_command_combined_log(command, cwd=tmp_path, log_path=log_path)

    log_text = log_path.read_text(encoding="utf-8")
    assert result.status == "passed"
    assert result.stdout_path == str(log_path.resolve())
    assert result.stderr_path == str(log_path.resolve())
    assert "stdout-combined" in log_text
    assert "stderr-combined" in log_text
