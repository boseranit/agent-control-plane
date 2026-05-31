from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

UNSUPPORTED_TOP_LEVEL_FIELDS = frozenset(
    {
        "env",
        "environment",
        "environment_variables",
        "env_vars",
        "target_branch",
        "branch",
        "base_branch",
        "service_tier",
        "dependencies",
        "dependency_graph",
        "depends_on",
    }
)
UNSUPPORTED_CODEX_FIELDS = frozenset({"service_tier"})
UNSUPPORTED_TASK_FIELDS = frozenset(
    {
        "env",
        "environment",
        "environment_variables",
        "env_vars",
        "dependencies",
        "dependency_graph",
        "depends_on",
    }
)


@dataclass(frozen=True)
class CodexConfig:
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class TestCommand:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    prompt: str
    context: str | None = None


@dataclass(frozen=True)
class TaskSpec:
    source_path: Path
    target_repository: Path
    description: str | None
    context: str | None
    codex: CodexConfig
    require_plan_approval: bool
    max_iterations: int
    test_commands: tuple[TestCommand, ...]
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class TaskSource:
    task_spec: TaskSpec
    snapshot_text: str
    untracked_source_root: str | None = None


class TaskSpecError(ValueError):
    """Raised when a Task Spec cannot be loaded."""


def load_task_source(
    path: str | Path, *, repo_path: str | Path | None = None
) -> TaskSource:
    source_path = Path(path).expanduser()
    if source_path.is_dir():
        return _load_issue_directory_source(source_path, repo_path=repo_path)
    if repo_path is not None:
        raise TaskSpecError(
            "Task Source --repo is only supported for issue directories."
        )
    task_spec = load_task_spec(source_path)
    return TaskSource(
        task_spec=task_spec,
        snapshot_text=task_spec.source_path.read_text(encoding="utf-8"),
    )


def load_task_spec(path: str | Path) -> TaskSpec:
    source_path = Path(path).expanduser()
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    return _load_task_spec_data(data, source_path=source_path.resolve())


def _load_task_spec_data(data: Any, *, source_path: Path) -> TaskSpec:
    if not isinstance(data, dict):
        raise TaskSpecError("Task Spec must be a mapping.")
    _reject_unsupported_fields(data, UNSUPPORTED_TOP_LEVEL_FIELDS, "Task Spec")

    target_repository = _required_path(data, "target_repository").expanduser().resolve()
    codex_data = data.get("codex") or {}
    if not isinstance(codex_data, dict):
        raise TaskSpecError("Task Spec field 'codex' must be a mapping.")
    _reject_unsupported_fields(codex_data, UNSUPPORTED_CODEX_FIELDS, "Codex")

    return TaskSpec(
        source_path=source_path,
        target_repository=target_repository,
        description=_optional_string(data, "description"),
        context=_optional_string(data, "context"),
        codex=CodexConfig(
            model=_optional_string(codex_data, "model"),
            effort=_optional_string(codex_data, "effort"),
        ),
        require_plan_approval=bool(data.get("require_plan_approval", True)),
        max_iterations=int(data.get("max_iterations", 10)),
        test_commands=_load_test_commands(data.get("test_commands", [])),
        tasks=_load_tasks(data.get("tasks")),
    )


def _load_issue_directory_source(
    source_path: Path, *, repo_path: str | Path | None
) -> TaskSource:
    issue_directory = source_path.resolve()
    target_repository = (
        Path(repo_path).expanduser().resolve()
        if repo_path is not None
        else _infer_target_repository(issue_directory)
    )
    issue_files = sorted(
        path
        for path in issue_directory.glob("*.md")
        if path.name.lower() != "readme.md"
    )
    if not issue_files:
        raise TaskSpecError(
            f"Issue Directory has no issue markdown files: {issue_directory}"
        )

    readme_path = issue_directory / "README.md"
    if readme_path.exists() and not readme_path.is_file():
        raise TaskSpecError(f"Issue Directory README is not a file: {readme_path}")
    readme_text = (
        readme_path.read_text(encoding="utf-8").strip() if readme_path.exists() else ""
    )

    tasks = []
    for issue_file in issue_files:
        issue_text = issue_file.read_text(encoding="utf-8").strip()
        title = _first_markdown_title(issue_text)
        if title is None:
            raise TaskSpecError(
                f"Issue file requires a top-level markdown title: {issue_file}"
            )
        tasks.append(
            {
                "id": issue_file.stem,
                "title": title,
                "prompt": f"{issue_text}\n",
                "context": f"Imported from issue file: {issue_file}",
            }
        )

    context_parts = [
        "Task Source: Issue Directory",
        f"Issue directory: {issue_directory}",
    ]
    if readme_text:
        context_parts.extend(["", "README:", readme_text])

    data = {
        "target_repository": str(target_repository),
        "description": _first_markdown_title(readme_text)
        or f"Imported issue directory: {issue_directory.name}",
        "context": "\n".join(context_parts) + "\n",
        "tasks": tasks,
    }
    return TaskSource(
        task_spec=_load_task_spec_data(data, source_path=issue_directory),
        snapshot_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=False),
        untracked_source_root=_untracked_source_root(
            issue_directory, target_repository
        ),
    )


