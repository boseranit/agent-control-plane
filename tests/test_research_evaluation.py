from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.control_plane.boundary_audit import git_snapshot
from agent_control_plane.control_plane.json_artifacts import (
    file_sha256,
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.evaluation import (
    EvaluationBoundaryError,
    create_evaluator_workspace,
    run_evaluation_boundary_audit,
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


def test_create_evaluator_workspace_writes_manifest_without_eval_inputs(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    experiment_design = experiment_dir / "experiment_design.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    experiment_design.write_text('{"confirmatory_commands": []}\n', encoding="utf-8")

    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={
            "selected_plan": selected_plan,
            "experiment_design": experiment_design,
        },
        locked_artifacts=[selected_plan, experiment_design],
        confirmatory_commands=[{"name": "eval", "argv": ["python", "eval.py"]}],
        exploratory_commands=[{"name": "diag", "argv": ["python", "diag.py"]}],
    )

    manifest = read_json_object(workspace.manifest_path)
    child_names = {child.name for child in workspace.path.iterdir()}

    assert workspace.path == experiment_dir / "evaluation"
    assert child_names == {"manifest.json", "eval_scratch", "eval_outputs"}
    assert manifest["experiment_dir"] == str(experiment_dir.resolve())
    assert manifest["worktree"] == str(repo.resolve())
    assert manifest["worktree_path"] == str(repo.resolve())
    assert manifest["data_root"] == str((tmp_path / "data").resolve())
    assert manifest["git_sha"] == "abc123"
    assert manifest["canonical_artifacts"] == {
        "experiment_design": str(experiment_design.resolve()),
        "selected_plan": str(selected_plan.resolve()),
    }
    assert manifest["commands"]["confirmatory"][0]["name"] == "eval"
    assert manifest["commands"]["exploratory"][0]["name"] == "diag"
    assert set(manifest["locked_artifact_hashes"]) == {
        str(selected_plan.resolve()),
        str(experiment_design.resolve()),
    }
    assert manifest["confirmatory_commands"][0]["name"] == "eval"
    assert manifest["exploratory_commands"][0]["name"] == "diag"
    assert not (experiment_dir / "evaluation_boundary_evidence.json").exists()


def test_evaluation_boundary_audit_rejects_path_mode(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    with pytest.raises(TypeError, match="controller-held"):
        run_evaluation_boundary_audit(workspace.manifest_path)


def test_evaluation_boundary_audit_detects_locked_artifact_hash_change(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    selected_plan.write_text('{"selected": false}\n', encoding="utf-8")

    with pytest.raises(EvaluationBoundaryError, match="Locked artifact"):
        run_evaluation_boundary_audit(workspace)


def test_evaluation_boundary_audit_ignores_tampered_manifest_hashes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    selected_plan.write_text('{"selected": false}\n', encoding="utf-8")
    manifest = read_json_object(workspace.manifest_path)
    manifest["locked_artifact_hashes"][str(selected_plan.resolve())] = file_sha256(
        selected_plan
    )
    write_json(workspace.manifest_path, manifest)

    with pytest.raises(EvaluationBoundaryError, match="Locked artifact"):
        run_evaluation_boundary_audit(workspace)


def test_evaluation_boundary_audit_ignores_tampered_manifest_worktree_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    after = git_snapshot(repo)
    manifest = read_json_object(workspace.manifest_path)
    manifest["pre_evaluation_worktree"] = {
        "status_porcelain": after.status_porcelain,
        "diff": after.diff,
        "changed_files": after.changed_files,
        "dirty_content_state": after.dirty_content_state,
        "head": after.head,
        "head_tree": after.head_tree,
    }
    write_json(workspace.manifest_path, manifest)

    with pytest.raises(EvaluationBoundaryError, match="Worktree state changed"):
        run_evaluation_boundary_audit(workspace)


def test_evaluation_boundary_audit_detects_worktree_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(EvaluationBoundaryError, match="Worktree state changed"):
        run_evaluation_boundary_audit(workspace)


def test_evaluation_boundary_audit_detects_ignored_worktree_file(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / ".gitignore").write_text("*.cache\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "ignore cache"], cwd=repo, check=True)
    experiment_dir = tmp_path / "run" / "experiments" / "EXP-0001"
    experiment_dir.mkdir(parents=True)
    selected_plan = experiment_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_dir=experiment_dir,
        worktree_path=repo,
        data_root=tmp_path / "data",
        git_sha="abc123",
        canonical_artifacts={"selected_plan": selected_plan},
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )

    (repo / "evaluation.cache").write_text("ignored\n", encoding="utf-8")

    with pytest.raises(EvaluationBoundaryError, match="evaluation.cache"):
        run_evaluation_boundary_audit(workspace)
