from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)


class ExperimentWorktreeError(RuntimeError):
    """Raised when an Experiment Worktree cannot be prepared safely."""


@dataclass(frozen=True)
class ExperimentWorktree:
    path: Path
    branch: str
    created: bool


def prepare_experiment_worktree(
    *,
    target_repository: str | Path,
    paths: ResearchProgramPaths,
    research_run_id: str,
    experiment_id: str,
) -> ExperimentWorktree:
    repo = Path(target_repository).resolve()
    path = paths.worktree_directory(research_run_id, experiment_id)
    branch = _branch_name(research_run_id, experiment_id)
    if path.exists():
        _require_clean_worktree(path)
        return ExperimentWorktree(path=path, branch=branch, created=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(path), "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ExperimentWorktreeError(detail or f"Could not create {path}")
    return ExperimentWorktree(path=path, branch=branch, created=True)


def _branch_name(research_run_id: str, experiment_id: str) -> str:
    return f"research/{research_run_id}/{experiment_id}"[:120]


def _require_clean_worktree(path: Path) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        detail = status.stderr.strip() or status.stdout.strip()
        raise ExperimentWorktreeError(
            f"Could not inspect Experiment Worktree {path}: {detail}"
        )
    if status.stdout.strip():
        raise ExperimentWorktreeError(f"Existing Experiment Worktree is dirty: {path}")
