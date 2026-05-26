import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from agent_control_plane.task_control_plane.cli import main
from agent_control_plane.task_control_plane.controller import (
    TaskRun,
    plan_active_task,
    resume_task_run,
    run_active_task_implementer,
    start_task_run,
)


class FakeCodexClient:
    def __init__(
        self,
        *,
        planner_turns: Iterable[object] = (),
        context_turns: Iterable[object] = (),
        implementer_turns: Iterable[object] = (),
        reviewer_turns: Iterable[object] = (),
    ) -> None:
        self.turns_by_role = {
            "planner": list(planner_turns),
            "context": list(context_turns),
            "implementer": list(implementer_turns),
            "reviewer": list(reviewer_turns),
        }
        self.started_threads: list[dict[str, object]] = []
        self.resumed_threads: list[dict[str, object]] = []
        self.thread_history_by_role: dict[str, list[FakeCodexThread]] = {}
        self.events: list[tuple[str, str, str]] = []

    def thread_start(self, **kwargs: object) -> "FakeCodexThread":
        role = self._role(kwargs)
        role_thread_count = len(self.thread_history_by_role.get(role, [])) + 1
        thread = FakeCodexThread(
            client=self,
            role=role,
            thread_id=f"{role}-thread-{role_thread_count}",
        )
        self.started_threads.append(kwargs)
        self.thread_history_by_role.setdefault(role, []).append(thread)
        self.events.append(("start", role, thread.id))
        return thread

    def thread_resume(self, thread_id: str, **kwargs: object) -> "FakeCodexThread":
        role = self._role(kwargs)
        thread = FakeCodexThread(client=self, role=role, thread_id=thread_id)
        self.resumed_threads.append({"thread_id": thread_id, **kwargs})
        self.thread_history_by_role.setdefault(role, []).append(thread)
        self.events.append(("resume", role, thread.id))
        return thread

    @staticmethod
    def _role(kwargs: dict[str, object]) -> str:
        developer_instructions = kwargs.get("developer_instructions")
        if not isinstance(developer_instructions, str):
            raise AssertionError("Fake Codex thread needs developer instructions.")
        for role, marker in (
            ("planner", "# Planner Agent"),
            ("context", "# Context Agent"),
            ("implementer", "# Implementer Agent"),
            ("reviewer", "# Reviewer Agent"),
        ):
            if developer_instructions.lstrip().startswith(marker):
                return role
        raise AssertionError("Fake Codex client could not identify the role.")


class FakeCodexThread:
    def __init__(self, *, client: FakeCodexClient, role: str, thread_id: str) -> None:
        self.client = client
        self.role = role
        self.id = thread_id
        self.run_calls: list[dict[str, object]] = []

    def run(self, input: str, **kwargs: object) -> "FakeCodexTurnResult":
        self.run_calls.append({"input": input, **kwargs})
        self.client.events.append(("run", self.role, self.id))
        turns = self.client.turns_by_role[self.role]
        if not turns:
            raise AssertionError(f"No queued {self.role} output for {self.id}.")

        turn = turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        if callable(turn):
            turn = turn(input, kwargs, self)
        return FakeCodexTurnResult(turn)


class FakeCodexTurnResult:
    def __init__(self, output: object) -> None:
        self.final_response = output if isinstance(output, str) else json.dumps(output)


def codex_turn(
    output: object,
    side_effect: Callable[[str, dict[str, object], FakeCodexThread], None] | None = None,
) -> Callable[[str, dict[str, object], FakeCodexThread], object]:
    def run_turn(
        turn_input: str, run_kwargs: dict[str, object], thread: FakeCodexThread
    ) -> object:
        if side_effect is not None:
            side_effect(turn_input, run_kwargs, thread)
        return output

    return run_turn


def configure_git_identity(repository: Path) -> None:
    subprocess.run(
        ["git", "config", "user.name", "Task Control Plane E2E Test"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "task-control-plane-e2e@example.test"],
        cwd=repository,
        check=True,
        capture_output=True,
    )


def init_target_repository(tmp_path: Path) -> Path:
    target_repository = tmp_path / "target"
    target_repository.mkdir()
    subprocess.run(
        ["git", "init"], cwd=target_repository, check=True, capture_output=True
    )
    configure_git_identity(target_repository)
    return target_repository


