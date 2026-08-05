from __future__ import annotations

import os
import signal
import subprocess
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from typing import Sequence

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.control_plane.systemd_scope import (
    ResourceBoundaryUnavailable,
    SystemdMemoryScope,
)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: Sequence[str] = field(default_factory=tuple)
    timeout_seconds: float | None = None
    maximum_memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.argv, str):
            raise ValueError("Command argv must be a sequence, not a shell string.")
        if not self.argv:
            raise ValueError("Command argv must not be empty.")
        if not all(isinstance(part, str) for part in self.argv):
            raise ValueError("Command argv parts must be strings.")
        if self.maximum_memory_bytes is not None and (
            isinstance(self.maximum_memory_bytes, bool)
            or not isinstance(self.maximum_memory_bytes, int)
            or self.maximum_memory_bytes <= 0
        ):
            raise ValueError("Command maximum memory must be a positive integer.")
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
    maximum_memory_bytes: int | None = None
    memory_limit_exceeded: bool = False

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
            "maximum_memory_bytes": self.maximum_memory_bytes,
            "memory_limit_exceeded": self.memory_limit_exceeded,
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
    return _run_command(
        command,
        cwd=cwd,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        env=env,
        combine_output=False,
    )


def run_command_combined_log(
    command: CommandSpec,
    *,
    cwd: str | Path,
    log_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    return _run_command(
        command,
        cwd=cwd,
        stdout_path=log_path,
        stderr_path=log_path,
        env=env,
        combine_output=True,
    )


def _run_command(
    command: CommandSpec,
    *,
    cwd: str | Path,
    stdout_path: str | Path,
    stderr_path: str | Path,
    env: Mapping[str, str] | None,
    combine_output: bool,
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
    memory_limit_exceeded = False
    scope: SystemdMemoryScope | None = None

    with ExitStack() as stack:
        stdout_file = stack.enter_context(
            resolved_stdout_path.open("w", encoding="utf-8", buffering=1)
        )
        if combine_output:
            stderr_file = stdout_file
            stderr_target: Any = subprocess.STDOUT
        else:
            stderr_file = stack.enter_context(
                resolved_stderr_path.open("w", encoding="utf-8", buffering=1)
            )
            stderr_target = stderr_file
        try:
            argv = list(command.argv)
            if command.maximum_memory_bytes is not None:
                scope = SystemdMemoryScope.create(
                    command.maximum_memory_bytes,
                    purpose=command.name,
                )
                argv = list(scope.command_argv(argv))
            process = subprocess.Popen(
                argv,
                shell=False,
                cwd=resolved_cwd,
                env=runtime_env,
                stdout=stdout_file,
                stderr=stderr_target,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            stderr_file.write(f"failed to start command: {exc}\n")
        else:
            try:
                exit_code = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                if scope is not None:
                    scope.stop()
                _terminate_process_group(process)
                stderr_file.write(
                    f"command timed out after {command.timeout_seconds} seconds\n"
                )
                status = "timed_out"
            else:
                scope_result = scope.result() if scope is not None else None
                if scope is not None and exit_code != 0 and scope_result is None:
                    raise ResourceBoundaryUnavailable(
                        "systemd did not retain the requested command memory scope."
                    )
                memory_limit_exceeded = scope_result == "oom-kill"
                if memory_limit_exceeded:
                    status = "memory_limit_exceeded"
                    stderr_file.write(
                        "command exceeded the hard process-tree memory limit of "
                        f"{command.maximum_memory_bytes} bytes\n"
                    )
                else:
                    status = "passed" if exit_code == 0 else "failed"
        finally:
            if scope is not None:
                scope.cleanup()

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
        maximum_memory_bytes=command.maximum_memory_bytes,
        memory_limit_exceeded=memory_limit_exceeded,
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
