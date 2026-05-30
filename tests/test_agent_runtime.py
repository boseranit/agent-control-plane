from __future__ import annotations

import json
from pathlib import Path

import pytest
from agents.exceptions import ModelBehaviorError

from agent_control_plane.task_control_plane import agent_runtime
from agent_control_plane.task_control_plane.agent_runtime import (
    AgentRunConfig,
    AgentRuntime,
    _JsonSchemaOutput,
)
from agent_control_plane.task_control_plane.controller import _parse_planner_output


class FakeAgent:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls.append(kwargs)


class FakeSession:
    calls: list[dict[str, object]] = []

    def __init__(self, session_id: str, db_path: str | Path) -> None:
        self.session_id = session_id
        self.db_path = db_path
        self.closed = False
        self.calls.append({"session_id": session_id, "db_path": db_path})

    def close(self) -> None:
        self.closed = True


class FakeRunResult:
    def __init__(self, final_output: object) -> None:
        self.final_output = final_output


class FakeRunner:
    calls: list[dict[str, object]] = []
    final_output: object = {"status": "planned", "plan_markdown": "Do it."}

    @classmethod
    def run_sync(cls, agent: FakeAgent, input: str, **kwargs: object) -> FakeRunResult:
        cls.calls.append({"agent": agent, "input": input, **kwargs})
        return FakeRunResult(cls.final_output)


@pytest.fixture(autouse=True)
def fake_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAgent.calls = []
    FakeSession.calls = []
    FakeRunner.calls = []
    FakeRunner.final_output = {"status": "planned", "plan_markdown": "Do it."}
    monkeypatch.setattr(agent_runtime, "Agent", FakeAgent)
    monkeypatch.setattr(agent_runtime, "Runner", FakeRunner)
    monkeypatch.setattr(agent_runtime, "SQLiteSession", FakeSession)


def test_agent_runtime_starts_thread_and_runs_agents_session(
    tmp_path: Path,
) -> None:
    runtime = AgentRuntime(
        thread_id_factory=lambda role: f"{role}-thread-1",
        session_db_path=tmp_path / "sessions.sqlite3",
    )
    schema = {"title": "PlannerOutput", "type": "object"}

    thread = runtime.open_thread(
        AgentRunConfig(
            role="planner",
            cwd=tmp_path,
            developer_instructions="# Planner Agent",
            model="gpt-5-codex",
        )
    )
    result = thread.run(
        "plan",
        AgentRunConfig(
            role="planner",
            cwd=tmp_path,
            effort="high",
            model="gpt-5-codex",
            output_schema=schema,
        ),
    )

    assert thread.id == "planner-thread-1"
    assert FakeSession.calls == [
        {"session_id": "planner-thread-1", "db_path": tmp_path / "sessions.sqlite3"}
    ]
    agent_call = FakeAgent.calls[0]
    assert agent_call["name"] == "task-control-planner"
    assert agent_call["model"] == "gpt-5-codex"
    assert "Planner Agent" in str(agent_call["instructions"])
    assert len(agent_call["tools"]) == 3
    assert agent_call["output_type"].json_schema() == schema
    assert FakeRunner.calls[0]["input"] == "plan"
    assert _parse_planner_output(result) == {
        "status": "planned",
        "plan_markdown": "Do it.",
    }


def test_agent_runtime_resumes_existing_thread_and_enables_implementer_tools(
    tmp_path: Path,
) -> None:
    runtime = AgentRuntime(thread_id_factory=lambda role: f"{role}-new")

    thread = runtime.open_thread(
        AgentRunConfig(
            role="implementer",
            cwd=tmp_path,
            thread_id="implementer-existing",
            developer_instructions="# Implementer Agent",
            session_db_path=tmp_path / "run-sessions.sqlite3",
        )
    )
    thread.run(
        "implement",
        AgentRunConfig(role="implementer", cwd=tmp_path, effort="xhigh"),
    )

    assert thread.id == "implementer-existing"
    assert FakeSession.calls[0] == {
        "session_id": "implementer-existing",
        "db_path": tmp_path / "run-sessions.sqlite3",
    }
    agent_call = FakeAgent.calls[0]
    assert len(agent_call["tools"]) == 5
    tool_names = [tool.name for tool in agent_call["tools"]]
    assert tool_names == [
        "read_file",
        "list_files",
        "search_text",
        "shell",
        "apply_patch",
    ]
    assert agent_call["model_settings"].reasoning.effort == "xhigh"


def test_json_schema_output_validates_and_round_trips() -> None:
    output = _JsonSchemaOutput(
        {
            "title": "PlannerOutput",
            "type": "object",
            "properties": {"status": {"const": "planned"}},
            "required": ["status"],
        }
    )

    assert output.name() == "PlannerOutput"
    assert output.validate_json('{"status": "planned"}') == {"status": "planned"}
    with pytest.raises(ModelBehaviorError):
        output.validate_json('{"status": "needs_answers"}')


def test_agent_turn_result_final_response_parses_like_controller_output(
    tmp_path: Path,
) -> None:
    FakeRunner.final_output = {"status": "planned", "plan_markdown": "Do it."}
    thread = AgentRuntime(thread_id_factory=lambda _role: "thread-1").open_thread(
        AgentRunConfig(role="planner", cwd=tmp_path)
    )

    result = thread.run(
        "plan",
        AgentRunConfig(
            role="planner",
            cwd=tmp_path,
            output_schema={"title": "PlannerOutput", "type": "object"},
        ),
    )

    assert json.loads(result.final_response) == {
        "status": "planned",
        "plan_markdown": "Do it.",
    }


def test_openai_codex_import_is_removed_from_package() -> None:
    package_root = Path("agent_control_plane/task_control_plane")
    offenders = [
        path
        for path in package_root.glob("*.py")
        if "openai_codex" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
