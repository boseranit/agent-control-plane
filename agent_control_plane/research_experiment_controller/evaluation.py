from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from agent_control_plane.control_plane.boundary_audit import (
    GitSnapshot,
    assert_git_snapshot_unchanged,
    git_snapshot,
    verify_hash_manifest,
)
from agent_control_plane.control_plane.json_artifacts import (
    file_sha256,
    write_json,
)


class EvaluationBoundaryError(RuntimeError):
    """Raised when evaluation mutates locked inputs or the Experiment Worktree."""


@dataclass(frozen=True)
class EvaluationBoundaryEvidence:
    worktree_path: Path
    locked_artifact_hashes: dict[str, str]
    pre_evaluation_worktree: GitSnapshot


@dataclass(frozen=True)
class EvaluatorWorkspace:
    path: Path
    manifest_path: Path
    boundary_evidence: EvaluationBoundaryEvidence


def create_evaluator_workspace(
    *,
    experiment_dir: str | Path,
    worktree_path: str | Path,
    data_root: str | Path,
    git_sha: str,
    canonical_artifacts: Mapping[str, str | Path],
    locked_artifacts: Sequence[str | Path],
    confirmatory_commands: Sequence[Mapping[str, Any]],
    exploratory_commands: Sequence[Mapping[str, Any]] = (),
) -> EvaluatorWorkspace:
    resolved_experiment_dir = Path(experiment_dir).resolve()
    resolved_worktree = Path(worktree_path).resolve()
    workspace = resolved_experiment_dir / "evaluation"
    scratch = workspace / "eval_scratch"
    outputs = workspace / "eval_outputs"
    scratch.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)

    before = git_snapshot(resolved_worktree)
    locked_artifact_hashes = {
        str(Path(path).resolve()): file_sha256(path)
        for path in sorted(locked_artifacts, key=lambda item: str(item))
    }
    boundary_evidence = EvaluationBoundaryEvidence(
        worktree_path=resolved_worktree,
        locked_artifact_hashes=locked_artifact_hashes,
        pre_evaluation_worktree=before,
    )
    manifest_path = workspace / "manifest.json"
    write_json(
        manifest_path,
        {
            "experiment_dir": str(resolved_experiment_dir),
            "worktree_path": str(resolved_worktree),
            "data_root": str(Path(data_root).expanduser().resolve()),
            "git_sha": git_sha,
            "canonical_artifacts": {
                name: str(Path(path).resolve())
                for name, path in sorted(canonical_artifacts.items())
            },
            "locked_artifact_hashes": locked_artifact_hashes,
            "commands": {
                "confirmatory": [dict(command) for command in confirmatory_commands],
                "exploratory": [dict(command) for command in exploratory_commands],
            },
            "eval_scratch": str(scratch.resolve()),
            "eval_outputs": str(outputs.resolve()),
        },
    )
    return EvaluatorWorkspace(
        path=workspace,
        manifest_path=manifest_path,
        boundary_evidence=boundary_evidence,
    )


def run_evaluation_boundary_audit(
    evidence: EvaluationBoundaryEvidence | EvaluatorWorkspace,
) -> None:
    boundary_evidence = _boundary_evidence(evidence)
    try:
        verify_hash_manifest(boundary_evidence.locked_artifact_hashes)
        assert_git_snapshot_unchanged(
            boundary_evidence.pre_evaluation_worktree,
            git_snapshot(boundary_evidence.worktree_path),
        )
    except ValueError as exc:
        raise EvaluationBoundaryError(str(exc)) from exc


def _boundary_evidence(
    evidence: EvaluationBoundaryEvidence | EvaluatorWorkspace,
) -> EvaluationBoundaryEvidence:
    if isinstance(evidence, EvaluationBoundaryEvidence):
        return evidence
    if isinstance(evidence, EvaluatorWorkspace):
        return evidence.boundary_evidence
    raise TypeError(
        "Evaluation Boundary Audit requires controller-held evidence, not a path."
    )
