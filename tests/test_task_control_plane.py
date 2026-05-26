import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from agent_control_plane.task_control_plane.cli import main
from agent_control_plane.task_control_plane.controller import (
    CONTEXT_ANSWERS_SCHEMA_PATH,
    CONTEXT_PROMPT_PATH,
    PLANNER_OUTPUT_SCHEMA_PATH,
    PLANNER_PROMPT_PATH,
    ContextOutputError,
    HumanAnswerError,
    PlannerOutputError,
    TaskRun,
    TaskRunError,
    build_implementer_turn_input,
    plan_active_task,
    start_task_run,
)
from agent_control_plane.task_control_plane.task_spec import TaskSpecError
from agent_control_plane.task_control_plane.task_spec import load_task_spec


class FakeCodexClient:
    def __init__(
        self,
        planner_output: object | list[object],
        context_outputs: list[object] | None = None,
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
        }
        self.started_thread: FakeCodexThread | None = None
        self.resumed_thread: FakeCodexThread | None = None
        self.threads_by_role: dict[str, FakeCodexThread] = {}

    def thread_start(self, **kwargs: object) -> "FakeCodexThread":
        self.started_threads.append(kwargs)
        role = self._role(kwargs)
        thread = FakeCodexThread(f"{role}-thread-1", self.outputs_by_role[role])
        self.threads_by_role[role] = thread
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
            and "Context Agent" in developer_instructions
        ):
            return "context"
        if (
            isinstance(developer_instructions, str)
            and "Planner Agent" in developer_instructions
        ):
            return "planner"
        raise AssertionError("FakeCodexClient could not identify thread role.")


class FakeCodexThread:
    def __init__(self, thread_id: str, outputs: list[object]) -> None:
        self.id = thread_id
        self.outputs = outputs
        self.run_calls: list[dict[str, object]] = []

    def run(self, input: str, **kwargs: object) -> object:
        self.run_calls.append({"input": input, **kwargs})
        if not self.outputs:
            raise AssertionError(f"No queued output for thread {self.id}.")
        return FakeCodexTurnResult(self.outputs.pop(0))


class FakeCodexTurnResult:
    def __init__(self, planner_output: object) -> None:
        self.final_response = (
            planner_output
            if isinstance(planner_output, str)
            else json.dumps(planner_output)
        )


def sdk_value(value: object) -> object:
    return getattr(value, "value", value)


def create_task_run(
    tmp_path: Path, *, require_plan_approval: bool = False
) -> tuple[Path, TaskRun]:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )

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
