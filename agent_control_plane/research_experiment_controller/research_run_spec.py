from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_control_plane.research_agent_defaults import DEFAULT_RESEARCH_AGENT_MODEL
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)


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


@dataclass(frozen=True, init=False)
class ResearchProgramConfig:
    paths: ResearchProgramPaths

    def __init__(
        self,
        root: str | Path | ResearchProgramPaths,
    ) -> None:
        paths = (
            root
            if isinstance(root, ResearchProgramPaths)
            else ResearchProgramPaths(root)
        )
        object.__setattr__(self, "paths", paths)

    @property
    def root(self) -> Path:
        return Path(self.paths.root)


@dataclass(frozen=True)
class MLflowConfig:
    enabled: bool = False
    tracking_uri: str | None = None
    experiment_name: str | None = None


@dataclass(frozen=True)
class CodexConfig:
    model: str = DEFAULT_RESEARCH_AGENT_MODEL
    effort: str | None = None


@dataclass(frozen=True)
class ImplementationConfig:
    max_repairs: int = 3


@dataclass(frozen=True)
class ContinuationConfig:
    prior_run_dirs: tuple[Path, ...] = ()
    prior_worktree_roots: tuple[Path, ...] = ()
    repo_loop_context_paths: tuple[Path, ...] = ()
    max_prior_experiments: int = 12


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
    experiment_data_root: Path
    research_program: ResearchProgramConfig
    worktree: WorktreeConfig
    mlflow: MLflowConfig
    codex: CodexConfig
    implementation: ImplementationConfig
    continuation: ContinuationConfig
    stop_on_prerequisites_failed: bool


class ResearchRunSpecError(ValueError):
    """Raised when a Research Run Spec cannot be loaded."""


def load_research_run_spec(path: str | Path) -> ResearchRunSpec:
    return _load_research_run_spec(path, research_program_root=None)


def load_research_run_spec_snapshot(
    path: str | Path,
    *,
    research_program_root: str | Path,
) -> ResearchRunSpec:
    return _load_research_run_spec(path, research_program_root=research_program_root)


def _load_research_run_spec(
    path: str | Path,
    *,
    research_program_root: str | Path | None,
) -> ResearchRunSpec:
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
    _reject_unsupported_field(
        data,
        "max_prior_experiments",
        replacement="continuation.max_prior_experiments",
    )

    data_root = Path(_required_string(data, "data_root")).expanduser()
    experiment_data_root = Path(
        _required_string(data, "experiment_data_root")
    ).expanduser()
    _require_experiment_data_root_outside_data_root(
        data_root=data_root,
        experiment_data_root=experiment_data_root,
    )
    research_program = _load_research_program(
        data,
        research_program_root=research_program_root,
    )
    continuation = _load_continuation(
        data.get("continuation"),
    )

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
        data_root=data_root,
        experiment_data_root=experiment_data_root,
        research_program=research_program,
        worktree=_load_worktree(data.get("worktree")),
        mlflow=_load_mlflow(data.get("mlflow")),
        codex=_load_codex(data.get("codex")),
        implementation=_load_implementation(data.get("implementation")),
        continuation=continuation,
        stop_on_prerequisites_failed=_optional_bool(
            data, "stop_on_prerequisites_failed", True
        ),
    )