def write_task_spec(
    tmp_path: Path,
    target_repository: Path,
    *,
    tasks: list[tuple[str, str]] | None = None,
    test_commands: list[tuple[str, list[str]]] | None = None,
    max_iterations: int = 5,
) -> Path:
    task_spec_path = tmp_path / "task-spec.yaml"
    task_entries = tasks or [("TASK-1", "First task")]
    lines = [
        f"target_repository: {json.dumps(str(target_repository))}",
        "require_plan_approval: false",
        f"max_iterations: {max_iterations}",
    ]
    if test_commands is not None:
        lines.append("test_commands:")
        for name, argv in test_commands:
            lines.append(f"  - name: {name}")
            lines.append(f"    argv: {json.dumps(argv)}")
    lines.append("tasks:")
    for task_id, title in task_entries:
        lines.extend(
            [
                f"  - id: {task_id}",
                f"    title: {title}",
                f"    prompt: Implement {task_id}.",
            ]
        )
    task_spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return task_spec_path


def start_run(
    tmp_path: Path,
    target_repository: Path,
    *,
    tasks: list[tuple[str, str]] | None = None,
    test_commands: list[tuple[str, list[str]]] | None = None,
    max_iterations: int = 5,
) -> TaskRun:
    task_spec_path = write_task_spec(
        tmp_path,
        target_repository,
        tasks=tasks,
        test_commands=test_commands,
        max_iterations=max_iterations,
    )
    return start_task_run(task_spec_path, runtime_root=tmp_path / "runs")


def file_content_test_command(path: str, expected: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import sys; "
            f"path = Path({path!r}); "
            "actual = path.read_text(encoding='utf-8') if path.exists() else ''; "
            f"sys.exit(0 if actual == {expected!r} else 1)"
        ),
    ]


def passing_test_command() -> list[str]:
    return [sys.executable, "-c", "print('deterministic tests passed')"]


def write_target_file(path: str, content: str) -> Callable[..., None]:
    def side_effect(
        _turn_input: str, run_kwargs: dict[str, object], _thread: FakeCodexThread
    ) -> None:
        target_repository = Path(str(run_kwargs["cwd"]))
        target_path = target_repository / path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    return side_effect


def assert_latest_commit_starts_with(prefix: str) -> Callable[..., None]:
    def side_effect(
        _turn_input: str, run_kwargs: dict[str, object], _thread: FakeCodexThread
    ) -> None:
        subject = latest_commit_subjects(Path(str(run_kwargs["cwd"])))[0]
        assert subject.startswith(prefix)

    return side_effect


def latest_commit_subjects(repository: Path) -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def git_status(repository: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def read_state(task_run: TaskRun) -> dict[str, Any]:
    return json.loads(task_run.task_state_path.read_text(encoding="utf-8"))


def task_state(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for candidate in state["tasks"]:
        if candidate["id"] == task_id:
            return candidate
    raise AssertionError(f"Task State does not contain {task_id}.")


def assert_compact_artifacts(
    state: dict[str, Any],
    task_id: str,
    *,
    expected_existing: set[str] | None = None,
) -> None:
    expected_existing = expected_existing or {
        "task_context",
        "planning",
        "approved_plan",
        "implementation_result",
        "command_log",
        "review_log",
    }
    artifacts = task_state(state, task_id)["artifacts"]
    allowed_names = {
        "context.json",
        "planning.json",
        "approved-plan.md",
        "implementation-result.json",
        "command.log",
        "review.log",
    }
    for artifact_name in expected_existing:
        artifact_path = Path(artifacts[artifact_name])
        assert artifact_path.exists(), f"missing {artifact_name}"
        assert artifact_path.stat().st_size < 20_000, artifact_path

    artifact_files = [
        path for path in Path(artifacts["task_context"]).parent.iterdir() if path.is_file()
    ]
    assert len(artifact_files) <= len(allowed_names)
    assert {path.name for path in artifact_files} <= allowed_names


def approved_review(summary: str = "Ready to commit.") -> dict[str, object]:
    return {
        "status": "approved",
        "summary": summary,
        "blocking_issues": [],
        "requested_changes": [],
        "non_blocking_issues": [],
    }


def implementation_result(summary: str, changed_files: list[str]) -> dict[str, object]:
    return {
        "status": "implementation_complete",
        "summary": summary,
        "changed_files": changed_files,
        "recommended_commands": [],
    }


def run_id_from_cli_output(output: str) -> str:
    match = re.search(r"Started Task Run: (?P<run_id>\S+)", output)
    assert match is not None
    return match.group("run_id")


def test_cli_run_and_resume_complete_happy_path_without_real_codex_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_spec_path = write_task_spec(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("done.txt", "done\n"))],
    )
    monkeypatch.chdir(tmp_path)

    assert main(["run", str(task_spec_path)]) == 0
    run_id = run_id_from_cli_output(capsys.readouterr().out)
    fake_codex = FakeCodexClient(
        planner_turns=[{"status": "planned", "plan_markdown": "Write done.txt."}],
        implementer_turns=[
            codex_turn(
                implementation_result("Created the done file.", ["done.txt"]),
                write_target_file("done.txt", "done\n"),
            )
        ],
        reviewer_turns=[approved_review()],
    )

    assert main(["resume", run_id], codex_client_factory=lambda: fake_codex) == 0

    cli_output = capsys.readouterr().out
    assert "Status: completed" in cli_output
    state = json.loads(
        (tmp_path / "runs" / run_id / "task-state.json").read_text(encoding="utf-8")
    )
    assert state["phase"] == "completed"
    assert task_state(state, "TASK-1")["commit_sha"]
    assert latest_commit_subjects(target_repository)[0] == "TASK-1: First task"
    assert git_status(target_repository) == ""
    assert_compact_artifacts(state, "TASK-1")


