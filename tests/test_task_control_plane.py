import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from agent_control_plane.task_control_plane.agent_runtime import AgentRunConfig
from agent_control_plane.task_control_plane.cli import main
from agent_control_plane.task_control_plane.controller import (
    CONTEXT_ANSWERS_SCHEMA_PATH,
    CONTEXT_PROMPT_PATH,
    IMPLEMENTER_PROMPT_PATH,
    IMPLEMENTER_RESULT_SCHEMA_PATH,
    PLANNER_OUTPUT_SCHEMA_PATH,
    PLANNER_PROMPT_PATH,
    REVIEWER_OUTPUT_SCHEMA_PATH,
    REVIEWER_PROMPT_PATH,
    ContextOutputError,
    HumanAnswerError,
    PlannerOutputError,
    TaskRun,
    TaskRunError,
    build_implementer_turn_input,
    commit_active_task_and_advance,
    plan_active_task,
    resume_task_run,
    run_active_task_failed_test_repair,
    run_active_task_implementer,
    run_active_task_review_rejection_repair,
    run_active_task_reviewer,
    run_active_task_tests,
    start_task_run,
)
from agent_control_plane.task_control_plane.task_spec import (
    TaskSpecError,
    load_task_source,
    load_task_spec,
)


class FakeCodexClient:
    def __init__(
        self,
        planner_output: object | list[object],
        context_outputs: list[object] | None = None,
        implementer_outputs: list[object] | None = None,
        reviewer_outputs: list[object] | None = None,
    ) -> None:
        self.started_threads: list[dict[str, object]] = []
        self.resumed_threads: list[dict[str, object]] = []
        self.outputs_by_role = {
            "planner": (
                list(planner_output)
                if isinstance(planner_output, list)
                else [planner_output]
            ),
            "context": list(context_outputs or []),
            "implementer": list(implementer_outputs or []),
            "reviewer": list(reviewer_outputs or []),
        }
        self.started_thread: FakeCodexThread | None = None
        self.resumed_thread: FakeCodexThread | None = None
        self.threads_by_role: dict[str, FakeCodexThread] = {}
        self.thread_history_by_role: dict[str, list[FakeCodexThread]] = {}

    def open_thread(self, config: AgentRunConfig) -> "FakeCodexThread":
        kwargs = thread_call_from_config(config)
        if config.thread_id:
            return self.thread_resume(config.thread_id, **kwargs)
        return self.thread_start(**kwargs)

    def thread_start(self, **kwargs: object) -> "FakeCodexThread":
        self.started_threads.append(kwargs)
        role = self._role(kwargs)
        role_thread_count = len(self.thread_history_by_role.get(role, [])) + 1
        thread = FakeCodexThread(
            f"{role}-thread-{role_thread_count}", self.outputs_by_role[role]
        )
        self.threads_by_role[role] = thread
        self.thread_history_by_role.setdefault(role, []).append(thread)
        if role == "planner":
            self.started_thread = thread
        return thread

    def thread_resume(self, thread_id: str, **kwargs: object) -> "FakeCodexThread":
        self.resumed_threads.append({"thread_id": thread_id, **kwargs})
        role = self._role(kwargs)
        self.resumed_thread = FakeCodexThread(thread_id, self.outputs_by_role[role])
        self.threads_by_role[role] = self.resumed_thread
        return self.resumed_thread

    @staticmethod
    def _role(kwargs: dict[str, object]) -> str:
        developer_instructions = kwargs.get("developer_instructions")
        if (
            isinstance(developer_instructions, str)
            and "Implementer Agent" in developer_instructions
        ):
            return "implementer"
        if (
            isinstance(developer_instructions, str)
            and "Context Agent" in developer_instructions
        ):
            return "context"
        if (
            isinstance(developer_instructions, str)
            and "Planner Agent" in developer_instructions
        ):
            return "planner"
        if (
            isinstance(developer_instructions, str)
            and "Reviewer Agent" in developer_instructions
        ):
            return "reviewer"
        raise AssertionError("FakeCodexClient could not identify thread role.")


class FakeCodexThread:
    def __init__(self, thread_id: str, outputs: list[object]) -> None:
        self.id = thread_id
        self.outputs = outputs
        self.run_calls: list[dict[str, object]] = []

    def run(self, input: str, config: AgentRunConfig) -> object:
        kwargs = run_call_from_config(config)
        self.run_calls.append({"input": input, **kwargs})
        if not self.outputs:
            raise AssertionError(f"No queued output for thread {self.id}.")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return FakeCodexTurnResult(output)


class FakeCodexTurnResult:
    def __init__(self, planner_output: object) -> None:
        self.final_response = (
            planner_output
            if isinstance(planner_output, str)
            else json.dumps(planner_output)
        )


def sdk_value(value: object) -> object:
    return getattr(value, "value", value)


class FakeSandboxPolicy:
    def __init__(self, type: str) -> None:
        self.type = type


def thread_call_from_config(config: AgentRunConfig) -> dict[str, object]:
    return {
        "approval_mode": "deny_all" if config.role == "reviewer" else "auto_review",
        "cwd": str(config.cwd),
        "developer_instructions": config.developer_instructions,
        "model": config.model,
        "sandbox": ("workspace-write" if config.role == "implementer" else "read-only"),
    }


def run_call_from_config(config: AgentRunConfig) -> dict[str, object]:
    sandbox_policy_type = (
        "workspaceWrite" if config.role == "implementer" else "readOnly"
    )
    return {
        "approval_mode": "deny_all" if config.role == "reviewer" else "auto_review",
        "cwd": str(config.cwd),
        "effort": config.effort,
        "model": config.model,
        "output_schema": config.output_schema,
        "sandbox_policy": FakeSandboxPolicy(sandbox_policy_type),
    }


def configure_git_identity(repository: Path) -> None:
    subprocess.run(
        ["git", "config", "user.name", "Task Control Plane Test"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "task-control-plane@example.test"],
        cwd=repository,
        check=True,
        capture_output=True,
    )


def create_task_run(
    tmp_path: Path, *, require_plan_approval: bool = False
) -> tuple[Path, TaskRun]:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)

    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: {str(require_plan_approval).lower()}
codex:
  model: gpt-5-codex
  effort: high
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    return target_repository, start_task_run(
        task_spec_path, runtime_root=tmp_path / "runs"
    )


