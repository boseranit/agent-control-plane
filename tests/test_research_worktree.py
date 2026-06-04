from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
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
    paths = ResearchProgramPaths(tmp_path / "programs" / "run-1")
    init_repo(repo)

    worktree = prepare_experiment_worktree(
        target_repository=repo,
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )

    assert worktree.path == paths.worktree_directory("run-1", "EXP-0001")
    assert worktree.path.is_dir()
    assert worktree.created is True
    assert worktree.branch == "research/run-1/EXP-0001"


def test_program_root_can_live_outside_target_repository(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    program_root = tmp_path / "programs" / "peer-residuals"
    paths = ResearchProgramPaths(program_root)
    init_repo(repo)

    worktree = prepare_experiment_worktree(
        target_repository=repo,
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )

    assert worktree.path == program_root / "worktrees" / "run-1" / "EXP-0001"
    assert worktree.path.is_dir()
    assert repo not in worktree.path.parents


def test_prepare_experiment_worktree_seeds_prior_dirty_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    paths = ResearchProgramPaths(tmp_path / "programs" / "run-1")
    init_repo(repo)
    seed = prepare_experiment_worktree(
        target_repository=repo,
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0000",
    )
    (seed.path / "research").mkdir()
    (seed.path / "research" / "base.py").write_text(
        "VALUE = 'committed seed'\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "research/base.py"],
        cwd=seed.path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed base"],
        cwd=seed.path,
        check=True,
        capture_output=True,
    )
    (seed.path / "README.md").write_text("seeded\n", encoding="utf-8")
    (seed.path / "research" / "candidate.py").write_text(
        "VALUE = 'seeded'\n",
        encoding="utf-8",
    )

    worktree = prepare_experiment_worktree(
        target_repository=repo,
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
        seed_worktree=seed.path,
    )

    assert (worktree.path / "research" / "base.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 'committed seed'\n"
    assert (worktree.path / "README.md").read_text(encoding="utf-8") == "seeded\n"
    assert (worktree.path / "research" / "candidate.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 'seeded'\n"


def test_prepare_experiment_worktree_rejects_dirty_existing_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    paths = ResearchProgramPaths(tmp_path / "programs" / "run-1")
    init_repo(repo)
    worktree = prepare_experiment_worktree(
        target_repository=repo,
        paths=paths,
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )
    (worktree.path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ExperimentWorktreeError, match="dirty"):
        prepare_experiment_worktree(
            target_repository=repo,
            paths=paths,
            research_run_id="run-1",
            experiment_id="EXP-0001",
        )

    assert (worktree.path / "dirty.txt").exists()