def test_resume_task_run_answers_planner_questions_with_context_and_human_inputs(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("question.txt", "answered\n"))],
    )
    first_planner_output = {
        "status": "needs_answers",
        "questions": [
            {"id": "q1", "question": "Which file should prove completion?"},
            {"id": "q2", "question": "What human policy should be used?"},
        ],
    }
    final_planner_output = {
        "status": "planned",
        "plan_markdown": "Use the answered context and human policy.",
    }
    context_output = {
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "Write question.txt.",
                "reason": "The deterministic test command checks that path.",
            },
            {
                "question_id": "q2",
                "status": "unresolved",
                "reason": "Only the human can choose policy.",
            },
        ]
    }
    human_batches: list[list[dict[str, Any]]] = []
    fake_codex = FakeCodexClient(
        planner_turns=[first_planner_output, final_planner_output],
        context_turns=[context_output],
        implementer_turns=[
            codex_turn(
                implementation_result("Implemented answered plan.", ["question.txt"]),
                write_target_file("question.txt", "answered\n"),
            )
        ],
        reviewer_turns=[approved_review("Questions resolved and task is ready.")],
    )

    def answer_human_questions(
        unresolved_questions: list[dict[str, Any]],
        _task_context_path: Path,
        _planning_artifact_path: Path,
    ) -> list[dict[str, str]]:
        human_batches.append(unresolved_questions)
        return [{"question_id": "q2", "answer": "Keep the automated plan."}]

    result = resume_task_run(
        task_run.run_id,
        fake_codex,
        runtime_root=tmp_path / "runs",
        human_answer_provider=answer_human_questions,
    )

    assert result["status"] == "completed"
    state = read_state(task_run)
    planning_artifact = json.loads(
        Path(task_state(state, "TASK-1")["artifacts"]["planning"]).read_text(
            encoding="utf-8"
        )
    )
    assert human_batches == [
        [
            {
                "id": "q2",
                "question": "What human policy should be used?",
                "unresolved_reason": "Only the human can choose policy.",
            }
        ]
    ]
    assert planning_artifact["planner_outputs"] == [
        first_planner_output,
        final_planner_output,
    ]
    assert planning_artifact["answer_batches"][0]["context_answers"] == (
        context_output["answers"]
    )
    assert planning_artifact["answer_batches"][0]["human_answers"] == [
        {"question_id": "q2", "answer": "Keep the automated plan."}
    ]
    assert_compact_artifacts(state, "TASK-1")


def test_resume_task_run_failed_tests_bypass_review_and_retry_same_implementer(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("status.txt", "fixed\n"))],
    )
    fake_codex = FakeCodexClient(
        planner_turns=[{"status": "planned", "plan_markdown": "Repair until tests pass."}],
        implementer_turns=[
            codex_turn(
                implementation_result("Initial implementation is incomplete.", ["status.txt"]),
                write_target_file("status.txt", "broken\n"),
            ),
            codex_turn(
                implementation_result("Fixed the failing tests.", ["status.txt"]),
                write_target_file("status.txt", "fixed\n"),
            ),
        ],
        reviewer_turns=[approved_review("Ready after failed-test repair.")],
    )

    result = resume_task_run(
        task_run.run_id, fake_codex, runtime_root=tmp_path / "runs"
    )

    assert result["status"] == "completed"
    implementer_resume_calls = [
        call
        for call in fake_codex.resumed_threads
        if "Implementer Agent" in call["developer_instructions"]
    ]
    assert [call["thread_id"] for call in implementer_resume_calls] == [
        "implementer-thread-1"
    ]
    event_prefixes = [(event, role) for event, role, _thread_id in fake_codex.events]
    second_implementer_run = [
        index
        for index, event in enumerate(event_prefixes)
        if event == ("run", "implementer")
    ][1]
    first_reviewer_start = event_prefixes.index(("start", "reviewer"))
    assert second_implementer_run < first_reviewer_start
    state = read_state(task_run)
    assert task_state(state, "TASK-1")["iterations"] == 1
    command_log = Path(task_state(state, "TASK-1")["artifacts"]["command_log"])
    assert command_log.read_text(encoding="utf-8").count("test run START") == 2
    assert_compact_artifacts(state, "TASK-1")


