from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.control_plane import agent_runtime
from agent_control_plane.control_plane.agent_runtime import (
    AgentRunConfig,
    AgentRuntime,
    RuntimePolicy,
)


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
    final_output: object = {"status": "ok"}

    @classmethod
    def run_sync(cls, agent: FakeAgent, input: str, **kwargs: object) -> FakeRunResult:
        cls.calls.append({"agent": agent, "input": input, **kwargs})
        return FakeRunResult(cls.final_output)


@pytest.fixture(autouse=True)
def fake_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAgent.calls = []
    FakeSession.calls = []
    FakeRunner.calls = []
    FakeRunner.final_output = {"status": "ok"}
    monkeypatch.setattr(agent_runtime, "Agent", FakeAgent)
    monkeypatch.setattr(agent_runtime, "Runner", FakeRunner)
    monkeypatch.setattr(agent_runtime, "SQLiteSession", FakeSession)


def test_shared_agent_runtime_accepts_arbitrary_read_only_role(
    tmp_path: Path,
) -> None:
    runtime = AgentRuntime(
        thread_id_factory=lambda role: f"{role}-thread-1",
        session_db_path=tmp_path / "sessions.sqlite3",
    )

    thread = runtime.open_thread(
        AgentRunConfig(
            role="strategist",
            cwd=tmp_path,
            developer_instructions="# Strategist Agent",
            model="gpt-5-codex",
            policy=RuntimePolicy.READ_ONLY,
        )
    )
    result = thread.run("plan", AgentRunConfig(role="strategist", cwd=tmp_path))

    assert result.final_response == '{"status": "ok"}'
    assert thread.id == "strategist-thread-1"
    assert FakeSession.calls == [
        {"session_id": "strategist-thread-1", "db_path": tmp_path / "sessions.sqlite3"}
    ]
    agent_call = FakeAgent.calls[0]
    assert agent_call["name"] == "control-plane-strategist"
    assert "Strategist Agent" in str(agent_call["instructions"])
    assert [tool.name for tool in agent_call["tools"]] == [
        "read_file",
        "list_files",
        "search_text",
    ]


def test_shared_agent_runtime_enables_workspace_write_policy(
    tmp_path: Path,
) -> None:
    thread = AgentRuntime(thread_id_factory=lambda _role: "evaluator-new").open_thread(
        AgentRunConfig(
            role="evaluator",
            cwd=tmp_path,
            thread_id="evaluator-existing",
            policy=RuntimePolicy.WORKSPACE_WRITE,
        )
    )

    thread.run("evaluate", AgentRunConfig(role="evaluator", cwd=tmp_path))

    assert thread.id == "evaluator-existing"
    assert [tool.name for tool in FakeAgent.calls[0]["tools"]] == [
        "read_file",
        "list_files",
        "search_text",
        "shell",
        "apply_patch",
    ]


def test_shared_agent_runtime_run_config_can_override_thread_policy(
    tmp_path: Path,
) -> None:
    thread = AgentRuntime(thread_id_factory=lambda role: f"{role}-thread").open_thread(
        AgentRunConfig(
            role="critic",
            cwd=tmp_path,
            policy=RuntimePolicy.READ_ONLY,
        )
    )

    thread.run(
        "repair",
        AgentRunConfig(
            role="critic",
            cwd=tmp_path,
            policy=RuntimePolicy.WORKSPACE_WRITE,
        ),
    )

    assert thread.id == "critic-thread"
    assert [tool.name for tool in FakeAgent.calls[0]["tools"]] == [
        "read_file",
        "list_files",
        "search_text",
        "shell",
        "apply_patch",
    ]
