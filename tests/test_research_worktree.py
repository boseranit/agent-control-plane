from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller.worktree import (
    ExperimentWorktreeError,
    prepare_experiment_worktree,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_prepare_experiment_worktree_creates_scoped_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)

    worktree = prepare_experiment_worktree(
        target_repository=repo,
        worktree_root=tmp_path / ".worktrees",
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )

    assert worktree.path == (tmp_path / ".worktrees" / "run-1" / "EXP-0001")
    assert worktree.path.is_dir()
    assert worktree.created is True
    assert worktree.branch == "research/run-1/EXP-0001"


def test_prepare_experiment_worktree_rejects_dirty_existing_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    worktree = prepare_experiment_worktree(
        target_repository=repo,
        worktree_root=tmp_path / ".worktrees",
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )
    (worktree.path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ExperimentWorktreeError, match="dirty"):
        prepare_experiment_worktree(
            target_repository=repo,
            worktree_root=tmp_path / ".worktrees",
            research_run_id="run-1",
            experiment_id="EXP-0001",
        )

    assert (worktree.path / "dirty.txt").exists()
