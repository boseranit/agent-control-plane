from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_control_plane.research_experiment_controller.research_run_spec import (
    ResearchRunSpecError,
    load_research_run_spec,
    resolved_spec_dict,
)

DELETE = object()


def write_prd_spec(tmp_path: Path, repo: Path) -> Path:
    path = tmp_path / "research-run.yaml"
    path.write_text(
        f"""
version: 1
research_run_id: peer-residual-v1
target_repository: {repo}
max_experiments: 5

research_brief: |
  Test peer residual forecasting.

budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
  research:
    month_start: "2020-01"
    month_end: "2026-01"
    max_runtime_minutes: 240

data_root: /mnt/redbackup/data

worktree:
  create: true
  root: .worktrees

mlflow:
  enabled: true
  tracking_uri: file:/tmp/mlruns
  experiment_name: peer-residual-v1

codex:
  model: gpt-5.3-codex
  effort: xhigh

implementation:
  max_repairs: 3

stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return path


def minimal_spec_data(repo: Path) -> dict[str, Any]:
    return {
        "research_run_id": "peer-residual-v1",
        "target_repository": str(repo),
        "research_brief": "Test peer residual forecasting.\n",
        "budget": "smoke",
        "budgets": {
            "smoke": {
                "month_start": "2026-01",
                "month_end": "2026-01",
                "max_runtime_minutes": 5,
            }
        },
        "data_root": "/mnt/redbackup/data",
    }


def write_spec_data(tmp_path: Path, data: dict[str, Any], name: str) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return path


def patch_spec_data(data: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if value is DELETE:
            data.pop(key, None)
        elif isinstance(value, dict) and isinstance(data.get(key), dict):
            patch_spec_data(data[key], value)
        else:
            data[key] = value


def write_minimal_spec(tmp_path: Path, repo: Path) -> Path:
    path = tmp_path / "minimal-research-run.yaml"
    path.write_text(
        f"""
research_run_id: peer-residual-v1
target_repository: {repo}
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: /mnt/redbackup/data
stop_on_prerequisites_failed: false
""",
        encoding="utf-8",
    )
    return path


def test_loads_prd_minimal_research_run_spec(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    spec = load_research_run_spec(write_prd_spec(tmp_path, repo))

    assert spec.version == 1
    assert spec.research_run_id == "peer-residual-v1"
    assert spec.target_repository == repo.resolve()
    assert spec.max_experiments == 5
    assert spec.research_brief.strip() == "Test peer residual forecasting."
    assert spec.budget == "smoke"
    assert spec.data_root == Path("/mnt/redbackup/data")
    assert spec.worktree.create is True
    assert spec.worktree.root == Path(".worktrees")
    assert spec.mlflow.enabled is True
    assert spec.mlflow.tracking_uri == "file:/tmp/mlruns"
    assert spec.mlflow.experiment_name == "peer-residual-v1"
    assert spec.codex.model == "gpt-5.3-codex"
    assert spec.codex.effort == "xhigh"
    assert spec.implementation.max_repairs == 3
    assert spec.stop_on_prerequisites_failed is True


def test_exposes_selected_budget_with_default_command_timeout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    spec = load_research_run_spec(write_prd_spec(tmp_path, repo))

    assert spec.selected_budget.month_start == "2026-01"
    assert spec.selected_budget.month_end == "2026-01"
    assert spec.selected_budget.max_runtime_minutes == 5
    assert spec.selected_budget.default_command_timeout_seconds == 300


def test_applies_defaults_and_accepts_stop_on_prerequisites_failed_false(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    spec = load_research_run_spec(write_minimal_spec(tmp_path, repo))

    assert spec.version == 1
    assert spec.max_experiments == 1
    assert spec.worktree.create is True
    assert spec.worktree.root == Path(".worktrees")
    assert spec.mlflow.enabled is False
    assert spec.mlflow.tracking_uri is None
    assert spec.mlflow.experiment_name is None
    assert spec.codex.model is None
    assert spec.codex.effort is None
    assert spec.implementation.max_repairs == 3
    assert spec.stop_on_prerequisites_failed is False


@pytest.mark.parametrize(
    ("name", "patch", "match"),
    [
        (
            "missing_research_run_id",
            {"research_run_id": DELETE},
            "research_run_id.*required",
        ),
        (
            "missing_target_repository",
            {"target_repository": DELETE},
            "target_repository.*required",
        ),
        (
            "missing_research_brief",
            {"research_brief": DELETE},
            "research_brief.*required",
        ),
        ("missing_data_root", {"data_root": DELETE}, "data_root.*required"),
        ("missing_budget", {"budget": DELETE}, "budget.*required"),
        ("missing_selected_budget", {"budget": "missing"}, "selected budget"),
        ("budgets_not_mapping", {"budgets": []}, "budgets.*mapping"),
        (
            "budget_entry_not_mapping",
            {"budgets": {"smoke": []}},
            "Budget 'smoke'.*mapping",
        ),
        (
            "max_experiments_not_positive",
            {"max_experiments": 0},
            "max_experiments.*positive",
        ),
        (
            "budget_runtime_not_positive",
            {"budgets": {"smoke": {"max_runtime_minutes": 0}}},
            "max_runtime_minutes.*positive",
        ),
        (
            "implementation_repairs_not_positive",
            {"implementation": {"max_repairs": 0}},
            "max_repairs.*positive",
        ),
        ("unsupported_version", {"version": 2}, "version.*1"),
        ("worktree_not_mapping", {"worktree": []}, "worktree.*mapping"),
        ("mlflow_not_mapping", {"mlflow": []}, "mlflow.*mapping"),
        ("codex_not_mapping", {"codex": []}, "codex.*mapping"),
        (
            "implementation_not_mapping",
            {"implementation": []},
            "implementation.*mapping",
        ),
        (
            "worktree_create_not_bool",
            {"worktree": {"create": "false"}},
            "worktree.create.*boolean",
        ),
        (
            "worktree_root_not_string",
            {"worktree": {"root": None}},
            "worktree.root.*string",
        ),
        (
            "mlflow_enabled_not_bool",
            {"mlflow": {"enabled": "false"}},
            "mlflow.enabled.*boolean",
        ),
        (
            "stop_on_prerequisites_failed_not_bool",
            {"stop_on_prerequisites_failed": "false"},
            "stop_on_prerequisites_failed.*boolean",
        ),
    ],
)
def test_rejects_invalid_research_run_specs(
    tmp_path: Path, name: str, patch: dict[str, Any], match: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    data = minimal_spec_data(repo)
    patch_spec_data(data, patch)

    with pytest.raises(ResearchRunSpecError, match=match):
        load_research_run_spec(write_spec_data(tmp_path, data, name))


def test_resolved_spec_dict_is_deterministic_snapshot_data(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    data = minimal_spec_data(repo)
    data["budgets"]["research"] = {
        "month_start": "2020-01",
        "month_end": "2026-01",
        "max_runtime_minutes": 240,
    }
    spec = load_research_run_spec(write_spec_data(tmp_path, data, "snapshot-source"))

    resolved = resolved_spec_dict(spec)

    assert resolved["version"] == 1
    assert resolved["research_run_id"] == "peer-residual-v1"
    assert resolved["target_repository"] == str(repo.resolve())
    assert resolved["max_experiments"] == 1
    assert resolved["research_brief"] == "Test peer residual forecasting.\n"
    assert resolved["budget"] == "smoke"
    assert list(resolved["budgets"]) == ["research", "smoke"]
    assert resolved["data_root"] == "/mnt/redbackup/data"
    assert resolved["worktree"] == {"create": True, "root": ".worktrees"}
    assert resolved["mlflow"] == {
        "enabled": False,
        "tracking_uri": None,
        "experiment_name": None,
    }
    assert resolved["codex"] == {"model": None, "effort": None}
    assert resolved["implementation"] == {"max_repairs": 3}
    assert resolved["stop_on_prerequisites_failed"] is True
    assert "source_path" not in resolved
    assert "selected_budget" not in resolved

    snapshot_path = tmp_path / "resolved.yaml"
    snapshot_path.write_text(
        yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8"
    )

    reloaded = load_research_run_spec(snapshot_path)

    assert resolved_spec_dict(reloaded) == resolved


def test_ignores_nonessential_unknown_research_run_spec_fields(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    data = minimal_spec_data(repo)
    data["commands"] = []
    data["eval_inputs"] = []
    data["service_tier"] = "flex"
    data["dependencies"] = []

    spec = load_research_run_spec(write_spec_data(tmp_path, data, "unknown-fields"))

    assert spec.research_run_id == "peer-residual-v1"
    assert spec.budget == "smoke"
