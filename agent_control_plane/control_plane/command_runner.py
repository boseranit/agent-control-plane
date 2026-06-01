from __future__ import annotations

import os
import signal
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from typing import Sequence

from agent_control_plane.control_plane.json_artifacts import write_json


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: Sequence[str] = field(default_factory=tuple)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.argv, str):
            raise ValueError("Command argv must be a sequence, not a shell string.")
        if not self.argv:
            raise ValueError("Command argv must not be empty.")
        if not all(isinstance(part, str) for part in self.argv):
            raise ValueError("Command argv parts must be strings.")
        object.__setattr__(self, "argv", tuple(self.argv))


@dataclass(frozen=True)
class CommandResult:
    name: str
    argv: list[str]
    cwd: str
    status: str
    exit_code: int | None
    duration_seconds: float
    timeout_seconds: float | None
    stdout_path: str
    stderr_path: str
    env: dict[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": self.argv,
            "cwd": self.cwd,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "env": self.env,
            "timeout_seconds": self.timeout_seconds,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }


def run_command(
    command: CommandSpec,
    *,
    cwd: str | Path,
    stdout_path: str | Path,
    stderr_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    resolved_cwd = Path(cwd).resolve()
    resolved_stdout_path = Path(stdout_path).resolve()
    resolved_stderr_path = Path(stderr_path).resolve()
    resolved_stdout_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_env = {**os.environ, **(env or {})}
    started = time.monotonic()
    exit_code: int | None = None
    status = "failed"

    with (
        resolved_stdout_path.open("w", encoding="utf-8", buffering=1) as stdout_file,
        resolved_stderr_path.open("w", encoding="utf-8", buffering=1) as stderr_file,
    ):
        try:
            process = subprocess.Popen(
                list(command.argv),
                shell=False,
                cwd=resolved_cwd,
                env=runtime_env,
                stdout=stdout_file,
                stderr=stderr_file,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            stderr_file.write(f"failed to start command: {exc}\n")
        else:
            try:
                exit_code = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                stderr_file.write(
                    f"command timed out after {command.timeout_seconds} seconds\n"
                )
                status = "timed_out"
            else:
                status = "passed" if exit_code == 0 else "failed"

    return CommandResult(
        name=command.name,
        argv=list(command.argv),
        cwd=str(resolved_cwd),
        status=status,
        exit_code=exit_code,
        duration_seconds=round(time.monotonic() - started, 3),
        env=dict(env or {}),
        timeout_seconds=command.timeout_seconds,
        stdout_path=str(resolved_stdout_path),
        stderr_path=str(resolved_stderr_path),
    )


def run_command_combined_log(
    command: CommandSpec,
    *,
    cwd: str | Path,
    log_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    resolved_cwd = Path(cwd).resolve()
    resolved_log_path = Path(log_path).resolve()
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_env = {**os.environ, **(env or {})}
    started = time.monotonic()
    exit_code: int | None = None
    status = "failed"

    with resolved_log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        try:
            process = subprocess.Popen(
                list(command.argv),
                shell=False,
                cwd=resolved_cwd,
                env=runtime_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            log_file.write(f"failed to start command: {exc}\n")
        else:
            try:
                exit_code = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                log_file.write(
                    f"command timed out after {command.timeout_seconds} seconds\n"
                )
                status = "timed_out"
            else:
                status = "passed" if exit_code == 0 else "failed"

    return CommandResult(
        name=command.name,
        argv=list(command.argv),
        cwd=str(resolved_cwd),
        status=status,
        exit_code=exit_code,
        duration_seconds=round(time.monotonic() - started, 3),
        env=dict(env or {}),
        timeout_seconds=command.timeout_seconds,
        stdout_path=str(resolved_log_path),
        stderr_path=str(resolved_log_path),
    )


def write_command_metrics(path: str | Path, results: Sequence[CommandResult]) -> None:
    failed_count = sum(1 for result in results if result.status != "passed")
    write_json(
        path,
        {
            "command_count": len(results),
            "commands": [result.to_record() for result in results],
            "failed_count": failed_count,
            "passed": 1 if failed_count == 0 else 0,
            "status_counts": dict(Counter(result.status for result in results)),
            "total_duration_seconds": round(
                sum(result.duration_seconds for result in results), 3
            ),
        },
    )


def _process_group_kwargs() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {}


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait()
        return

    process.kill()
    process.wait()
