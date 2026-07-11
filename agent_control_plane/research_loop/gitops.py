from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

_CACHE_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})


class DirtyRepositoryError(RuntimeError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(f"repository has uncommitted changes: {', '.join(paths)}")


class BoundaryViolation(RuntimeError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(f"changed paths outside allowed boundary: {', '.join(paths)}")


class CommitFailedError(RuntimeError):
    def __init__(self, *, message: str, stdout: str, stderr: str) -> None:
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr or stdout or "git commit failed"
        super().__init__(detail)


def changed_files(repo: Path) -> list[str]:
    out = _git_output(repo, "status", "--porcelain", "--untracked-files=all")
    changed: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        entry = line[3:] if len(line) > 3 else line.strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip()
        if entry.startswith('"') and entry.endswith('"'):
            entry = entry[1:-1]
        if entry and not _is_cache_path(entry):
            changed.add(entry)
    return sorted(changed)


def assert_changes_within(repo: Path, prefix: str) -> None:
    outside = [path for path in changed_files(repo) if not path.startswith(prefix)]
    if outside:
        raise BoundaryViolation(outside)


def commit_all(repo: Path, message: str) -> str:
    _git_output(repo, "add", "-A")
    try:
        _git_output(repo, "commit", "-m", message)
    except subprocess.CalledProcessError as exc:
        raise CommitFailedError(
            message=message,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        ) from exc
    return head_sha(repo)


def reset_hard_and_clean(repo: Path) -> None:
    _git_output(repo, "reset", "--hard")
    _git_output(repo, "clean", "-fd")

def head_sha(repo: Path) -> str:
    return _git_output(repo, "rev-parse", "HEAD").strip()


def _git_output(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        env=_git_env(),
    )
    return completed.stdout


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{count}"] = "filter.nbstripout.clean"
    env[f"GIT_CONFIG_VALUE_{count}"] = "cat"
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _is_cache_path(path: str) -> bool:
    return any(part in _CACHE_DIR_NAMES for part in PurePosixPath(path).parts)