import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from agent_control_plane.task_control_plane.cli import main
from agent_control_plane.task_control_plane.controller import (
    PLANNER_OUTPUT_SCHEMA_PATH,
    PLANNER_PROMPT_PATH,
    PlannerOutputError,
    TaskRun,
    TaskRunError,
    plan_active_task,
    start_task_run,
)
from agent_control_plane.task_control_plane.task_spec import TaskSpecError
from agent_control_plane.task_control_plane.task_spec import load_task_spec


class FakeCodexClient:
    def __init__(self, planner_output: object) -> None:
        self.started_threads: list[dict[str, object]] = []
        self.resumed_threads: list[dict[str, object]] = []
        self.started_thread = FakeCodexThread("planner-thread-1", planner_output)
        self.resumed_thread: FakeCodexThread | None = None

    def thread_start(self, **kwargs: object) -> "FakeCodexThread":
        self.started_threads.append(kwargs)
        return self.started_thread

    def thread_resume(self, thread_id: str, **kwargs: object) -> "FakeCodexThread":
        self.resumed_threads.append({"thread_id": thread_id, **kwargs})
        self.resumed_thread = FakeCodexThread(
            thread_id, self.started_thread.planner_output
        )
        return self.resumed_thread


class FakeCodexThread:
    def __init__(self, thread_id: str, planner_output: object) -> None:
        self.id = thread_id
        self.planner_output = planner_output
        self.run_calls: list[dict[str, object]] = []

    def run(self, input: str, **kwargs: object) -> object:
        self.run_calls.append({"input": input, **kwargs})
        return FakeCodexTurnResult(self.planner_output)


class FakeCodexTurnResult:
    def __init__(self, planner_output: object) -> None:
        self.final_response = (
            planner_output
            if isinstance(planner_output, str)
            else json.dumps(planner_output)
        )


def sdk_value(value: object) -> object:
    return getattr(value, "value", value)


def create_task_run(tmp_path: Path) -> tuple[Path, TaskRun]:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )

    task_spec_path = tmp_path / "task-spec.yaml"
    task_spec_path.write_text(
        f"""
target_repository: {target_repository}
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
    target_repository, task_run = create_task_run(tmp_path)
    planner_output = {
        "status": "planned",
        "plan_markdown": "1. Inspect the existing code.\n2. Make the scoped change.",
    }
    codex_client = FakeCodexClient(planner_output)

    result = plan_active_task(task_run.task_state_path, codex_client)

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
    assert state["phase"] == "plan_ready"
    assert task_state["phase"] == "plan_ready"
    assert task_state["threads"]["planner"] == "planner-thread-1"

    planning_artifact_path = Path(task_state["artifacts"]["planning"])
    planning_artifact = json.loads(planning_artifact_path.read_text(encoding="utf-8"))
    assert planning_artifact["planner_outputs"] == [planner_output]


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


def test_plan_active_task_pauses_when_planner_needs_answers(tmp_path: Path) -> None:
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
    codex_client = FakeCodexClient(planner_output)

    result = plan_active_task(task_run.task_state_path, codex_client)

    assert result == planner_output
    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "planning_needs_answers"
    assert state["tasks"][0]["phase"] == "planning_needs_answers"
    planning_artifact = json.loads(
        Path(state["tasks"][0]["artifacts"]["planning"]).read_text(encoding="utf-8")
    )
    assert planning_artifact["planner_outputs"] == [planner_output]


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


def test_cli_run_requires_explicit_task_spec_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["run"])

    assert exc_info.value.code == 2
    assert "task_spec_path" in capsys.readouterr().err


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