def resolved_spec_dict(
    spec: ResearchRunSpec,
    *,
    include_research_program_root: bool = True,
) -> dict[str, Any]:
    data = {
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
        "experiment_data_root": str(spec.experiment_data_root),
        "continuation": {
            "prior_run_dirs": [
                str(path) for path in spec.continuation.prior_run_dirs
            ],
            "prior_worktree_roots": [
                str(path) for path in spec.continuation.prior_worktree_roots
            ],
            "repo_loop_context_paths": [
                str(path) for path in spec.continuation.repo_loop_context_paths
            ],
            "max_prior_experiments": spec.continuation.max_prior_experiments,
        },
        "worktree": {"create": spec.worktree.create},
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
    if include_research_program_root:
        data["research_program_root"] = str(spec.research_program.root)
    return data


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


def _load_research_program(
    data: dict[str, Any],
    *,
    research_program_root: str | Path | None,
) -> ResearchProgramConfig:
    if research_program_root is None:
        root = Path(_required_string(data, "research_program_root"))
    else:
        root = Path(research_program_root)
    return ResearchProgramConfig(
        root=root.expanduser().resolve(),
    )


def _load_worktree(value: Any) -> WorktreeConfig:
    data = _optional_mapping(value, "worktree")
    if "root" in data:
        raise ResearchRunSpecError(
            "Research Run Spec field 'worktree.root' is not supported; use "
            "research_program_root."
        )
    return WorktreeConfig(
        create=_optional_bool(data, "create", True, "worktree.create"),
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
        model=_optional_string(
            data,
            "model",
            DEFAULT_RESEARCH_AGENT_MODEL,
            "codex.model",
        ),
        effort=_optional_string(data, "effort", None, "codex.effort"),
    )


def _load_implementation(value: Any) -> ImplementationConfig:
    data = _optional_mapping(value, "implementation")
    return ImplementationConfig(max_repairs=_positive_int(data, "max_repairs", 3))


def _load_continuation(value: Any) -> ContinuationConfig:
    data = _optional_mapping(value, "continuation")
    return ContinuationConfig(
        prior_run_dirs=_path_tuple(
            data, "prior_run_dirs", "continuation.prior_run_dirs"
        ),
        prior_worktree_roots=_path_tuple(
            data, "prior_worktree_roots", "continuation.prior_worktree_roots"
        ),
        repo_loop_context_paths=_existing_readable_file_path_tuple(
            data,
            "repo_loop_context_paths",
            "continuation.repo_loop_context_paths",
        ),
        max_prior_experiments=_positive_int(
            data,
            "max_prior_experiments",
            12,
            "continuation.max_prior_experiments",
        ),
    )


def _require_experiment_data_root_outside_data_root(
    *,
    data_root: Path,
    experiment_data_root: Path,
) -> None:
    resolved_data_root = data_root.resolve()
    resolved_experiment_data_root = experiment_data_root.resolve()
    if (
        resolved_experiment_data_root == resolved_data_root
        or resolved_data_root in resolved_experiment_data_root.parents
    ):
        raise ResearchRunSpecError(
            "Research Run Spec field 'experiment_data_root' must be outside data_root."
        )


def _optional_mapping(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ResearchRunSpecError(
            f"Research Run Spec field '{field}' must be a mapping."
        )
    return value


def _reject_unsupported_field(
    data: dict[str, Any],
    field: str,
    *,
    replacement: str,
) -> None:
    if field in data:
        raise ResearchRunSpecError(
            f"Research Run Spec field '{field}' is not supported; "
            f"use '{replacement}'."
        )


def _path_tuple(
    data: dict[str, Any],
    field: str,
    display_field: str,
) -> tuple[Path, ...]:
    value = data.get(field, [])
    if not isinstance(value, list):
        raise ResearchRunSpecError(
            f"Research Run Spec field '{display_field}' must be a list."
        )
    paths: list[Path] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ResearchRunSpecError(
                f"Research Run Spec field '{display_field}[{index}]' "
                "must be a non-empty string."
            )
        paths.append(Path(item).expanduser().resolve())
    return tuple(paths)


def _existing_readable_file_path_tuple(
    data: dict[str, Any],
    field: str,
    display_field: str,
) -> tuple[Path, ...]:
    paths = _path_tuple(data, field, display_field)
    for index, path in enumerate(paths):
        display_item = f"{display_field}[{index}]"
        if not path.is_file():
            raise ResearchRunSpecError(
                f"Research Run Spec field '{display_item}' must be an "
                f"existing readable file: {path}"
            )
        try:
            with path.open("rb"):
                pass
        except OSError as exc:
            raise ResearchRunSpecError(
                f"Research Run Spec field '{display_item}' must be an "
                f"existing readable file: {path}"
            ) from exc
    return paths


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


def _positive_int(
    data: dict[str, Any],
    field: str,
    default: int,
    display_field: str | None = None,
) -> int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchRunSpecError(
            f"Research Run Spec field '{display_field or field}' must be a "
            "positive integer."
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