def _first_markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title
    return None


def _infer_target_repository(issue_directory: Path) -> Path:
    for candidate in (issue_directory, *issue_directory.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    raise TaskSpecError(
        "Issue Directory target repository could not be inferred; pass --repo."
    )


def _untracked_source_root(
    issue_directory: Path, target_repository: Path
) -> str | None:
    if not issue_directory.is_relative_to(target_repository):
        return None
    source_root = issue_directory.relative_to(target_repository).as_posix().rstrip("/")
    return source_root if source_root and source_root != "." else None


def _reject_unsupported_fields(
    data: dict[str, Any], unsupported_fields: frozenset[str], owner: str
) -> None:
    for field in data:
        if field in unsupported_fields:
            raise TaskSpecError(f"Unsupported v1 {owner} field '{field}'.")


def _required_path(data: dict[str, Any], field: str) -> Path:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TaskSpecError(f"Task Spec field '{field}' is required.")
    return Path(value)


def _optional_string(data: dict[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskSpecError(f"Task Spec field '{field}' must be a string.")
    return value


def _load_test_commands(value: Any) -> tuple[TestCommand, ...]:
    if not isinstance(value, list):
        raise TaskSpecError("Task Spec field 'test_commands' must be a list.")

    commands: list[TestCommand] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            raise TaskSpecError(
                "Task Spec shell-string test commands are not supported; use named argv commands."
            )
        if not isinstance(item, dict):
            raise TaskSpecError(f"Test command {index} must be a mapping.")
        if "command" in item:
            raise TaskSpecError(
                "Task Spec shell-string test commands are not supported; use named argv commands."
            )
        name = item.get("name")
        argv = item.get("argv")
        if not isinstance(name, str) or not name.strip():
            raise TaskSpecError(f"Test command {index} requires a name.")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(part, str) for part in argv)
        ):
            raise TaskSpecError(
                f"Test command '{name}' requires a non-empty argv list."
            )
        commands.append(TestCommand(name=name, argv=tuple(argv)))
    return tuple(commands)


def _load_tasks(value: Any) -> tuple[Task, ...]:
    if not isinstance(value, list) or not value:
        raise TaskSpecError("Task Spec field 'tasks' must be a non-empty list.")

    tasks: list[Task] = []
    seen_task_ids: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise TaskSpecError(f"Task {index} must be a mapping.")
        _reject_unsupported_fields(item, UNSUPPORTED_TASK_FIELDS, "Task")
        task_id = item.get("id")
        title = item.get("title")
        prompt = item.get("prompt")
        if not isinstance(task_id, str) or not task_id.strip():
            raise TaskSpecError(f"Task {index} requires an explicit Task ID.")
        if task_id in seen_task_ids:
            raise TaskSpecError(f"Duplicate Task ID '{task_id}'.")
        seen_task_ids.add(task_id)
        if not isinstance(title, str) or not title.strip():
            raise TaskSpecError(f"Task '{task_id}' requires a title.")
        if not isinstance(prompt, str) or not prompt.strip():
            raise TaskSpecError(f"Task '{task_id}' requires a prompt.")
        context = item.get("context")
        if context is not None and not isinstance(context, str):
            raise TaskSpecError(f"Task '{task_id}' field 'context' must be a string.")
        tasks.append(Task(task_id=task_id, title=title, prompt=prompt, context=context))
    return tuple(tasks)
