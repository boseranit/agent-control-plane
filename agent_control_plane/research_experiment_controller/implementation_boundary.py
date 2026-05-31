from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from agent_control_plane.control_plane.boundary_audit import assert_allowed_paths
from agent_control_plane.research_experiment_controller.artifacts import (
    ImplementationDiffSummary,
    Summary,
)
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_run_failed,
)


@dataclass(frozen=True)
class ImplementationBoundaryAudit:
    diff_summary: ImplementationDiffSummary
    failure_summary: Summary | None = None


def audit_implementation_paths(
    *,
    changed_files: list[str],
    allowed_write_paths: list[str],
) -> ImplementationBoundaryAudit:
    try:
        assert_allowed_paths(changed_files, allowed_write_paths)
    except ValueError as exc:
        try:
            outside_paths = _outside_allowed_paths(changed_files, allowed_write_paths)
        except ValueError:
            outside_paths = changed_files
        return ImplementationBoundaryAudit(
            diff_summary=ImplementationDiffSummary(
                changed_files=changed_files,
                allowed_path_violations=outside_paths or changed_files,
                high_risk=True,
                notes=[str(exc)],
            ),
            failure_summary=classify_run_failed(
                str(exc),
                failed_stage="implementation_boundary_audit",
                failure_classification="allowed_path_violation",
            ),
        )
    return ImplementationBoundaryAudit(
        diff_summary=ImplementationDiffSummary(
            changed_files=changed_files,
            notes=["Changed files are within allowed write paths."],
        ),
    )


def _outside_allowed_paths(
    changed_files: Iterable[str | Path],
    allowed_write_paths: Iterable[str | Path],
) -> list[str]:
    normalized_allowed_paths = [
        _normalize_repo_relative_path(path) for path in allowed_write_paths
    ]
    return [
        path
        for path in (_normalize_repo_relative_path(path) for path in changed_files)
        if not any(
            _path_is_allowed(path, allowed) for allowed in normalized_allowed_paths
        )
    ]


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