def create_single_task_run_with_passing_command(
    tmp_path: Path,
) -> tuple[Path, TaskRun]:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    passing_command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            "Path('test-created.txt').write_text('created by tests\\n', "
            "encoding='utf-8')"
        ),
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: unit
    argv: {json.dumps(passing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    return target_repository, start_task_run(
        task_spec_path, runtime_root=tmp_path / "runs"
    )


def write_issue_directory(target_repository: Path) -> Path:
    issue_directory = (
        target_repository / ".planning" / "issues" / "cross-sectional-samples-collapse"
    )
    issue_directory.mkdir(parents=True)
    (issue_directory / "README.md").write_text(
        """# Issue Breakdown: Collapse Cross-Sectional Samples Into Elastic-Net

Parent PRD: https://example.test/prd/25
""",
        encoding="utf-8",
    )
    (issue_directory / "01-fit-elastic-net.md").write_text(
        """# Fit Elastic-Net From Feature Groups In Hot Modes

Type: AFK

## What to build

Make the model consume feature group outputs directly.

## Acceptance criteria

- [ ] Declares direct feature group dependencies.

## Blocked by

None - can start immediately
""",
        encoding="utf-8",
    )
    (issue_directory / "02-backfill-elastic-net.md").write_text(
        """# Backfill Elastic-Net Directly From Feature Group Parquet

Type: AFK

## What to build

Make backfill read promoted feature group parquet directly.

## Acceptance criteria

- [ ] Backfill keeps existing output layouts unchanged.

## Blocked by

- Issue 1
""",
        encoding="utf-8",
    )
    return issue_directory


def mark_task_run_commit_ready(task_run: TaskRun) -> None:
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    active_task_state = state["tasks"][0]
    state["phase"] = "commit_ready"
    active_task_state["phase"] = "commit_ready"
    active_task_state["latest_test_status"] = {
        "passed": True,
        "status": "passed",
        "command_log_path": active_task_state["artifacts"]["command_log"],
    }
    active_task_state["latest_review_output"] = {
        "status": "approved",
        "summary": "Ready.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    task_run.task_state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_load_task_spec_applies_defaults_and_preserves_ordered_tasks(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
description: Bootstrap the run
context: Shared run context
codex:
  model: gpt-5-codex
  effort: high
test_commands:
  - name: unit
    argv: ["pytest", "-q"]
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
    context: Task-specific context.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )

    task_spec = load_task_spec(task_spec_path)

    assert task_spec.target_repository == target_repository.resolve()
    assert task_spec.description == "Bootstrap the run"
    assert task_spec.context == "Shared run context"
    assert task_spec.codex.model == "gpt-5-codex"
    assert task_spec.codex.effort == "high"
    assert task_spec.require_plan_approval is True
    assert task_spec.max_iterations == 10
    assert [(command.name, command.argv) for command in task_spec.test_commands] == [
        ("unit", ("pytest", "-q"))
    ]
    assert [task.task_id for task in task_spec.tasks] == ["TASK-1", "TASK-2"]
    assert task_spec.tasks[0].context == "Task-specific context."


def test_load_task_source_imports_issue_directory_as_ordered_tasks(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    issue_directory = write_issue_directory(target_repository)

    source = load_task_source(issue_directory)

    assert source.task_spec.target_repository == target_repository.resolve()
    assert source.task_spec.description == (
        "Issue Breakdown: Collapse Cross-Sectional Samples Into Elastic-Net"
    )
    assert [task.task_id for task in source.task_spec.tasks] == [
        "01-fit-elastic-net",
        "02-backfill-elastic-net",
    ]
    assert source.task_spec.tasks[0].title == (
        "Fit Elastic-Net From Feature Groups In Hot Modes"
    )
    assert "Declares direct feature group dependencies" in (
        source.task_spec.tasks[0].prompt
    )
    assert "Parent PRD" in (source.task_spec.context or "")
    assert (
        source.untracked_source_root
        == ".planning/issues/cross-sectional-samples-collapse"
    )
    assert "01-fit-elastic-net" in source.snapshot_text


def test_load_task_source_imports_external_issue_directory_with_repo_override(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    issue_directory = tmp_path / "issues"
    issue_directory.mkdir()
    (issue_directory / "01-task.md").write_text(
        "# External Task\n\nDo the work.\n", encoding="utf-8"
    )

    source = load_task_source(issue_directory, repo_path=target_repository)

    assert source.task_spec.target_repository == target_repository.resolve()
    assert source.task_spec.tasks[0].task_id == "01-task"
    assert source.untracked_source_root is None


def test_load_task_source_requires_repo_for_external_issue_directory(
    tmp_path: Path,
) -> None:
    issue_directory = tmp_path / "issues"
    issue_directory.mkdir()
    (issue_directory / "01-task.md").write_text(
        "# External Task\n\nDo the work.\n", encoding="utf-8"
    )

    with pytest.raises(TaskSpecError, match="could not be inferred"):
        load_task_source(issue_directory)


def test_load_task_source_rejects_repo_override_for_yaml(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskSpecError, match="only supported for issue directories"):
        load_task_source(task_spec_path, repo_path=target_repository)


def test_load_task_spec_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-1
    title: Duplicate task
    prompt: Implement the duplicate task.
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskSpecError, match="Duplicate Task ID 'TASK-1'"):
        load_task_spec(task_spec_path)


def test_load_task_spec_rejects_shell_string_test_commands(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
test_commands:
  - name: unit
    command: "pytest -q"
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(
        TaskSpecError, match="shell-string test commands are not supported"
    ):
        load_task_spec(task_spec_path)


def test_load_task_spec_rejects_string_argv_test_commands(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
test_commands:
  - name: unit
    argv: "pytest -q"
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskSpecError, match="requires a non-empty argv list"):
        load_task_spec(task_spec_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("env", "{}"),
        ("environment", "{}"),
        ("env_vars", "{}"),
        ("target_branch", "feature/task-control-plane"),
        ("service_tier", "flex"),
        ("dependencies", "[]"),
        ("dependency_graph", "{}"),
    ],
)
def test_load_task_spec_rejects_unsupported_v1_fields(
    tmp_path: Path, field: str, value: str
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
{field}: {value}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(
        TaskSpecError, match=f"Unsupported v1 Task Spec field '{field}'"
    ):
        load_task_spec(task_spec_path)


def test_load_task_spec_rejects_codex_service_tier(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
codex:
  model: gpt-5-codex
  service_tier: flex
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(
        TaskSpecError, match="Unsupported v1 Codex field 'service_tier'"
    ):
        load_task_spec(task_spec_path)


def test_load_task_spec_rejects_task_dependency_fields(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
    depends_on: []
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskSpecError, match="Unsupported v1 Task field 'depends_on'"):
        load_task_spec(task_spec_path)


def test_start_task_run_creates_snapshot_state_and_first_task_context(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )

    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_content = f"""
target_repository: {target_repository}
description: Bootstrap the run
context: Shared run context
require_plan_approval: false
max_iterations: 3
test_commands:
  - name: unit
    argv: ["pytest", "-q"]
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
"""
    task_spec_path.write_text(task_spec_content, encoding="utf-8")

    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")

    assert task_run.run_directory.parent == (tmp_path / "runs").resolve()
    snapshot_path = task_run.run_directory / "task-spec.yaml"
    state_path = task_run.run_directory / "task-state.json"
    context_path = task_run.run_directory / "tasks" / "TASK-1" / "context.json"
    assert snapshot_path.read_text(encoding="utf-8") == task_spec_content

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["run_id"] == task_run.run_id
    assert state["phase"] == "ready_for_planning"
    assert state["active_task_id"] == "TASK-1"
    assert state["active_task"] == {"id": "TASK-1", "title": "First task"}
    assert [task["id"] for task in state["tasks"]] == ["TASK-1", "TASK-2"]
    assert [task["status"] for task in state["tasks"]] == ["active", "pending"]

    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["run_id"] == task_run.run_id
    assert context["run"]["require_plan_approval"] is False
    assert context["run"]["max_iterations"] == 3
    assert context["task"]["id"] == "TASK-1"
    assert context["task"]["prompt"] == "Implement the first task."
    assert Path(context["target_repository"]).is_absolute()
    assert Path(context["task_spec_snapshot_path"]).is_absolute()
    assert Path(context["task_state_path"]).is_absolute()
    assert all(Path(path).is_absolute() for path in context["artifacts"].values())


def test_start_task_run_accepts_untracked_issue_directory_source(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    issue_directory = write_issue_directory(target_repository)

    task_run = start_task_run(issue_directory, runtime_root=tmp_path / "runs")

    snapshot = load_task_spec(task_run.task_spec_snapshot_path)
    assert [task.task_id for task in snapshot.tasks] == [
        "01-fit-elastic-net",
        "02-backfill-elastic-net",
    ]
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert (
        state["task_source_untracked_root"]
        == ".planning/issues/cross-sectional-samples-collapse"
    )
    assert state["active_task_id"] == "01-fit-elastic-net"


def test_start_task_run_rejects_untracked_file_next_to_issue_directory_source(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    issue_directory = write_issue_directory(target_repository)
    adjacent_directory = issue_directory.with_name(f"{issue_directory.name}-extra")
    adjacent_directory.mkdir()
    (adjacent_directory / "01-task.md").write_text(
        "# Adjacent Task\n\nThis is not run input.\n", encoding="utf-8"
    )

    with pytest.raises(TaskRunError, match="Target Repository must be clean"):
        start_task_run(issue_directory, runtime_root=tmp_path / "runs")


def test_start_task_run_refuses_dirty_target_repository(tmp_path: Path) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    (target_repository / "untracked.txt").write_text("human edit\n", encoding="utf-8")

    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskRunError, match="Target Repository must be clean"):
        start_task_run(task_spec_path, runtime_root=tmp_path / "runs")

    assert not (tmp_path / "runs").exists()


def test_plan_active_task_starts_planner_thread_and_records_planned_output(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {
        "status": "planned",
        "plan_markdown": "1. Inspect the existing code.\n2. Make the scoped change.",
    }
    codex_client = FakeCodexClient(planner_output)

    def fail_if_editor_opens(_approved_plan_path: Path) -> None:
        raise AssertionError("Auto-approval must not open the editor.")

    def fail_if_confirmation_requested(_approved_plan_path: Path) -> bool:
        raise AssertionError("Auto-approval must not request confirmation.")

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=fail_if_editor_opens,
        plan_approval_confirmer=fail_if_confirmation_requested,
    )

    assert result == planner_output
    assert len(codex_client.started_threads) == 1
    start_call = codex_client.started_threads[0]
    assert "Planner Agent" in start_call["developer_instructions"]
    assert start_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(start_call["approval_mode"]) == "auto_review"
    assert sdk_value(start_call["sandbox"]) == "read-only"
    assert start_call["model"] == "gpt-5-codex"

    run_call = codex_client.started_thread.run_calls[0]
    assert "TASK-1" in run_call["input"]
    assert run_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(run_call["approval_mode"]) == "auto_review"
    assert run_call["sandbox_policy"].type == "readOnly"
    assert sdk_value(run_call["effort"]) == "high"
    assert run_call["output_schema"]["title"] == "PlannerOutput"

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    assert state["phase"] == "plan_approved"
    assert task_state["phase"] == "plan_approved"
    assert task_state["threads"]["planner"] == "planner-thread-1"

    planning_artifact_path = Path(task_state["artifacts"]["planning"])
    planning_artifact = json.loads(planning_artifact_path.read_text(encoding="utf-8"))
    assert planning_artifact["planner_outputs"] == [planner_output]

    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    assert approved_plan_path.read_text(encoding="utf-8") == (
        "1. Inspect the existing code.\n2. Make the scoped change.\n"
    )
    assert planning_artifact["approved_plan"]["path"] == str(approved_plan_path)
    assert planning_artifact["approved_plan"]["approval"]["status"] == "approved"
    assert planning_artifact["approved_plan"]["approval"]["mode"] == "automatic"
    assert "approved_at" in planning_artifact["approved_plan"]["approval"]
    assert "plan_markdown" not in planning_artifact["approved_plan"]
    assert task_state["plan_approval"]["status"] == "approved"
    assert task_state["plan_approval"]["mode"] == "automatic"
    assert task_state["plan_approval"]["approved_plan_path"] == str(approved_plan_path)


def test_plan_active_task_sleeps_until_usage_limit_retry_time_and_retries(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Continue after the usage-limit wait.",
    }
    usage_limit_error = RuntimeError(
        "Codex usage limit reached. Please try again at 2026-05-27T14:05:00+10:00."
    )
    codex_client = FakeCodexClient([usage_limit_error, planner_output])
    sleeps: list[float] = []

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        usage_clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        usage_sleep=sleeps.append,
    )

    assert result == planner_output
    assert sleeps == [300.0]
    planner_thread = codex_client.threads_by_role["planner"]
    assert len(planner_thread.run_calls) == 2
    assert planner_thread.run_calls[0]["input"] == planner_thread.run_calls[1]["input"]

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    usage_wait = state["usage_limit_waits"][0]
    assert task_state["usage_limit_waits"] == [usage_wait]
    assert usage_wait["role"] == "planner"
    assert usage_wait["sleep_seconds"] == 300.0
    assert usage_wait["suggested_retry_at"] == "2026-05-27T14:05:00+10:00"
    assert "usage limit" in usage_wait["message"]
    assert state["phase"] == "plan_approved"


def test_plan_active_task_handles_usage_limit_waits_in_context_agent_turns(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {
        "status": "needs_answers",
        "questions": [{"id": "q1", "question": "Which file should change?"}],
    }
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Use the answered context.",
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Change app.py.",
                "reason": "The task context points at app.py.",
            }
        ]
    }
    usage_limit_error = RuntimeError(
        "Codex usage limit reached. Please retry after 1 hour and 30 minutes."
    )
    codex_client = FakeCodexClient(
        [planner_output, final_planner_output],
        context_outputs=[usage_limit_error, context_output],
    )
    sleeps: list[float] = []

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        usage_clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        usage_sleep=sleeps.append,
    )

    assert result == final_planner_output
    assert sleeps == [5400.0]
    context_thread = codex_client.threads_by_role["context"]
    assert len(context_thread.run_calls) == 2
    assert context_thread.run_calls[0]["input"] == context_thread.run_calls[1]["input"]

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    usage_wait = state["usage_limit_waits"][0]
    assert usage_wait["role"] == "context"
    assert usage_wait["sleep_seconds"] == 5400.0
    assert usage_wait["suggested_retry_at"] == "2026-05-27T15:30:00+10:00"


def test_run_active_task_implementer_never_records_negative_usage_limit_sleep(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Implemented after a stale retry time.",
        "changed_files": ["app.py"],
        "recommended_commands": [],
    }
    usage_limit_error = RuntimeError(
        "Codex usage limit reached. Please try again at 2026-05-27T13:59:30+10:00."
    )
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[usage_limit_error, implementer_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    sleeps: list[float] = []

    result = run_active_task_implementer(
        task_run.task_state_path,
        codex_client,
        usage_clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        usage_sleep=sleeps.append,
    )

    assert result == implementer_output
    assert sleeps == [0.0]
    implementer_thread = codex_client.threads_by_role["implementer"]
    assert len(implementer_thread.run_calls) == 2

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    usage_wait = state["usage_limit_waits"][0]
    assert usage_wait["role"] == "implementer"
    assert usage_wait["sleep_seconds"] == 0.0


def test_run_active_task_reviewer_handles_local_time_of_day_usage_limit_wait(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Implemented.",
        "changed_files": ["app.py"],
        "recommended_commands": [],
    }
    reviewer_output = {
        "status": "approved",
        "summary": "Ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    usage_limit_error = RuntimeError(
        "Codex usage limit reached. Please try again at 2:05 PM."
    )
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[usage_limit_error, reviewer_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    run_active_task_tests(task_run.task_state_path)
    sleeps: list[float] = []

    result = run_active_task_reviewer(
        task_run.task_state_path,
        codex_client,
        usage_clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        usage_sleep=sleeps.append,
    )

    assert result == reviewer_output
    assert sleeps == [300.0]
    reviewer_thread = codex_client.thread_history_by_role["reviewer"][0]
    assert len(reviewer_thread.run_calls) == 2

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    usage_wait = state["usage_limit_waits"][0]
    assert usage_wait["role"] == "reviewer"
    assert usage_wait["suggested_retry_at"] == "2026-05-27T14:05:00+10:00"
    assert state["phase"] == "commit_ready"


def test_codex_non_usage_errors_propagate_without_sleeping(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=False)
    codex_client = FakeCodexClient(
        [
            RuntimeError(
                "Codex transport failed. Please try again at 2026-05-27T14:05:00+10:00."
            )
        ]
    )
    sleeps: list[float] = []

    with pytest.raises(RuntimeError, match="transport failed"):
        plan_active_task(
            task_run.task_state_path,
            codex_client,
            usage_clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
            usage_sleep=sleeps.append,
        )

    assert sleeps == []
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert "usage_limit_waits" not in state
    assert "usage_limit_waits" not in state["tasks"][0]


def test_plan_active_task_opens_approved_plan_for_human_approval_and_keeps_edits(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=True)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Planner draft that should be edited.",
    }
    codex_client = FakeCodexClient(planner_output)
    opened_paths: list[Path] = []
    confirmed_paths: list[Path] = []

    def edit_approved_plan(approved_plan_path: Path) -> None:
        opened_paths.append(approved_plan_path)
        approved_plan_path.write_text("Human-edited Approved Plan.\n", encoding="utf-8")

    def confirm_approved_plan(approved_plan_path: Path) -> bool:
        confirmed_paths.append(approved_plan_path)
        return True

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=edit_approved_plan,
        plan_approval_confirmer=confirm_approved_plan,
    )

    assert result == planner_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    assert opened_paths == [approved_plan_path]
    assert confirmed_paths == [approved_plan_path]
    assert approved_plan_path.read_text(encoding="utf-8") == (
        "Human-edited Approved Plan.\n"
    )
    assert state["phase"] == "plan_approved"
    assert task_state["phase"] == "plan_approved"
    assert task_state["plan_approval"]["status"] == "approved"
    assert task_state["plan_approval"]["mode"] == "human"

    planning_artifact = json.loads(
        Path(task_state["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["approved_plan"]["path"] == str(approved_plan_path)
    assert planning_artifact["approved_plan"]["approval"]["status"] == "approved"
    assert planning_artifact["approved_plan"]["approval"]["mode"] == "human"
    assert "plan_markdown" not in planning_artifact["approved_plan"]


def test_plan_active_task_records_declined_human_approval_without_approving(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=True)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Planner draft awaiting human approval.",
    }
    codex_client = FakeCodexClient(planner_output)
    opened_paths: list[Path] = []
    confirmed_paths: list[Path] = []

    def edit_approved_plan(approved_plan_path: Path) -> None:
        opened_paths.append(approved_plan_path)

    def decline_approved_plan(approved_plan_path: Path) -> bool:
        confirmed_paths.append(approved_plan_path)
        return False

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=edit_approved_plan,
        plan_approval_confirmer=decline_approved_plan,
    )

    assert result == planner_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    assert opened_paths == [approved_plan_path]
    assert confirmed_paths == [approved_plan_path]
    assert approved_plan_path.read_text(encoding="utf-8") == (
        "Planner draft awaiting human approval.\n"
    )
    assert state["phase"] == "plan_approval_declined"
    assert task_state["phase"] == "plan_approval_declined"
    assert task_state["plan_approval"]["status"] == "declined"
    assert task_state["plan_approval"]["mode"] == "human"

    planning_artifact = json.loads(
        Path(task_state["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["approved_plan"]["path"] == str(approved_plan_path)
    assert planning_artifact["approved_plan"]["approval"]["status"] == "declined"
    assert planning_artifact["approved_plan"]["approval"]["mode"] == "human"
    assert "declined_at" in planning_artifact["approved_plan"]["approval"]
    assert "plan_markdown" not in planning_artifact["approved_plan"]


def test_build_implementer_turn_input_rejects_declined_plan_approval(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=True)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Planner draft awaiting human approval.",
    }
    codex_client = FakeCodexClient(planner_output)
    plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=lambda _approved_plan_path: None,
        plan_approval_confirmer=lambda _approved_plan_path: False,
    )

    with pytest.raises(TaskRunError, match="Approved Plan has not been approved"):
        build_implementer_turn_input(task_run.task_state_path)


def test_build_implementer_turn_input_uses_approved_plan_path_without_drafts(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path, require_plan_approval=True)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Planner draft must stay out of implementer input.",
    }
    codex_client = FakeCodexClient(planner_output)

    def edit_approved_plan(approved_plan_path: Path) -> None:
        approved_plan_path.write_text(
            "Edited Approved Plan must stay in the file only.\n", encoding="utf-8"
        )

    plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=edit_approved_plan,
        plan_approval_confirmer=lambda _approved_plan_path: True,
    )

    implementer_input = build_implementer_turn_input(task_run.task_state_path)

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    task_context_path = Path(task_state["artifacts"]["task_context"])
    planning_artifact_path = Path(task_state["artifacts"]["planning"])
    assert "TASK-1" in implementer_input
    assert "First task" in implementer_input
    assert str(task_context_path) in implementer_input
    assert str(approved_plan_path) in implementer_input
    assert str(planning_artifact_path) not in implementer_input
    assert "Planner draft must stay out" not in implementer_input
    assert "Edited Approved Plan" not in implementer_input
    assert "planner_outputs" not in implementer_input


def test_run_active_task_implementer_runs_from_approved_plan_and_resumes_thread(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=True)
    planner_output = {
        "status": "planned",
        "plan_markdown": "Planner draft must not be sent to the Implementer Agent.",
    }
    first_implementation_result = {
        "status": "implementation_complete",
        "summary": "Implemented the approved plan.",
        "changed_files": ["app.py"],
        "recommended_commands": [{"name": "unit", "argv": ["pytest", "-q"]}],
    }
    second_implementation_result = {
        "status": "implementation_complete",
        "summary": "Refined the implementation.",
        "changed_files": ["app.py", "tests/test_app.py"],
        "recommended_commands": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[
            first_implementation_result,
            second_implementation_result,
        ],
    )

    def edit_approved_plan(approved_plan_path: Path) -> None:
        approved_plan_path.write_text(
            "Human-edited Approved Plan must stay in the file only.\n",
            encoding="utf-8",
        )

    plan_active_task(
        task_run.task_state_path,
        codex_client,
        approved_plan_editor=edit_approved_plan,
        plan_approval_confirmer=lambda _approved_plan_path: True,
    )

    result = run_active_task_implementer(task_run.task_state_path, codex_client)

    assert result == first_implementation_result
    implementer_start_call = next(
        call
        for call in codex_client.started_threads
        if "Implementer Agent" in call["developer_instructions"]
    )
    assert implementer_start_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(implementer_start_call["approval_mode"]) == "auto_review"
    assert sdk_value(implementer_start_call["sandbox"]) == "workspace-write"
    assert implementer_start_call["model"] == "gpt-5-codex"

    implementer_thread = codex_client.threads_by_role["implementer"]
    run_call = implementer_thread.run_calls[0]
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    task_context_path = Path(task_state["artifacts"]["task_context"])
    planning_artifact_path = Path(task_state["artifacts"]["planning"])
    assert "TASK-1" in run_call["input"]
    assert "First task" in run_call["input"]
    assert str(task_context_path) in run_call["input"]
    assert str(approved_plan_path) in run_call["input"]
    assert str(planning_artifact_path) not in run_call["input"]
    assert "Planner draft must not be sent" not in run_call["input"]
    assert "Human-edited Approved Plan" not in run_call["input"]
    assert run_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(run_call["approval_mode"]) == "auto_review"
    assert run_call["sandbox_policy"].type == "workspaceWrite"
    assert sdk_value(run_call["effort"]) == "high"
    assert run_call["output_schema"]["title"] == "ImplementerResultOutput"

    assert state["phase"] == "ready_for_tests"
    assert task_state["phase"] == "ready_for_tests"
    assert task_state["threads"]["implementer"] == "implementer-thread-1"
    implementation_result_path = Path(task_state["artifacts"]["implementation_result"])
    assert json.loads(implementation_result_path.read_text(encoding="utf-8")) == (
        first_implementation_result
    )

    implementation_result_path.write_text(
        json.dumps({"status": "stale"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resumed_result = run_active_task_implementer(task_run.task_state_path, codex_client)

    assert resumed_result == second_implementation_result
    assert codex_client.resumed_threads[-1]["thread_id"] == "implementer-thread-1"
    assert (
        "Implementer Agent"
        in codex_client.resumed_threads[-1]["developer_instructions"]
    )
    assert json.loads(implementation_result_path.read_text(encoding="utf-8")) == (
        second_implementation_result
    )


def test_run_active_task_tests_streams_command_log_and_records_aggregate_status(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    first_command = [
        sys.executable,
        "-u",
        "-c",
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "import time",
                "Path('cwd-proof.txt').write_text('ran in target\\n', encoding='utf-8')",
                "Path('first-running.txt').write_text('yes\\n', encoding='utf-8')",
                "sys.stdout.write('first stdout')",
                "sys.stdout.flush()",
                "sys.stderr.write('first stderr')",
                "sys.stderr.flush()",
                "time.sleep(1.0)",
                "Path('first-running.txt').unlink()",
                "sys.exit(3)",
            ]
        ),
    ]
    second_command = [
        sys.executable,
        "-u",
        "-c",
        "\n".join(
            [
                "from pathlib import Path",
                "Path('second-ran.txt').write_text('yes\\n', encoding='utf-8')",
                "print('second stdout', flush=True)",
            ]
        ),
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: first-fails
    argv: {json.dumps(first_command)}
  - name: second-still-runs
    argv: {json.dumps(second_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Ready for deterministic tests.",
        "changed_files": [],
        "recommended_commands": [],
    }
    codex_client = FakeCodexClient(
        planner_output, implementer_outputs=[implementer_output]
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)

    state_before_tests = json.loads(
        task_run.task_state_path.read_text(encoding="utf-8")
    )
    command_log_path = Path(state_before_tests["tasks"][0]["artifacts"]["command_log"])
    result_holder: dict[str, object] = {}

    def run_tests() -> None:
        result_holder["result"] = run_active_task_tests(task_run.task_state_path)

    worker = threading.Thread(target=run_tests)
    worker.start()
    deadline = time.monotonic() + 5.0
    streamed_before_exit = False
    while time.monotonic() < deadline:
        if (
            command_log_path.exists()
            and (target_repository / "first-running.txt").exists()
        ):
            log_text = command_log_path.read_text(encoding="utf-8")
            if "first stdout" in log_text and "first stderr" in log_text:
                streamed_before_exit = True
                break
        time.sleep(0.02)

    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert streamed_before_exit

    result = result_holder["result"]
    assert result["status"] == "failed"
    assert result["passed"] is False
    assert result["command_log_path"] == str(command_log_path)
    assert [
        (command["name"], command["exit_code"], command["status"])
        for command in result["command_results"]
    ] == [
        ("first-fails", 3, "failed"),
        ("second-still-runs", 0, "passed"),
    ]
    assert result["command_results"][0]["argv"] == first_command
    assert result["command_results"][1]["argv"] == second_command

    assert (target_repository / "cwd-proof.txt").read_text(encoding="utf-8") == (
        "ran in target\n"
    )
    assert (target_repository / "second-ran.txt").read_text(encoding="utf-8") == (
        "yes\n"
    )

    final_log_text = command_log_path.read_text(encoding="utf-8")
    first_start = final_log_text.index("===== test command START: first-fails =====")
    first_stdout = final_log_text.index("[stdout] first stdout")
    first_stderr = final_log_text.index("[stderr] first stderr")
    first_end = final_log_text.index("===== test command END: first-fails =====")
    second_start = final_log_text.index(
        "===== test command START: second-still-runs ====="
    )
    second_stdout = final_log_text.index("[stdout] second stdout")
    second_end = final_log_text.index("===== test command END: second-still-runs =====")
    assert (
        first_start
        < first_stdout
        < first_end
        < second_start
        < second_stdout
        < second_end
    )
    assert first_start < first_stderr < first_end
    assert f"argv: {json.dumps(first_command)}" in final_log_text
    assert f"argv: {json.dumps(second_command)}" in final_log_text
    assert "exit_code: 3" in final_log_text
    assert "exit_code: 0" in final_log_text

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    assert state["phase"] == "tests_failed"
    assert task_state["phase"] == "tests_failed"
    assert task_state["latest_test_status"] == result


def test_run_active_task_failed_test_repair_bypasses_review_and_reuses_implementer_thread(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    failing_command = [
        sys.executable,
        "-c",
        "import sys; print('failure output that stays in the log'); sys.exit(2)",
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
max_iterations: 2
test_commands:
  - name: unit
    argv: {json.dumps(failing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    first_implementation_result = {
        "status": "implementation_complete",
        "summary": "Initial implementation.",
        "changed_files": ["app.py"],
        "recommended_commands": [],
    }
    repair_implementation_result = {
        "status": "implementation_complete",
        "summary": "Repaired failing tests.",
        "changed_files": ["app.py", "tests/test_app.py"],
        "recommended_commands": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[
            first_implementation_result,
            repair_implementation_result,
        ],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    failed_tests = run_active_task_tests(task_run.task_state_path)

    result = run_active_task_failed_test_repair(task_run.task_state_path, codex_client)

    assert result == repair_implementation_result
    assert codex_client.resumed_threads[-1]["thread_id"] == "implementer-thread-1"
    repair_run_call = codex_client.threads_by_role["implementer"].run_calls[0]

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    approved_plan_path = Path(task_state["artifacts"]["approved_plan"])
    command_log_path = Path(task_state["artifacts"]["command_log"])
    implementation_result_path = Path(task_state["artifacts"]["implementation_result"])

    assert task_state["iterations"] == 1
    assert state["phase"] == "ready_for_tests"
    assert task_state["phase"] == "ready_for_tests"
    assert "deterministic test commands failed" in repair_run_call["input"]
    assert str(approved_plan_path) in repair_run_call["input"]
    assert str(command_log_path) in repair_run_call["input"]
    assert failed_tests["command_log_path"] == str(command_log_path)
    assert "failure output that stays in the log" not in repair_run_call["input"]
    assert json.loads(implementation_result_path.read_text(encoding="utf-8")) == (
        repair_implementation_result
    )
    assert all(
        "Reviewer Agent" not in str(call.get("developer_instructions"))
        for call in [*codex_client.started_threads, *codex_client.resumed_threads]
    )


def test_run_active_task_failed_test_repair_marks_task_run_failed_at_iteration_cap_without_reverting(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    failing_command = [sys.executable, "-c", "import sys; sys.exit(1)"]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
max_iterations: 1
test_commands:
  - name: unit
    argv: {json.dumps(failing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Left failed work for inspection.",
        "changed_files": ["attempt.txt"],
        "recommended_commands": [],
    }
    codex_client = FakeCodexClient(
        planner_output, implementer_outputs=[implementer_output]
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    dirty_path = target_repository / "attempt.txt"
    dirty_path.write_text("failed work remains\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)

    result = run_active_task_failed_test_repair(task_run.task_state_path, codex_client)

    assert result["status"] == "failed"
    assert result["reason"] == "max_iterations_reached"
    assert result["iterations"] == 1
    assert result["max_iterations"] == 1
    assert dirty_path.read_text(encoding="utf-8") == "failed work remains\n"
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "?? attempt.txt" in status.stdout
    assert codex_client.resumed_threads == []

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    first_task_state, second_task_state = state["tasks"]
    assert state["phase"] == "failed"
    assert state["active_task_id"] == "TASK-1"
    assert state["failure"]["active_task_id"] == "TASK-1"
    assert first_task_state["status"] == "failed"
    assert first_task_state["phase"] == "failed"
    assert first_task_state["iterations"] == 1
    assert first_task_state["failure"]["reason"] == "max_iterations_reached"
    assert second_task_state["status"] == "pending"
    assert second_task_state["phase"] == "pending"
    assert second_task_state["iterations"] == 0
    assert second_task_state["artifacts"] == {}


def test_run_active_task_reviewer_uses_fresh_read_only_threads_and_records_approved_reviews(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Implemented the approved plan.",
        "changed_files": ["app.py"],
        "recommended_commands": [],
    }
    first_review_output = {
        "status": "approved",
        "summary": "The task is ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [
            {
                "path": "app.py",
                "line": 12,
                "message": "Consider a follow-up cleanup.",
            }
        ],
    }
    second_review_output = {
        "status": "approved",
        "summary": "A fresh review also approves the current changes.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[first_review_output, second_review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    test_status = run_active_task_tests(task_run.task_state_path)

    first_result = run_active_task_reviewer(task_run.task_state_path, codex_client)
    second_result = run_active_task_reviewer(task_run.task_state_path, codex_client)

    assert test_status["passed"] is True
    assert first_result == first_review_output
    assert second_result == second_review_output

    reviewer_start_calls = [
        call
        for call in codex_client.started_threads
        if "Reviewer Agent" in call["developer_instructions"]
    ]
    assert len(reviewer_start_calls) == 2
    assert codex_client.resumed_threads == []
    for start_call in reviewer_start_calls:
        assert start_call["cwd"] == str(target_repository.resolve())
        assert sdk_value(start_call["approval_mode"]) == "deny_all"
        assert sdk_value(start_call["sandbox"]) == "read-only"
        assert start_call["model"] == "gpt-5-codex"

    reviewer_threads = codex_client.thread_history_by_role["reviewer"]
    assert [thread.id for thread in reviewer_threads] == [
        "reviewer-thread-1",
        "reviewer-thread-2",
    ]
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    artifacts = task_state["artifacts"]
    reviewer_run_call = reviewer_threads[0].run_calls[0]
    reviewer_input = reviewer_run_call["input"]
    assert "TASK-1" in reviewer_input
    assert "First task" in reviewer_input
    assert "Implement the first task." in reviewer_input
    assert str(Path(artifacts["task_context"])) in reviewer_input
    assert str(Path(artifacts["approved_plan"])) in reviewer_input
    assert str(Path(artifacts["command_log"])) in reviewer_input
    assert str(Path(artifacts["review_log"])) in reviewer_input
    assert "diff --git" not in reviewer_input
    assert reviewer_run_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(reviewer_run_call["approval_mode"]) == "deny_all"
    assert reviewer_run_call["sandbox_policy"].type == "readOnly"
    assert sdk_value(reviewer_run_call["effort"]) == "high"
    assert reviewer_run_call["output_schema"]["title"] == "ReviewerOutput"

    assert state["phase"] == "commit_ready"
    assert task_state["phase"] == "commit_ready"
    assert task_state["latest_review_output"] == second_review_output
    assert "reviewer" not in task_state["threads"]

    review_log_path = Path(artifacts["review_log"])
    review_log_entries = [
        json.loads(line)
        for line in review_log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert review_log_entries == [first_review_output, second_review_output]


def test_run_active_task_reviewer_requires_passing_deterministic_tests(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    failing_command = [sys.executable, "-c", "import sys; sys.exit(1)"]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: unit
    argv: {json.dumps(failing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Ready for deterministic tests.",
        "changed_files": [],
        "recommended_commands": [],
    }
    codex_client = FakeCodexClient(
        planner_output, implementer_outputs=[implementer_output]
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    failed_tests = run_active_task_tests(task_run.task_state_path)

    with pytest.raises(TaskRunError, match="did not pass"):
        run_active_task_reviewer(task_run.task_state_path, codex_client)

    assert failed_tests["passed"] is False
    assert "reviewer" not in codex_client.thread_history_by_role
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    review_log_path = Path(state["tasks"][0]["artifacts"]["review_log"])
    assert not review_log_path.exists()
    assert state["phase"] == "tests_failed"
    assert state["tasks"][0]["phase"] == "tests_failed"


def test_commit_active_task_commits_current_non_ignored_changes_and_advances_to_next_task(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    (target_repository / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (target_repository / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial target state"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )

    test_counter_path = tmp_path / "test-counter.txt"
    test_counter_path.write_text("0", encoding="utf-8")
    passing_command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            f"path = Path({str(test_counter_path)!r}); "
            "path.write_text(str(int(path.read_text(encoding='utf-8')) + 1), encoding='utf-8')"
        ),
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: unit
    argv: {json.dumps(passing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Changed tracked and untracked files.",
        "changed_files": ["tracked.txt", "created.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    (target_repository / "tracked.txt").write_text("after\n", encoding="utf-8")
    (target_repository / "created.txt").write_text("new file\n", encoding="utf-8")
    (target_repository / "ignored.log").write_text("ignored\n", encoding="utf-8")
    test_status = run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, codex_client)

    result = commit_active_task_and_advance(task_run.task_state_path)

    assert test_status["passed"] is True
    assert test_counter_path.read_text(encoding="utf-8") == "1"
    assert result["status"] == "advanced"
    assert result["completed_task_id"] == "TASK-1"
    assert result["active_task_id"] == "TASK-2"

    commit_subject = subprocess.run(
        ["git", "show", "-s", "--format=%s", "HEAD"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit_subject.startswith("TASK-1: First task")

    committed_files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "tracked.txt" in committed_files
    assert "created.txt" in committed_files
    assert "ignored.log" not in committed_files
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=target_repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    first_task_state, second_task_state = state["tasks"]
    assert state["phase"] == "ready_for_planning"
    assert state["active_task_id"] == "TASK-2"
    assert first_task_state["status"] == "completed"
    assert first_task_state["phase"] == "completed"
    assert first_task_state["commit_sha"] == result["commit_sha"]
    assert len(first_task_state["commit_sha"]) == 40
    assert second_task_state["status"] == "active"
    assert second_task_state["phase"] == "ready_for_planning"
    assert second_task_state["artifacts"]

    next_context_path = Path(second_task_state["artifacts"]["task_context"])
    next_context = json.loads(next_context_path.read_text(encoding="utf-8"))
    assert next_context["task"]["id"] == "TASK-2"
    assert next_context["task"]["title"] == "Second task"
    assert all(Path(path).is_absolute() for path in next_context["artifacts"].values())


def test_commit_active_task_excludes_untracked_issue_directory_source(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    (target_repository / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial target state"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    issue_directory = write_issue_directory(target_repository)
    task_run = start_task_run(issue_directory, runtime_root=tmp_path / "runs")

    mark_task_run_commit_ready(task_run)
    (target_repository / "done.txt").write_text("done\n", encoding="utf-8")

    result = commit_active_task_and_advance(task_run.task_state_path)

    assert result["status"] == "advanced"
    committed_files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "done.txt" in committed_files
    assert not any(path.startswith(".planning/") for path in committed_files)
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert ".planning/issues/cross-sectional-samples-collapse/" in status


def test_commit_active_task_keeps_tracked_issue_directory_changes(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    (target_repository / "README.md").write_text("initial\n", encoding="utf-8")
    issue_directory = write_issue_directory(target_repository)
    subprocess.run(
        ["git", "add", "README.md", ".planning"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial target state"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    task_run = start_task_run(issue_directory, runtime_root=tmp_path / "runs")

    mark_task_run_commit_ready(task_run)
    (target_repository / "done.txt").write_text("done\n", encoding="utf-8")
    (issue_directory / "README.md").write_text(
        "# Issue Breakdown: Collapse Cross-Sectional Samples Into Elastic-Net\n\n"
        "Clarified PRD context.\n",
        encoding="utf-8",
    )

    result = commit_active_task_and_advance(task_run.task_state_path)

    assert result["status"] == "advanced"
    committed_files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "done.txt" in committed_files
    assert (
        ".planning/issues/cross-sectional-samples-collapse/README.md" in committed_files
    )


def test_commit_active_task_marks_run_completed_when_no_next_task_exists(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Changed one file.",
        "changed_files": ["done.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    (target_repository / "done.txt").write_text("done\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, codex_client)

    result = commit_active_task_and_advance(task_run.task_state_path)

    assert result["status"] == "completed"
    assert result["completed_task_id"] == "TASK-1"
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    assert state["phase"] == "completed"
    assert state["active_task_id"] is None
    assert state["active_task"] is None
    assert task_state["status"] == "completed"
    assert task_state["phase"] == "completed"
    assert task_state["commit_sha"] == result["commit_sha"]


def test_commit_active_task_requires_clean_target_repository_before_activating_next_task(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    (target_repository / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "base.txt"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial target state"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    post_commit_hook = target_repository / ".git" / "hooks" / "post-commit"
    post_commit_hook.write_text(
        "#!/bin/sh\nprintf 'post-commit drift\\n' > hook-drift.txt\n",
        encoding="utf-8",
    )
    post_commit_hook.chmod(0o755)

    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Changed one file.",
        "changed_files": ["base.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    (target_repository / "base.txt").write_text("task change\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, codex_client)

    with pytest.raises(TaskRunError, match="before starting the next Task"):
        commit_active_task_and_advance(task_run.task_state_path)

    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "?? hook-drift.txt" in status

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    first_task_state, second_task_state = state["tasks"]
    assert state["phase"] == "target_repository_dirty_before_next_task"
    assert state["active_task_id"] == "TASK-1"
    assert first_task_state["status"] == "completed"
    assert first_task_state["phase"] == "completed"
    assert len(first_task_state["commit_sha"]) == 40
    assert second_task_state["status"] == "pending"
    assert second_task_state["phase"] == "pending"
    assert second_task_state["artifacts"] == {}


def test_commit_active_task_refuses_until_tests_pass_and_reviewer_approves(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Changed one file.",
        "changed_files": ["pending.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready to commit.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    (target_repository / "pending.txt").write_text("pending\n", encoding="utf-8")

    with pytest.raises(TaskRunError, match="not ready to commit"):
        commit_active_task_and_advance(task_run.task_state_path)

    run_active_task_tests(task_run.task_state_path)
    with pytest.raises(TaskRunError, match="not ready to commit"):
        commit_active_task_and_advance(task_run.task_state_path)

    run_active_task_reviewer(task_run.task_state_path, codex_client)
    result = commit_active_task_and_advance(task_run.task_state_path)

    assert result["status"] == "completed"


def test_run_active_task_review_rejection_repair_routes_verbatim_review_to_same_implementer_thread_and_back_to_tests(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path, require_plan_approval=False)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    initial_implementation_result = {
        "status": "implementation_complete",
        "summary": "Implemented the approved plan.",
        "changed_files": ["app.py"],
        "recommended_commands": [],
    }
    repair_implementation_result = {
        "status": "implementation_complete",
        "summary": "Addressed the reviewer feedback.",
        "changed_files": ["app.py", "tests/test_app.py"],
        "recommended_commands": [],
    }
    rejected_review_json = (
        '{"status":"rejected","summary":"Needs changes before commit.",'
        '"blocking_issues":[{"path":"app.py","line":4,'
        '"message":"Guard empty input before calling parse."}],'
        '"requested_changes":[{"path":"tests/test_app.py",'
        '"message":"Add coverage for empty input."}],'
        '"non_blocking_issues":[{"path":"README.md",'
        '"message":"Document the edge case later."}]}'
    )
    approved_review_output = {
        "status": "approved",
        "summary": "Ready to commit after the repair.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[
            initial_implementation_result,
            repair_implementation_result,
        ],
        reviewer_outputs=[rejected_review_json, approved_review_output],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    run_active_task_tests(task_run.task_state_path)

    rejected_review_output = run_active_task_reviewer(
        task_run.task_state_path, codex_client
    )
    repair_result = run_active_task_review_rejection_repair(
        task_run.task_state_path, codex_client
    )

    assert rejected_review_output == json.loads(rejected_review_json)
    assert repair_result == repair_implementation_result
    assert codex_client.resumed_threads[-1]["thread_id"] == "implementer-thread-1"
    repair_run_call = codex_client.threads_by_role["implementer"].run_calls[0]
    feedback_payload = repair_run_call["input"].split("Reviewer output:\n", 1)[1]
    assert feedback_payload == rejected_review_json
    assert (
        '"blocking_issues":[{"path":"app.py","line":4,'
        '"message":"Guard empty input before calling parse."}]'
    ) in feedback_payload
    assert (
        '"requested_changes":[{"path":"tests/test_app.py",'
        '"message":"Add coverage for empty input."}]'
    ) in feedback_payload
    assert (
        '"non_blocking_issues":[{"path":"README.md",'
        '"message":"Document the edge case later."}]'
    ) in feedback_payload

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    artifacts = task_state["artifacts"]
    implementation_result_path = Path(artifacts["implementation_result"])
    review_log_path = Path(artifacts["review_log"])

    assert state["phase"] == "ready_for_tests"
    assert task_state["phase"] == "ready_for_tests"
    assert task_state["iterations"] == 1
    assert task_state["latest_review_output"] == rejected_review_output
    assert task_state["latest_review_output_json"] == rejected_review_json
    assert review_log_path.read_text(encoding="utf-8") == f"{rejected_review_json}\n"
    assert json.loads(implementation_result_path.read_text(encoding="utf-8")) == (
        repair_implementation_result
    )

    reviewer_thread_count = len(codex_client.thread_history_by_role["reviewer"])
    with pytest.raises(TaskRunError, match="deterministic test"):
        run_active_task_reviewer(task_run.task_state_path, codex_client)
    assert len(codex_client.thread_history_by_role["reviewer"]) == reviewer_thread_count

    run_active_task_tests(task_run.task_state_path)
    approved_result = run_active_task_reviewer(task_run.task_state_path, codex_client)

    assert approved_result == approved_review_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    assert state["phase"] == "commit_ready"
    assert task_state["phase"] == "commit_ready"
    assert task_state["review_attempts"] == 2
    assert task_state["iterations"] == 1


def test_run_active_task_review_rejection_repair_marks_task_run_failed_at_iteration_cap_without_reverting(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
max_iterations: 1
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Left rejected work for inspection.",
        "changed_files": ["attempt.txt"],
        "recommended_commands": [],
    }
    rejected_review_json = (
        '{"status":"rejected","summary":"Still blocked.",'
        '"blocking_issues":[{"path":"attempt.txt","message":"Fix the task."}],'
        '"requested_changes":[{"path":"attempt.txt","message":"Rewrite this."}],'
        '"non_blocking_issues":[{"path":"notes.md","message":"Optional note."}]}'
    )
    codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[implementer_output],
        reviewer_outputs=[rejected_review_json],
    )
    plan_active_task(task_run.task_state_path, codex_client)
    run_active_task_implementer(task_run.task_state_path, codex_client)
    dirty_path = target_repository / "attempt.txt"
    dirty_path.write_text("rejected work remains\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, codex_client)

    result = run_active_task_review_rejection_repair(
        task_run.task_state_path, codex_client
    )

    assert result["status"] == "failed"
    assert result["reason"] == "max_iterations_reached"
    assert result["iterations"] == 1
    assert result["max_iterations"] == 1
    assert dirty_path.read_text(encoding="utf-8") == "rejected work remains\n"
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "?? attempt.txt" in status.stdout
    assert codex_client.resumed_threads == []

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    first_task_state, second_task_state = state["tasks"]
    review_log_path = Path(first_task_state["artifacts"]["review_log"])
    assert review_log_path.read_text(encoding="utf-8") == f"{rejected_review_json}\n"
    assert state["phase"] == "failed"
    assert state["active_task_id"] == "TASK-1"
    assert state["failure"]["active_task_id"] == "TASK-1"
    assert first_task_state["status"] == "failed"
    assert first_task_state["phase"] == "failed"
    assert first_task_state["iterations"] == 1
    assert first_task_state["failure"]["reason"] == "max_iterations_reached"
    assert second_task_state["status"] == "pending"
    assert second_task_state["phase"] == "pending"
    assert second_task_state["iterations"] == 0
    assert second_task_state["artifacts"] == {}


def test_resume_task_run_continues_dirty_active_task_without_rerunning_completed_tasks(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    (target_repository / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "base.txt"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial target state"],
        cwd=target_repository,
        check=True,
        capture_output=True,
    )

    test_counter_path = tmp_path / "test-counter.txt"
    test_counter_path.write_text("0", encoding="utf-8")
    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import sys; "
            f"path = Path({str(test_counter_path)!r}); "
            "count = int(path.read_text(encoding='utf-8')); "
            "path.write_text(str(count + 1), encoding='utf-8'); "
            "sys.exit(1 if count == 1 else 0)"
        ),
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: unit
    argv: {json.dumps(command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    prep_codex_client = FakeCodexClient(
        [
            {"status": "planned", "plan_markdown": "Plan Task 1."},
            {"status": "planned", "plan_markdown": "Plan Task 2."},
        ],
        implementer_outputs=[
            {
                "status": "implementation_complete",
                "summary": "Implemented Task 1.",
                "changed_files": ["task1.txt"],
                "recommended_commands": [],
            },
            {
                "status": "implementation_complete",
                "summary": "Implemented Task 2 before interruption.",
                "changed_files": ["task2.txt"],
                "recommended_commands": [],
            },
        ],
        reviewer_outputs=[
            {
                "status": "approved",
                "summary": "Task 1 is ready.",
                "blocking_issues": [],
                "requested_changes": [],
                "non_blocking_issues": [],
            }
        ],
    )

    plan_active_task(task_run.task_state_path, prep_codex_client)
    run_active_task_implementer(task_run.task_state_path, prep_codex_client)
    (target_repository / "task1.txt").write_text("task 1\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, prep_codex_client)
    commit_active_task_and_advance(task_run.task_state_path)
    plan_active_task(task_run.task_state_path, prep_codex_client)
    run_active_task_implementer(task_run.task_state_path, prep_codex_client)
    (target_repository / "task2.txt").write_text("task 2 dirty\n", encoding="utf-8")
    failed_tests = run_active_task_tests(task_run.task_state_path)
    interrupted_state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task2_implementer_thread_id = interrupted_state["tasks"][1]["threads"][
        "implementer"
    ]

    task_spec_path.write_text(
        "this replacement spec must not be read\n", encoding="utf-8"
    )
    resume_codex_client = FakeCodexClient(
        planner_output=[],
        implementer_outputs=[
            {
                "status": "implementation_complete",
                "summary": "Repaired Task 2 after resume.",
                "changed_files": ["task2.txt"],
                "recommended_commands": [],
            }
        ],
        reviewer_outputs=[
            {
                "status": "approved",
                "summary": "Task 2 is ready.",
                "blocking_issues": [],
                "requested_changes": [],
                "non_blocking_issues": [],
            }
        ],
    )

    result = resume_task_run(
        task_run.run_id,
        resume_codex_client,
        runtime_root=tmp_path / "runs",
    )

    assert failed_tests["passed"] is False
    assert result["status"] == "completed"
    assert result["completed_task_id"] == "TASK-2"
    assert test_counter_path.read_text(encoding="utf-8") == "3"
    assert [call["thread_id"] for call in resume_codex_client.resumed_threads] == [
        task2_implementer_thread_id
    ]
    assert all(
        "Reviewer Agent" in call["developer_instructions"]
        for call in resume_codex_client.started_threads
    )

    subjects = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=target_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert subjects[:2] == ["TASK-2: Second task", "TASK-1: First task"]

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    first_task_state, second_task_state = state["tasks"]
    assert state["phase"] == "completed"
    assert state["active_task_id"] is None
    assert first_task_state["status"] == "completed"
    assert first_task_state["commit_sha"]
    assert second_task_state["status"] == "completed"
    assert second_task_state["commit_sha"]
    assert second_task_state["iterations"] == 1
    assert second_task_state["threads"]["implementer"] == task2_implementer_thread_id


def test_resume_task_run_resumes_planning_threads_and_continues_to_commit(
    tmp_path: Path,
) -> None:
    _, task_run = create_single_task_run_with_passing_command(tmp_path)
    planner_output = {
        "status": "needs_answers",
        "questions": [{"id": "q1", "question": "Which path should change?"}],
    }
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    state["phase"] = "planning_needs_answers"
    state["tasks"][0]["phase"] = "planning_needs_answers"
    state["tasks"][0]["threads"] = {
        "context": "context-thread-existing",
        "planner": "planner-thread-existing",
    }
    task_run.task_state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    planning_artifact_path = Path(state["tasks"][0]["artifacts"]["planning"])
    planning_artifact_path.write_text(
        json.dumps(
            {"answer_batches": [], "planner_outputs": [planner_output]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Use the existing public resume path.",
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Use the active Task context artifact.",
                "reason": "The Task context names the artifacts.",
            }
        ]
    }
    implementer_output = {
        "status": "implementation_complete",
        "summary": "Implemented after resumed planning.",
        "changed_files": ["test-created.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready after resumed planning.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    codex_client = FakeCodexClient(
        [final_planner_output],
        context_outputs=[context_output],
        implementer_outputs=[implementer_output],
        reviewer_outputs=[review_output],
    )

    result = resume_task_run(
        task_run.run_id,
        codex_client,
        runtime_root=tmp_path / "runs",
    )

    assert result["status"] == "completed"
    assert [call["thread_id"] for call in codex_client.resumed_threads[:2]] == [
        "planner-thread-existing",
        "context-thread-existing",
    ]
    assert len(codex_client.started_threads) == 2
    assert any(
        "Implementer Agent" in call["developer_instructions"]
        for call in codex_client.started_threads
    )
    assert any(
        "Reviewer Agent" in call["developer_instructions"]
        for call in codex_client.started_threads
    )
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "completed"
    assert state["tasks"][0]["threads"]["planner"] == "planner-thread-existing"
    assert state["tasks"][0]["threads"]["context"] == "context-thread-existing"
    assert len(codex_client.threads_by_role["planner"].run_calls) == 1
    assert (
        "Use the active Task context artifact"
        in (codex_client.threads_by_role["planner"].run_calls[0]["input"])
    )


@pytest.mark.parametrize("phase", ["plan_approved", "ready_for_tests"])
def test_resume_task_run_continues_from_approved_plan_and_implementation_phases(
    tmp_path: Path, phase: str
) -> None:
    target_repository, task_run = create_single_task_run_with_passing_command(tmp_path)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    initial_implementation_output = {
        "status": "implementation_complete",
        "summary": "Initial implementation.",
        "changed_files": ["active.txt"],
        "recommended_commands": [],
    }
    prep_codex_client = FakeCodexClient(
        planner_output, implementer_outputs=[initial_implementation_output]
    )
    plan_active_task(task_run.task_state_path, prep_codex_client)
    if phase == "ready_for_tests":
        run_active_task_implementer(task_run.task_state_path, prep_codex_client)
        (target_repository / "active.txt").write_text(
            "active dirty work\n", encoding="utf-8"
        )

    resume_implementation_output = {
        "status": "implementation_complete",
        "summary": "Implemented after resume.",
        "changed_files": ["test-created.txt"],
        "recommended_commands": [],
    }
    review_output = {
        "status": "approved",
        "summary": "Ready after resume.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    resume_codex_client = FakeCodexClient(
        planner_output=[],
        implementer_outputs=[resume_implementation_output],
        reviewer_outputs=[review_output],
    )

    result = resume_task_run(
        task_run.run_id,
        resume_codex_client,
        runtime_root=tmp_path / "runs",
    )

    assert result["status"] == "completed"
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "completed"
    if phase == "plan_approved":
        assert any(
            "Implementer Agent" in call["developer_instructions"]
            for call in resume_codex_client.started_threads
        )
    else:
        assert all(
            "Implementer Agent" not in call["developer_instructions"]
            for call in resume_codex_client.started_threads
        )
        assert resume_codex_client.resumed_threads == []


def test_resume_task_run_continues_from_review_rejection_retry(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_single_task_run_with_passing_command(tmp_path)
    planner_output = {"status": "planned", "plan_markdown": "Make the change."}
    initial_implementation_output = {
        "status": "implementation_complete",
        "summary": "Initial implementation.",
        "changed_files": ["active.txt"],
        "recommended_commands": [],
    }
    rejected_review_output = {
        "status": "rejected",
        "summary": "Needs one repair.",
        "blocking_issues": [{"path": "active.txt", "message": "Fix it."}],
        "requested_changes": [{"path": "active.txt", "message": "Repair it."}],
        "non_blocking_issues": [],
    }
    prep_codex_client = FakeCodexClient(
        planner_output,
        implementer_outputs=[initial_implementation_output],
        reviewer_outputs=[rejected_review_output],
    )
    plan_active_task(task_run.task_state_path, prep_codex_client)
    run_active_task_implementer(task_run.task_state_path, prep_codex_client)
    (target_repository / "active.txt").write_text(
        "rejected dirty work\n", encoding="utf-8"
    )
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, prep_codex_client)
    rejected_state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    implementer_thread_id = rejected_state["tasks"][0]["threads"]["implementer"]

    repair_implementation_output = {
        "status": "implementation_complete",
        "summary": "Repaired after resume.",
        "changed_files": ["active.txt"],
        "recommended_commands": [],
    }
    approved_review_output = {
        "status": "approved",
        "summary": "Ready after repair.",
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }
    resume_codex_client = FakeCodexClient(
        planner_output=[],
        implementer_outputs=[repair_implementation_output],
        reviewer_outputs=[approved_review_output],
    )

    result = resume_task_run(
        task_run.run_id,
        resume_codex_client,
        runtime_root=tmp_path / "runs",
    )

    assert result["status"] == "completed"
    assert [call["thread_id"] for call in resume_codex_client.resumed_threads] == [
        implementer_thread_id
    ]
    assert all(
        "Reviewer Agent" in call["developer_instructions"]
        for call in resume_codex_client.started_threads
    )
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "completed"
    assert state["tasks"][0]["iterations"] == 1
    assert state["tasks"][0]["review_attempts"] == 2


def test_resume_task_run_requires_clean_repository_before_starting_next_task(
    tmp_path: Path,
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    test_counter_path = tmp_path / "next-task-test-counter.txt"
    test_counter_path.write_text("0", encoding="utf-8")
    passing_command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            f"counter = Path({str(test_counter_path)!r}); "
            "count = int(counter.read_text(encoding='utf-8')); "
            "counter.write_text(str(count + 1), encoding='utf-8'); "
            "Path('task2.txt').write_text('task 2\\n', encoding='utf-8') "
            "if count >= 1 else None"
        ),
    ]
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
require_plan_approval: false
test_commands:
  - name: unit
    argv: {json.dumps(passing_command)}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
  - id: TASK-2
    title: Second task
    prompt: Implement the second task.
""",
        encoding="utf-8",
    )
    task_run = start_task_run(task_spec_path, runtime_root=tmp_path / "runs")
    post_commit_hook = target_repository / ".git" / "hooks" / "post-commit"
    post_commit_hook.write_text(
        "#!/bin/sh\nprintf 'post-commit drift\\n' > hook-drift.txt\n",
        encoding="utf-8",
    )
    post_commit_hook.chmod(0o755)
    prep_codex_client = FakeCodexClient(
        {"status": "planned", "plan_markdown": "Make Task 1."},
        implementer_outputs=[
            {
                "status": "implementation_complete",
                "summary": "Implemented Task 1.",
                "changed_files": ["task1.txt"],
                "recommended_commands": [],
            }
        ],
        reviewer_outputs=[
            {
                "status": "approved",
                "summary": "Task 1 is ready.",
                "blocking_issues": [],
                "requested_changes": [],
                "non_blocking_issues": [],
            }
        ],
    )
    plan_active_task(task_run.task_state_path, prep_codex_client)
    run_active_task_implementer(task_run.task_state_path, prep_codex_client)
    (target_repository / "task1.txt").write_text("task 1\n", encoding="utf-8")
    run_active_task_tests(task_run.task_state_path)
    run_active_task_reviewer(task_run.task_state_path, prep_codex_client)
    with pytest.raises(TaskRunError, match="before starting the next Task"):
        commit_active_task_and_advance(task_run.task_state_path)

    resume_codex_client = FakeCodexClient(
        {"status": "planned", "plan_markdown": "Make Task 2."},
        implementer_outputs=[
            {
                "status": "implementation_complete",
                "summary": "Implemented Task 2.",
                "changed_files": ["task2.txt"],
                "recommended_commands": [],
            }
        ],
        reviewer_outputs=[
            {
                "status": "approved",
                "summary": "Task 2 is ready.",
                "blocking_issues": [],
                "requested_changes": [],
                "non_blocking_issues": [],
            }
        ],
    )
    with pytest.raises(TaskRunError, match="before starting the next Task"):
        resume_task_run(
            task_run.run_id,
            resume_codex_client,
            runtime_root=tmp_path / "runs",
        )
    assert resume_codex_client.started_threads == []

    (target_repository / "hook-drift.txt").unlink()
    result = resume_task_run(
        task_run.run_id,
        resume_codex_client,
        runtime_root=tmp_path / "runs",
    )

    assert result["status"] == "completed"
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "completed"
    assert [task["status"] for task in state["tasks"]] == ["completed", "completed"]


def test_plan_active_task_resumes_existing_planner_thread(tmp_path: Path) -> None:
    target_repository, task_run = create_task_run(tmp_path)
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["threads"] = {"planner": "planner-thread-existing"}
    task_run.task_state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    planner_output = {
        "status": "planned",
        "plan_markdown": "Resume the existing Planner Agent thread.",
    }
    codex_client = FakeCodexClient(planner_output)

    plan_active_task(task_run.task_state_path, codex_client)

    assert codex_client.started_threads == []
    assert len(codex_client.resumed_threads) == 1
    resume_call = codex_client.resumed_threads[0]
    assert resume_call["thread_id"] == "planner-thread-existing"
    assert "Planner Agent" in resume_call["developer_instructions"]
    assert resume_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(resume_call["approval_mode"]) == "auto_review"
    assert sdk_value(resume_call["sandbox"]) == "read-only"
    assert codex_client.resumed_thread is not None
    assert codex_client.resumed_thread.run_calls[0]["output_schema"]["title"] == (
        "PlannerOutput"
    )

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["tasks"][0]["threads"]["planner"] == "planner-thread-existing"


def test_plan_active_task_resolves_planner_questions_with_context_and_human_answers(
    tmp_path: Path,
) -> None:
    target_repository, task_run = create_task_run(tmp_path)
    first_planner_output = {
        "status": "needs_answers",
        "questions": [
            {
                "id": "q1",
                "context": "Need the current planning entrypoint.",
                "question": "Which public function should planning tests call?",
                "type": "repo_context",
            },
            {
                "id": "q2",
                "context": "Need human policy for this issue.",
                "question": "Should this slice implement plan approval?",
                "type": "human_policy",
            },
        ],
    }
    second_planner_output = {
        "status": "needs_answers",
        "questions": [
            {
                "id": "q3",
                "context": "Need Task State persistence details.",
                "question": "Where should the Context Agent thread ID be stored?",
                "type": "repo_context",
            }
        ],
    }
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Use plan_active_task and persist the Context Agent thread.",
    }
    first_context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Call plan_active_task through the controller module.",
                "reason": "The controller exposes planning through that public function.",
            },
            {
                "question_id": "q2",
                "status": "unresolved",
                "reason": "The Target Repository cannot answer approval policy.",
            },
        ]
    }
    second_context_output = {
        "answers": [
            {
                "question_id": "q3",
                "status": "answered",
                "answer": "Store it under the active Task State threads mapping.",
                "reason": "Planner thread IDs already use that Task State location.",
            }
        ]
    }
    codex_client = FakeCodexClient(
        [first_planner_output, second_planner_output, final_planner_output],
        context_outputs=[first_context_output, second_context_output],
    )
    human_batches: list[tuple[list[dict[str, object]], Path, Path]] = []

    def answer_from_human(
        unresolved_questions: list[dict[str, object]],
        context_artifact_path: Path,
        planning_artifact_path: Path,
    ) -> list[dict[str, str]]:
        human_batches.append(
            (unresolved_questions, context_artifact_path, planning_artifact_path)
        )
        return [
            {
                "question_id": "q2",
                "answer": "Do not implement plan approval in issue 03.",
            }
        ]

    result = plan_active_task(
        task_run.task_state_path,
        codex_client,
        human_answer_provider=answer_from_human,
    )

    assert result == final_planner_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    task_state = state["tasks"][0]
    assert state["phase"] == "plan_approved"
    assert task_state["phase"] == "plan_approved"
    assert task_state["threads"] == {
        "context": "context-thread-1",
        "planner": "planner-thread-1",
    }
    context_start_call = next(
        call
        for call in codex_client.started_threads
        if "Context Agent" in call["developer_instructions"]
    )
    assert context_start_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(context_start_call["approval_mode"]) == "auto_review"
    assert sdk_value(context_start_call["sandbox"]) == "read-only"
    assert context_start_call["model"] == "gpt-5-codex"

    planner_thread = codex_client.threads_by_role["planner"]
    assert len(planner_thread.run_calls) == 3
    assert "Call plan_active_task" in planner_thread.run_calls[1]["input"]
    assert "Do not implement plan approval" in planner_thread.run_calls[1]["input"]
    assert (
        "Store it under the active Task State threads mapping"
        in (planner_thread.run_calls[2]["input"])
    )

    context_thread = codex_client.threads_by_role["context"]
    assert len(context_thread.run_calls) == 2
    context_run_call = context_thread.run_calls[0]
    assert (
        "Which public function should planning tests call?" in context_run_call["input"]
    )
    assert str(task_run.first_task_context_path) in context_run_call["input"]
    planning_artifact_path = Path(task_state["artifacts"]["planning"])
    assert str(planning_artifact_path) in context_run_call["input"]
    assert context_run_call["cwd"] == str(target_repository.resolve())
    assert sdk_value(context_run_call["approval_mode"]) == "auto_review"
    assert context_run_call["sandbox_policy"].type == "readOnly"
    assert context_run_call["output_schema"]["title"] == "ContextAnswersOutput"

    assert len(human_batches) == 1
    unresolved_batch, context_artifact_path, human_planning_artifact_path = (
        human_batches[0]
    )
    assert unresolved_batch == [
        {
            "id": "q2",
            "context": "Need human policy for this issue.",
            "question": "Should this slice implement plan approval?",
            "type": "human_policy",
            "unresolved_reason": "The Target Repository cannot answer approval policy.",
        }
    ]
    assert context_artifact_path == task_run.first_task_context_path
    assert human_planning_artifact_path == planning_artifact_path

    planning_artifact = json.loads(planning_artifact_path.read_text(encoding="utf-8"))
    assert planning_artifact["planner_outputs"] == [
        first_planner_output,
        second_planner_output,
        final_planner_output,
    ]
    assert planning_artifact["answer_batches"] == [
        {
            "planner_questions": first_planner_output["questions"],
            "context_answers": first_context_output["answers"],
            "human_answers": [
                {
                    "question_id": "q2",
                    "answer": "Do not implement plan approval in issue 03.",
                }
            ],
        },
        {
            "planner_questions": second_planner_output["questions"],
            "context_answers": second_context_output["answers"],
            "human_answers": [],
        },
    ]


def test_plan_active_task_uses_context_answers_without_human_input(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path)
    planner_output = {
        "status": "needs_answers",
        "questions": [
            {
                "id": "q1",
                "context": "Need to know the existing public API.",
                "question": "Which function should expose this behavior?",
                "type": "repo_context",
            }
        ],
    }
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Use the controller planning function.",
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Expose the behavior through plan_active_task.",
                "reason": "That is the public planning entrypoint.",
            }
        ]
    }
    codex_client = FakeCodexClient(
        [planner_output, final_planner_output], context_outputs=[context_output]
    )

    result = plan_active_task(task_run.task_state_path, codex_client)

    assert result == final_planner_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "plan_approved"
    assert state["tasks"][0]["phase"] == "plan_approved"
    planning_artifact = json.loads(
        Path(state["tasks"][0]["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["planner_outputs"] == [
        planner_output,
        final_planner_output,
    ]
    assert planning_artifact["answer_batches"] == [
        {
            "planner_questions": planner_output["questions"],
            "context_answers": context_output["answers"],
            "human_answers": [],
        }
    ]


def test_plan_active_task_resumes_existing_context_thread(tmp_path: Path) -> None:
    _, task_run = create_task_run(tmp_path)
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["threads"] = {
        "context": "context-thread-existing",
        "planner": "planner-thread-existing",
    }
    task_run.task_state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    planner_output = {
        "status": "needs_answers",
        "questions": [
            {
                "id": "q1",
                "question": "Where should the Context Agent thread ID be stored?",
            }
        ],
    }
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Reuse the persisted Context Agent thread.",
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Store it in the active Task State threads mapping.",
                "reason": "That mapping already holds role thread IDs.",
            }
        ]
    }
    codex_client = FakeCodexClient(
        [planner_output, final_planner_output], context_outputs=[context_output]
    )

    plan_active_task(task_run.task_state_path, codex_client)

    assert codex_client.started_threads == []
    assert [call["thread_id"] for call in codex_client.resumed_threads] == [
        "planner-thread-existing",
        "context-thread-existing",
    ]
    context_resume_call = codex_client.resumed_threads[1]
    assert "Context Agent" in context_resume_call["developer_instructions"]
    assert sdk_value(context_resume_call["approval_mode"]) == "auto_review"
    assert sdk_value(context_resume_call["sandbox"]) == "read-only"

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["tasks"][0]["threads"] == {
        "context": "context-thread-existing",
        "planner": "planner-thread-existing",
    }


@pytest.mark.parametrize(
    ("planner_output", "message"),
    [
        ("not json", "unparseable JSON"),
        ({"status": "surprised"}, "Unknown Planner Agent status"),
    ],
)
def test_plan_active_task_rejects_unroutable_planner_output(
    tmp_path: Path, planner_output: object, message: str
) -> None:
    _, task_run = create_task_run(tmp_path)
    codex_client = FakeCodexClient(planner_output)

    with pytest.raises(PlannerOutputError, match=message):
        plan_active_task(task_run.task_state_path, codex_client)

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "ready_for_planning"
    assert state["tasks"][0]["phase"] == "ready_for_planning"
    assert state["tasks"][0]["threads"]["planner"] == "planner-thread-1"
    assert not Path(state["tasks"][0]["artifacts"]["planning"]).exists()


def test_plan_active_task_rejects_unroutable_context_output(tmp_path: Path) -> None:
    _, task_run = create_task_run(tmp_path)
    planner_output = {
        "status": "needs_answers",
        "questions": [{"id": "q1", "question": "Which path stores answers?"}],
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "guessed",
                "reason": "Not a valid routing status.",
            }
        ]
    }
    codex_client = FakeCodexClient([planner_output], context_outputs=[context_output])

    with pytest.raises(ContextOutputError, match="Unknown Context Agent answer status"):
        plan_active_task(task_run.task_state_path, codex_client)

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "planning_needs_answers"
    assert state["tasks"][0]["phase"] == "planning_needs_answers"
    assert state["tasks"][0]["threads"]["context"] == "context-thread-1"
    planning_artifact = json.loads(
        Path(state["tasks"][0]["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["planner_outputs"] == [planner_output]
    assert planning_artifact["answer_batches"] == []


def test_plan_active_task_rejects_malformed_human_answers(tmp_path: Path) -> None:
    _, task_run = create_task_run(tmp_path)
    planner_output = {
        "status": "needs_answers",
        "questions": [{"id": "q1", "question": "Should this wait for a human?"}],
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "unresolved",
                "reason": "The Target Repository cannot answer this.",
            }
        ]
    }
    codex_client = FakeCodexClient([planner_output], context_outputs=[context_output])

    def malformed_human_answers(
        _unresolved_questions: list[dict[str, object]],
        _context_artifact_path: Path,
        _planning_artifact_path: Path,
    ) -> list[dict[str, str]]:
        return [{"question_id": "wrong-id", "answer": "Use the issue scope."}]

    with pytest.raises(HumanAnswerError, match="unknown question_id"):
        plan_active_task(
            task_run.task_state_path,
            codex_client,
            human_answer_provider=malformed_human_answers,
        )

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    planning_artifact = json.loads(
        Path(state["tasks"][0]["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["planner_outputs"] == [planner_output]
    assert planning_artifact["answer_batches"] == []


def test_plan_active_task_rejects_unroutable_follow_up_planner_output(
    tmp_path: Path,
) -> None:
    _, task_run = create_task_run(tmp_path)
    planner_output = {
        "status": "needs_answers",
        "questions": [{"id": "q1", "question": "Which public interface is used?"}],
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Use plan_active_task.",
                "reason": "The controller exposes this function.",
            }
        ]
    }
    codex_client = FakeCodexClient(
        [planner_output, {"status": "surprised"}], context_outputs=[context_output]
    )

    with pytest.raises(PlannerOutputError, match="Unknown Planner Agent status"):
        plan_active_task(task_run.task_state_path, codex_client)

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    planning_artifact = json.loads(
        Path(state["tasks"][0]["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["planner_outputs"] == [planner_output]
    assert planning_artifact["answer_batches"] == [
        {
            "planner_questions": planner_output["questions"],
            "context_answers": context_output["answers"],
            "human_answers": [],
        }
    ]


def test_planner_prompt_and_output_schema_are_source_controlled() -> None:
    assert "Planner Agent" in PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(PLANNER_OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        {"status": "planned", "plan_markdown": "Do the scoped work."}, schema
    )
    jsonschema.validate(
        {
            "status": "needs_answers",
            "questions": [{"id": "q1", "question": "What should happen next?"}],
        },
        schema,
    )


def test_context_prompt_and_output_schema_are_source_controlled() -> None:
    assert "Context Agent" in CONTEXT_PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(CONTEXT_ANSWERS_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        {
            "answers": [
                {
                    "question_id": "q1",
                    "status": "answered",
                    "answer": "Use the public controller interface.",
                    "reason": "The code exposes that interface.",
                }
            ]
        },
        schema,
    )
    jsonschema.validate(
        {
            "answers": [
                {
                    "question_id": "q2",
                    "status": "unresolved",
                    "reason": "The repository cannot answer user policy.",
                }
            ]
        },
        schema,
    )


def test_implementer_prompt_and_result_schema_are_source_controlled() -> None:
    assert "Implementer Agent" in IMPLEMENTER_PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(IMPLEMENTER_RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        {
            "status": "implementation_complete",
            "summary": "Implemented the approved plan.",
            "changed_files": ["agent_control_plane/task_control_plane/controller.py"],
            "recommended_commands": [{"name": "unit", "argv": ["pytest", "-q"]}],
        },
        schema,
    )


def test_reviewer_prompt_and_output_schema_are_source_controlled() -> None:
    prompt = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    assert "Reviewer Agent" in prompt
    assert "Controller will commit all current Target Repository changes" in prompt
    assert "non-blocking issues do not prevent commit" in prompt
    schema = json.loads(REVIEWER_OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        {
            "status": "approved",
            "summary": "Ready to commit with one advisory note.",
            "blocking_issues": [],
            "requested_changes": [],
            "non_blocking_issues": [
                {"path": "app.py", "message": "Consider a follow-up cleanup."}
            ],
        },
        schema,
    )
    jsonschema.validate(
        {
            "status": "rejected",
            "summary": "Needs a requested change before commit.",
            "blocking_issues": [],
            "requested_changes": [
                {"path": "app.py", "message": "Add the missing empty-input guard."}
            ],
            "non_blocking_issues": [],
        },
        schema,
    )


def test_cli_run_requires_explicit_task_source_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["run"])

    assert exc_info.value.code == 2
    assert "task_source_path" in capsys.readouterr().err


def test_cli_resume_requires_task_run_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["resume"])

    assert exc_info.value.code == 2
    assert "run_id" in capsys.readouterr().err


def test_cli_resume_does_not_accept_replacement_task_spec_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["resume", "run-123", "task-spec.yaml"])

    assert exc_info.value.code == 2
    assert "unrecognized arguments: task-spec.yaml" in capsys.readouterr().err


def test_cli_run_starts_task_run_under_top_level_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
tasks:
  - id: TASK-1
    title: First task
    prompt: Implement the first task.
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(["run", str(task_spec_path)])

    assert exit_code == 0
    run_directories = list((tmp_path / "runs").iterdir())
    assert len(run_directories) == 1
    assert (run_directories[0] / "task-state.json").exists()
    assert "Started Task Run:" in capsys.readouterr().out
