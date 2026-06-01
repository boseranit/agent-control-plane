from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ResearchBudget:
    month_start: str
    month_end: str
    max_runtime_minutes: int

    @property
    def default_command_timeout_seconds(self) -> int:
        return self.max_runtime_minutes * 60


@dataclass(frozen=True)
class WorktreeConfig:
    create: bool = True
    root: Path = Path(".worktrees")


@dataclass(frozen=True)
class MLflowConfig:
    enabled: bool = False
    tracking_uri: str | None = None
    experiment_name: str | None = None


@dataclass(frozen=True)
class CodexConfig:
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class ImplementationConfig:
    max_repairs: int = 3


@dataclass(frozen=True)
class ResearchRunSpec:
    source_path: Path
    version: int
    research_run_id: str
    target_repository: Path
    max_experiments: int
    research_brief: str
    budget: str
    budgets: dict[str, ResearchBudget]
    selected_budget: ResearchBudget
    data_root: Path
    worktree: WorktreeConfig
    mlflow: MLflowConfig
    codex: CodexConfig
    implementation: ImplementationConfig
    stop_on_prerequisites_failed: bool


class ResearchRunSpecError(ValueError):
    """Raised when a Research Run Spec cannot be loaded."""


def load_research_run_spec(path: str | Path) -> ResearchRunSpec:
    source_path = Path(path)
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ResearchRunSpecError("Research Run Spec must be a mapping.")

    budgets = _load_budgets(data.get("budgets"))
    budget_name = _required_string(data, "budget")
    selected_budget = budgets.get(budget_name)
    if selected_budget is None:
        raise ResearchRunSpecError(
            f"Research Run Spec selected budget is missing: {budget_name}"
        )
    version = _positive_int(data, "version", 1)
    if version != 1:
        raise ResearchRunSpecError("Research Run Spec field 'version' must be 1.")

    return ResearchRunSpec(
        source_path=source_path.resolve(),
        version=version,
        research_run_id=_required_string(data, "research_run_id"),
        target_repository=Path(_required_string(data, "target_repository"))
        .expanduser()
        .resolve(),
        max_experiments=_positive_int(data, "max_experiments", 1),
        research_brief=_required_string(data, "research_brief"),
        budget=budget_name,
        budgets=budgets,
        selected_budget=selected_budget,
        data_root=Path(_required_string(data, "data_root")).expanduser(),
        worktree=_load_worktree(data.get("worktree")),
        mlflow=_load_mlflow(data.get("mlflow")),
        codex=_load_codex(data.get("codex")),
        implementation=_load_implementation(data.get("implementation")),
        stop_on_prerequisites_failed=_optional_bool(
            data, "stop_on_prerequisites_failed", True
        ),
    )


def resolved_spec_dict(spec: ResearchRunSpec) -> dict[str, Any]:
    return {
        "version": spec.version,
        "research_run_id": spec.research_run_id,
        "target_repository": str(spec.target_repository),
        "max_experiments": spec.max_experiments,
        "research_brief": spec.research_brief,
        "budget": spec.budget,
        "budgets": {
            name: {
                "month_start": budget.month_start,
                "month_end": budget.month_end,
                "max_runtime_minutes": budget.max_runtime_minutes,
            }
            for name, budget in (
                (name, spec.budgets[name]) for name in sorted(spec.budgets)
            )
        },
        "data_root": str(spec.data_root),
        "worktree": {
            "create": spec.worktree.create,
            "root": str(spec.worktree.root),
        },
        "mlflow": {
            "enabled": spec.mlflow.enabled,
            "tracking_uri": spec.mlflow.tracking_uri,
            "experiment_name": spec.mlflow.experiment_name,
        },
        "codex": {
            "model": spec.codex.model,
            "effort": spec.codex.effort,
        },
        "implementation": {
            "max_repairs": spec.implementation.max_repairs,
        },
        "stop_on_prerequisites_failed": spec.stop_on_prerequisites_failed,
    }


def _load_budgets(value: Any) -> dict[str, ResearchBudget]:
    if not isinstance(value, dict) or not value:
        raise ResearchRunSpecError(
            "Research Run Spec field 'budgets' must be a non-empty mapping."
        )
    budgets: dict[str, ResearchBudget] = {}
    for name, item in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ResearchRunSpecError(
                "Research Budget names must be non-empty strings."
            )
        if not isinstance(item, dict):
            raise ResearchRunSpecError(f"Research Budget '{name}' must be a mapping.")
        budgets[name] = ResearchBudget(
            month_start=_required_string(item, "month_start"),
            month_end=_required_string(item, "month_end"),
            max_runtime_minutes=_positive_int(item, "max_runtime_minutes", 1),
        )
    return budgets


def _load_worktree(value: Any) -> WorktreeConfig:
    data = _optional_mapping(value, "worktree")
    return WorktreeConfig(
        create=_optional_bool(data, "create", True, "worktree.create"),
        root=Path(_optional_string(data, "root", ".worktrees", "worktree.root")),
    )


def _load_mlflow(value: Any) -> MLflowConfig:
    data = _optional_mapping(value, "mlflow")
    return MLflowConfig(
        enabled=_optional_bool(data, "enabled", False, "mlflow.enabled"),
        tracking_uri=_optional_string(
            data, "tracking_uri", None, "mlflow.tracking_uri"
        ),
        experiment_name=_optional_string(
            data, "experiment_name", None, "mlflow.experiment_name"
        ),
    )


def _load_codex(value: Any) -> CodexConfig:
    data = _optional_mapping(value, "codex")
    return CodexConfig(
        model=_optional_string(data, "model", None, "codex.model"),
        effort=_optional_string(data, "effort", None, "codex.effort"),
    )


def _load_implementation(value: Any) -> ImplementationConfig:
    data = _optional_mapping(value, "implementation")
    return ImplementationConfig(max_repairs=_positive_int(data, "max_repairs", 3))


def _optional_mapping(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ResearchRunSpecError(
            f"Research Run Spec field '{field}' must be a mapping."
        )
    return value


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchRunSpecError(f"Research Run Spec field '{field}' is required.")
    return value


def _optional_string(
    data: dict[str, Any],
    field: str,
    default: str | None = None,
    display_field: str | None = None,
) -> str | None:
    value = data[field] if field in data else default
    if value is None:
        if default is not None:
            raise ResearchRunSpecError(
                f"Research Run Spec field '{display_field or field}' must be a string."
            )
        return None
    if not isinstance(value, str):
        raise ResearchRunSpecError(
            f"Research Run Spec field '{display_field or field}' must be a string."
        )
    if not value.strip():
        raise ResearchRunSpecError(
            f"Research Run Spec field '{display_field or field}' must be non-empty."
        )
    return value


def _positive_int(data: dict[str, Any], field: str, default: int) -> int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchRunSpecError(
            f"Research Run Spec field '{field}' must be a positive integer."
        )
    return value


def _optional_bool(
    data: dict[str, Any],
    field: str,
    default: bool,
    display_field: str | None = None,
) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ResearchRunSpecError(
            f"Research Run Spec field '{display_field or field}' must be a boolean."
        )
    return value