def test_resume_task_run_reviewer_rejection_routes_verbatim_feedback_then_approves(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("review.txt", "ready\n"))],
    )
    rejected_review_json = (
        '{"status":"rejected","summary":"Needs exact repair.",'
        '"blocking_issues":[{"path":"review.txt","message":"Use ready."}],'
        '"requested_changes":[{"path":"review.txt","message":"Rewrite content."}],'
        '"non_blocking_issues":[{"path":"notes.md","message":"Optional note."}]}'
    )

    def repair_from_verbatim_review(
        turn_input: str, run_kwargs: dict[str, object], thread: FakeCodexThread
    ) -> None:
        assert thread.id == "implementer-thread-1"
        assert turn_input.split("Reviewer output:\n", 1)[1] == rejected_review_json
        write_target_file("review.txt", "ready\n")(turn_input, run_kwargs, thread)

    fake_codex = FakeCodexClient(
        planner_turns=[{"status": "planned", "plan_markdown": "Pass review."}],
        implementer_turns=[
            codex_turn(
                implementation_result("Initial review candidate.", ["review.txt"]),
                write_target_file("review.txt", "ready\n"),
            ),
            codex_turn(
                implementation_result("Addressed reviewer feedback.", ["review.txt"]),
                repair_from_verbatim_review,
            ),
        ],
        reviewer_turns=[
            rejected_review_json,
            approved_review("Ready after reviewer feedback."),
        ],
    )

    result = resume_task_run(
        task_run.run_id, fake_codex, runtime_root=tmp_path / "runs"
    )

    assert result["status"] == "completed"
    state = read_state(task_run)
    active_task = task_state(state, "TASK-1")
    assert active_task["iterations"] == 1
    assert active_task["review_attempts"] == 2
    assert [thread.id for thread in fake_codex.thread_history_by_role["reviewer"]] == [
        "reviewer-thread-1",
        "reviewer-thread-2",
    ]
    review_log_path = Path(active_task["artifacts"]["review_log"])
    assert review_log_path.read_text(encoding="utf-8").splitlines()[0] == (
        rejected_review_json
    )
    assert latest_commit_subjects(target_repository)[0] == "TASK-1: First task"
    assert_compact_artifacts(state, "TASK-1")


def test_resume_task_run_commits_each_task_before_starting_the_next_task(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        tasks=[("TASK-1", "First task"), ("TASK-2", "Second task")],
        test_commands=[("unit", passing_test_command())],
    )
    fake_codex = FakeCodexClient(
        planner_turns=[
            {"status": "planned", "plan_markdown": "Implement Task 1."},
            codex_turn(
                {"status": "planned", "plan_markdown": "Implement Task 2."},
                assert_latest_commit_starts_with("TASK-1: First task"),
            ),
        ],
        implementer_turns=[
            codex_turn(
                implementation_result("Implemented Task 1.", ["task1.txt"]),
                write_target_file("task1.txt", "task 1\n"),
            ),
            codex_turn(
                implementation_result("Implemented Task 2.", ["task2.txt"]),
                write_target_file("task2.txt", "task 2\n"),
            ),
        ],
        reviewer_turns=[
            approved_review("Task 1 is ready."),
            approved_review("Task 2 is ready."),
        ],
    )

    result = resume_task_run(
        task_run.run_id, fake_codex, runtime_root=tmp_path / "runs"
    )

    assert result["status"] == "completed"
    assert latest_commit_subjects(target_repository)[:2] == [
        "TASK-2: Second task",
        "TASK-1: First task",
    ]
    state = read_state(task_run)
    assert [task["status"] for task in state["tasks"]] == ["completed", "completed"]
    assert_compact_artifacts(state, "TASK-1")
    assert_compact_artifacts(state, "TASK-2")


