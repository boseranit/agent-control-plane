from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_control_plane.control_plane.boundary_audit import GitSnapshot, git_snapshot
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
    seed_worktree: str | Path | None = None,
) -> ExperimentWorktree:
    repo = Path(target_repository).resolve()
    path = paths.worktree_directory(research_run_id, experiment_id)
    branch = _branch_name(research_run_id, experiment_id)
    if path.exists():
        _require_clean_worktree(path)
        return ExperimentWorktree(path=path, branch=branch, created=False)

    seed_path = Path(seed_worktree).resolve() if seed_worktree is not None else None
    seed_snapshot = _seed_snapshot(seed_path) if seed_path is not None else None
    start_point = seed_snapshot.head if seed_snapshot is not None else "HEAD"
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(path), start_point or "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ExperimentWorktreeError(detail or f"Could not create {path}")
    if seed_path is not None and seed_snapshot is not None:
        _copy_seed_changes(seed_path, path, seed_snapshot.changed_files)
    return ExperimentWorktree(path=path, branch=branch, created=True)


def _branch_name(research_run_id: str, experiment_id: str) -> str:
    return f"research/{research_run_id}/{experiment_id}"[:120]


def _seed_snapshot(seed_worktree: Path) -> GitSnapshot:
    try:
        return git_snapshot(seed_worktree)
    except ValueError as exc:
        raise ExperimentWorktreeError(
            f"Could not inspect seed Worktree {seed_worktree}: {exc}"
        ) from exc


def _copy_seed_changes(
    seed_worktree: Path,
    target_worktree: Path,
    changed_files: list[str],
) -> None:
    for changed_file in changed_files:
        source = seed_worktree / changed_file
        target = target_worktree / changed_file
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif target.exists() or target.is_symlink():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


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
