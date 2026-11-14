# Linux cgroup boundary for controller-owned process trees.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SYSTEMCTL_TIMEOUT_SECONDS = 5.0


class ResourceBoundaryUnavailable(RuntimeError):
    """Raised when a requested hard process-tree boundary cannot be enforced."""


class ResourceLimitExceeded(RuntimeError):
    """A controller-owned process tree crossed its configured resource ceiling."""


@dataclass(frozen=True)
class SystemdMemoryScope:
    """One transient user cgroup with an aggregate physical-memory ceiling."""

    unit_name: str
    maximum_memory_bytes: int
    systemd_run_path: Path
    systemctl_path: Path

    @classmethod
    def create(cls, maximum_memory_bytes: int, *, purpose: str) -> SystemdMemoryScope:
        if (
            isinstance(maximum_memory_bytes, bool)
            or not isinstance(maximum_memory_bytes, int)
            or maximum_memory_bytes <= 0
        ):
            raise ValueError(
                "Maximum memory must be a positive integer number of bytes."
            )
        if not sys.platform.startswith("linux"):
            raise ResourceBoundaryUnavailable(
                "Hard process-tree memory limits require Linux cgroup v2."
            )
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise ResourceBoundaryUnavailable(
                "Hard process-tree memory limits require Linux cgroup v2."
            )
        systemd_run = shutil.which("systemd-run")
        systemctl = shutil.which("systemctl")
        if systemd_run is None or systemctl is None:
            raise ResourceBoundaryUnavailable(
                "Hard process-tree memory limits require systemd-run and systemctl."
            )
        safe_purpose = re.sub(r"[^A-Za-z0-9_-]+", "-", purpose).strip("-")
        safe_purpose = (safe_purpose or "command")[:32]
        return cls(
            unit_name=f"acp-{safe_purpose}-{uuid.uuid4().hex}.scope",
            maximum_memory_bytes=maximum_memory_bytes,
            systemd_run_path=Path(systemd_run),
            systemctl_path=Path(systemctl),
        )

    def command_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        """Return a command whose descendants share this scope's memory ceiling."""
        return (
            str(self.systemd_run_path),
            "--user",
            "--scope",
            "--quiet",
            f"--unit={self.unit_name}",
            "--property",
            f"MemoryMax={self.maximum_memory_bytes}",
            "--property",
            "MemorySwapMax=0",
            "--property",
            "OOMPolicy=kill",
            "--",
            *argv,
        )

    def result(self) -> str | None:
        """Return systemd's terminal cause while a failed scope remains loaded."""
        completed = self._systemctl(
            "show",
            self.unit_name,
            "--property=Result",
            "--value",
        )
        if completed is None or completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def stop(self) -> None:
        """Stop every process still held by this command scope."""
        completed = self._systemctl("stop", self.unit_name)
        if completed is None or completed.returncode != 0:
            self._systemctl(
                "kill",
                "--kill-whom=all",
                "--signal=KILL",
                self.unit_name,
            )

    def cleanup(self) -> None:
        """Release retained failed-unit metadata after its result is recorded."""
        self._systemctl("reset-failed", self.unit_name)

    def _systemctl(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                [str(self.systemctl_path), "--user", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=SYSTEMCTL_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