def test_resume_task_run_continues_from_saved_state_without_rerunning_completed_phases(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("saved.txt", "saved\n"))],
    )
    prep_codex = FakeCodexClient(
        planner_turns=[{"status": "planned", "plan_markdown": "Write saved.txt."}],
        implementer_turns=[
            codex_turn(
                implementation_result("Prepared saved work.", ["saved.txt"]),
                write_target_file("saved.txt", "saved\n"),
            )
        ],
    )
    plan_active_task(task_run.task_state_path, prep_codex)
    run_active_task_implementer(task_run.task_state_path, prep_codex)
    interrupted_state = read_state(task_run)
    assert interrupted_state["phase"] == "ready_for_tests"

    resume_codex = FakeCodexClient(reviewer_turns=[approved_review("Saved work is ready.")])
    result = resume_task_run(
        task_run.run_id, resume_codex, runtime_root=tmp_path / "runs"
    )

    assert result["status"] == "completed"
    assert all(
        "Planner Agent" not in call["developer_instructions"]
        and "Implementer Agent" not in call["developer_instructions"]
        for call in [*resume_codex.started_threads, *resume_codex.resumed_threads]
    )
    state = read_state(task_run)
    assert state["phase"] == "completed"
    assert latest_commit_subjects(target_repository)[0] == "TASK-1: First task"
    assert_compact_artifacts(state, "TASK-1")


def test_resume_task_run_stops_at_max_iterations_and_leaves_target_repository_dirty(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        tasks=[("TASK-1", "First task"), ("TASK-2", "Second task")],
        test_commands=[("unit", file_content_test_command("attempt.txt", "passing\n"))],
        max_iterations=1,
    )
    fake_codex = FakeCodexClient(
        planner_turns=[{"status": "planned", "plan_markdown": "Attempt the task."}],
        implementer_turns=[
            codex_turn(
                implementation_result("Left failing work.", ["attempt.txt"]),
                write_target_file("attempt.txt", "still failing\n"),
            )
        ],
    )

    result = resume_task_run(
        task_run.run_id, fake_codex, runtime_root=tmp_path / "runs"
    )

    assert result["status"] == "failed"
    assert result["reason"] == "max_iterations_reached"
    assert "?? attempt.txt" in git_status(target_repository)
    assert "reviewer" not in fake_codex.thread_history_by_role
    state = read_state(task_run)
    assert state["phase"] == "failed"
    assert [task["status"] for task in state["tasks"]] == ["failed", "pending"]
    assert_compact_artifacts(
        state,
        "TASK-1",
        expected_existing={
            "task_context",
            "planning",
            "approved_plan",
            "implementation_result",
            "command_log",
        },
    )


def test_resume_task_run_records_controller_level_usage_limit_sleep_without_real_wait(
    tmp_path: Path,
) -> None:
    target_repository = init_target_repository(tmp_path)
    task_run = start_run(
        tmp_path,
        target_repository,
        test_commands=[("unit", file_content_test_command("usage.txt", "done\n"))],
    )
    fake_codex = FakeCodexClient(
        planner_turns=[
            RuntimeError(
                "Codex usage limit reached. Please try again at "
                "2026-05-27T14:05:00+10:00."
            ),
            {"status": "planned", "plan_markdown": "Continue after sleeping."},
        ],
        implementer_turns=[
            codex_turn(
                implementation_result("Implemented after wait.", ["usage.txt"]),
                write_target_file("usage.txt", "done\n"),
            )
        ],
        reviewer_turns=[approved_review("Ready after usage-limit wait.")],
    )
    sleeps: list[float] = []

    result = resume_task_run(
        task_run.run_id,
        fake_codex,
        runtime_root=tmp_path / "runs",
        usage_clock=lambda: __import__("datetime").datetime.fromisoformat(
            "2026-05-27T14:00:00+10:00"
        ),
        usage_sleep=sleeps.append,
    )

    assert result["status"] == "completed"
    assert sleeps == [300.0]
    state = read_state(task_run)
    usage_wait = state["usage_limit_waits"][0]
    assert usage_wait["role"] == "planner"
    assert usage_wait["sleep_seconds"] == 300.0
    assert usage_wait["suggested_retry_at"] == "2026-05-27T14:05:00+10:00"
    assert task_state(state, "TASK-1")["usage_limit_waits"] == [usage_wait]
    assert_compact_artifacts(state, "TASK-1")
