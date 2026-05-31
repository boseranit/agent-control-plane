from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.control_plane.boundary_audit import (
    assert_allowed_paths,
    assert_git_snapshot_unchanged,
    git_snapshot,
    hash_manifest,
    verify_hash_manifest,
)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def commit_file(repo: Path, relative_path: str, text: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {relative_path}"], cwd=repo, check=True
    )


def test_git_snapshot_detects_modified_tracked_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "tracked.txt", "before\n")

    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")

    snapshot = git_snapshot(repo)

    assert snapshot.repo == repo.resolve()
    assert snapshot.repository == str(repo.resolve())
    assert snapshot.status_porcelain == " M tracked.txt\n"
    assert snapshot.status == " M tracked.txt\n"
    assert "tracked.txt" in snapshot.diff
    assert snapshot.changed_files == ["tracked.txt"]


def test_snapshot_compare_detects_phase_mutation_with_existing_dirty_state(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "tracked.txt", "before\n")
    (repo / "existing.log").write_text("already dirty\n", encoding="utf-8")
    before = git_snapshot(repo)

    assert_git_snapshot_unchanged(before, git_snapshot(repo))

    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tracked.txt"):
        assert_git_snapshot_unchanged(before, git_snapshot(repo))


def test_snapshot_compare_detects_existing_untracked_file_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "tracked.txt", "tracked\n")
    (repo / "scratch.txt").write_text("first\n", encoding="utf-8")
    before = git_snapshot(repo)

    assert_git_snapshot_unchanged(before, git_snapshot(repo))

    (repo / "scratch.txt").write_text("second\n", encoding="utf-8")

    with pytest.raises(ValueError, match="scratch.txt"):
        assert_git_snapshot_unchanged(before, git_snapshot(repo))


def test_snapshot_compare_detects_ignored_file_created_after_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, ".gitignore", "*.cache\n")
    before = git_snapshot(repo)

    (repo / "evaluation.cache").write_text("ignored\n", encoding="utf-8")

    with pytest.raises(ValueError, match="evaluation.cache"):
        assert_git_snapshot_unchanged(before, git_snapshot(repo))


def test_snapshot_compare_detects_staged_file_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "tracked.txt", "tracked\n")
    (repo / "tracked.txt").write_text("staged first\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    before = git_snapshot(repo)

    assert_git_snapshot_unchanged(before, git_snapshot(repo))

    (repo / "tracked.txt").write_text("staged second\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)

    with pytest.raises(ValueError, match="tracked.txt"):
        assert_git_snapshot_unchanged(before, git_snapshot(repo))


def test_snapshot_compare_detects_committed_phase_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "tracked.txt", "tracked\n")
    before = git_snapshot(repo)

    assert_git_snapshot_unchanged(before, git_snapshot(repo))

    (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "mutate tracked"], cwd=repo, check=True)

    with pytest.raises(ValueError, match="repository content"):
        assert_git_snapshot_unchanged(before, git_snapshot(repo))


def test_allowlist_accepts_nested_paths_and_reports_outside_paths() -> None:
    assert_allowed_paths(
        ["src/package/module.py", "docs/readme.md"],
        ["src/package", "docs/readme.md"],
    )

    with pytest.raises(ValueError, match="outside.py"):
        assert_allowed_paths(
            ["src/package/module.py", "outside.py"],
            ["src/package"],
        )


def test_allowlist_rejects_staged_rename_across_allowed_boundary(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    commit_file(repo, "allowed/a.txt", "a\n")

    (repo / "outside").mkdir()
    subprocess.run(
        ["git", "mv", "allowed/a.txt", "outside/a.txt"], cwd=repo, check=True
    )

    with pytest.raises(ValueError, match="outside/a.txt"):
        assert_allowed_paths(git_snapshot(repo).changed_files, ["allowed"])


@pytest.mark.parametrize(
    "changed_files, allowed_paths",
    [
        (["../secret.py"], ["src"]),
        (["/tmp/secret.py"], ["src"]),
        (["src/file.py"], ["../src"]),
        (["src/file.py"], ["/tmp/src"]),
    ],
)
def test_allowlist_rejects_unsafe_paths(
    changed_files: list[str],
    allowed_paths: list[str],
) -> None:
    with pytest.raises(ValueError):
        assert_allowed_paths(changed_files, allowed_paths)


def test_hash_manifest_verifies_locked_artifact_and_fails_after_mutation(
    tmp_path: Path,
) -> None:
    first = tmp_path / "locked-a.json"
    second = tmp_path / "locked-b.json"
    first.write_text('{"a": 1}\n', encoding="utf-8")
    second.write_text('{"b": 2}\n', encoding="utf-8")

    manifest = hash_manifest([second, first])

    assert list(manifest) == [str(first.resolve()), str(second.resolve())]
    verify_hash_manifest(manifest)

    first.write_text('{"a": 2}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=f"hash changed.*{first.resolve()}"):
        verify_hash_manifest(manifest)

    first.unlink()

    with pytest.raises(ValueError, match=f"Missing file.*{first.resolve()}"):
        verify_hash_manifest(manifest)
