from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

from agent_control_plane.control_plane.json_artifacts import file_sha256


@dataclass(frozen=True)
class GitSnapshot:
    repo: Path
    status_porcelain: str
    diff: str
    changed_files: list[str]
    dirty_content_state: dict[str, dict[str, str | None]] = field(default_factory=dict)
    head: str | None = None
    head_tree: str | None = None

    @property
    def repository(self) -> str:
        return str(self.repo)

    @property
    def status(self) -> str:
        return self.status_porcelain


def git_snapshot(repo: str | Path) -> GitSnapshot:
    resolved_repo = Path(repo).resolve()
    status_porcelain = _git_output(
        resolved_repo,
        ["status", "--porcelain=v1", "--untracked-files=all"],
    )
    status_porcelain_z = _git_output(
        resolved_repo,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    diff = _git_output(resolved_repo, ["diff", "--", "."])
    changed_files = _changed_files_from_status_z(status_porcelain_z)
    return GitSnapshot(
        repo=resolved_repo,
        status_porcelain=status_porcelain,
        diff=diff,
        changed_files=changed_files,
        head=_git_output_or_none(resolved_repo, ["rev-parse", "--verify", "HEAD"]),
        head_tree=_git_output_or_none(
            resolved_repo,
            ["rev-parse", "--verify", "HEAD^{tree}"],
        ),
        dirty_content_state=_dirty_content_state(resolved_repo, changed_files),
    )


def assert_git_snapshot_unchanged(before: GitSnapshot, after: GitSnapshot) -> None:
    if before.repo != after.repo:
        raise ValueError(
            f"Cannot compare snapshots from different repos: {before.repo}, {after.repo}"
        )
    if (
        before.status_porcelain == after.status_porcelain
        and before.diff == after.diff
        and before.head == after.head
        and before.head_tree == after.head_tree
        and before.dirty_content_state == after.dirty_content_state
    ):
        return

    changed_files = sorted(set(before.changed_files) | set(after.changed_files))
    changed_detail = (
        ", ".join(changed_files) if changed_files else "repository content changed"
    )
    raise ValueError(f"Worktree state changed in {after.repo}: {changed_detail}")


def assert_allowed_paths(
    changed_files: Iterable[str | Path],
    allowed_paths: Iterable[str | Path],
) -> None:
    normalized_allowed_paths = [
        _normalize_repo_relative_path(path) for path in allowed_paths
    ]
    outside_paths = [
        path
        for path in (_normalize_repo_relative_path(path) for path in changed_files)
        if not any(
            _path_is_allowed(path, allowed) for allowed in normalized_allowed_paths
        )
    ]
    if outside_paths:
        raise ValueError(
            f"Changed files outside allowed paths: {', '.join(outside_paths)}"
        )


def hash_manifest(paths: Iterable[str | Path]) -> dict[str, str]:
    resolved_paths = sorted(Path(path).resolve() for path in paths)
    return {str(path): file_sha256(path) for path in resolved_paths}


def verify_hash_manifest(manifest: Mapping[str, str]) -> None:
    for path_string, expected_hash in manifest.items():
        path = Path(path_string)
        if not path.exists():
            raise ValueError(f"Missing file in hash manifest: {path}")
        actual_hash = file_sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Locked artifact hash changed: {path}; "
                f"expected {expected_hash}, got {actual_hash}"
            )


def _git_output(repo: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Git command failed in {repo}: {exc.stderr.strip()}") from exc
    return result.stdout


def _git_output_or_none(repo: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _changed_files_from_status_z(status_porcelain_z: str) -> list[str]:
    changed_files: list[str] = []
    entries = status_porcelain_z.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            raise ValueError(f"Malformed git status entry: {entry}")

        status_code = entry[:2]
        changed_files.append(entry[3:])
        if "R" in status_code or "C" in status_code:
            if index >= len(entries) or not entries[index]:
                raise ValueError(f"Malformed git rename/copy status entry: {entry}")
            changed_files.append(entries[index])
            index += 1

    return changed_files


def _dirty_content_state(
    repo: Path,
    changed_files: Iterable[str],
) -> dict[str, dict[str, str | None]]:
    return {
        changed_file: {
            "index_blob": _index_blob(repo, changed_file),
            "worktree_sha256": _worktree_sha256(repo, changed_file),
        }
        for changed_file in sorted(changed_files)
    }


def _index_blob(repo: Path, changed_file: str) -> str | None:
    output = _git_output(repo, ["ls-files", "-s", "--", changed_file])
    first_line = output.splitlines()[0] if output else ""
    if not first_line:
        return None
    fields = first_line.split()
    return fields[1] if len(fields) >= 2 else None


def _worktree_sha256(repo: Path, changed_file: str) -> str | None:
    path = repo / changed_file
    if not path.is_file():
        return None
    return file_sha256(path)


def _normalize_repo_relative_path(path: str | Path) -> str:
    path_text = path.as_posix() if isinstance(path, Path) else str(path)
    posix_path = PurePosixPath(path_text)
    windows_path = PureWindowsPath(path_text)
    if posix_path.is_absolute() or windows_path.is_absolute():
        raise ValueError(f"Path must be repo-relative: {path_text}")
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise ValueError(f"Path must not contain '..': {path_text}")
    return posix_path.as_posix()


def _path_is_allowed(changed_path: str, allowed_path: str) -> bool:
    return (
        allowed_path == "."
        or changed_path == allowed_path
        or changed_path.startswith(f"{allowed_path}/")
    )
