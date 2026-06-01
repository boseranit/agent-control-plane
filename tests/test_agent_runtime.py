from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane.agent_runtime import (
    AgentTurnResult,
    RuntimeApproval,
    RuntimePolicy,
)
from agent_control_plane.task_control_plane import agent_runtime as task_agent_runtime
from agent_control_plane.task_control_plane.agent_runtime import (
    AgentRunConfig,
    AgentRuntime,
)
from agent_control_plane.task_control_plane.controller import _parse_planner_output


class FakeSharedRuntime:
    instances: list["FakeSharedRuntime"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.open_configs = []
        self.threads: list[FakeSharedThread] = []
        self.entered = False
        self.exited = False
        self.instances.append(self)

    def __enter__(self) -> "FakeSharedRuntime":
        self.entered = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.exited = True

    def open_thread(self, config) -> "FakeSharedThread":
        self.open_configs.append(config)
        thread = FakeSharedThread(config.thread_id or f"{config.role}-thread-1")
        self.threads.append(thread)
        return thread


class FakeSharedThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.run_calls = []

    def run(self, input: str, config) -> AgentTurnResult:
        self.run_calls.append({"input": input, "config": config})
        return AgentTurnResult(
            final_response='{"status": "planned", "plan_markdown": "Do it."}'
        )


def fake_shared_runtime(monkeypatch) -> type[FakeSharedRuntime]:
    FakeSharedRuntime.instances = []
    monkeypatch.setattr(task_agent_runtime, "SharedAgentRuntime", FakeSharedRuntime)
    return FakeSharedRuntime


def test_task_agent_runtime_maps_planner_to_read_only_auto_review(
    tmp_path: Path, monkeypatch
) -> None:
    fake_runtime = fake_shared_runtime(monkeypatch)
    schema = {"title": "PlannerOutput", "type": "object"}

    runtime = AgentRuntime(session_db_path=tmp_path / "sessions.sqlite3")
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
            output_schema=schema,
        ),
    )

    shared_runtime = fake_runtime.instances[0]
    assert shared_runtime.kwargs["session_db_path"] == tmp_path / "sessions.sqlite3"
    open_config = shared_runtime.open_configs[0]
    assert open_config.policy is RuntimePolicy.READ_ONLY
    assert open_config.approval is RuntimeApproval.AUTO_REVIEW
    assert open_config.developer_instructions == "# Planner Agent"
    assert open_config.model == "gpt-5-codex"

    run_config = shared_runtime.threads[0].run_calls[0]["config"]
    assert run_config.policy is RuntimePolicy.READ_ONLY
    assert run_config.approval is RuntimeApproval.AUTO_REVIEW
    assert run_config.effort == "high"
    assert run_config.output_schema == schema
    assert _parse_planner_output(result) == {
        "status": "planned",
        "plan_markdown": "Do it.",
    }


def test_task_agent_runtime_maps_implementer_to_workspace_write(
    tmp_path: Path, monkeypatch
) -> None:
    fake_runtime = fake_shared_runtime(monkeypatch)

    runtime = AgentRuntime()
    thread = runtime.open_thread(
        AgentRunConfig(
            role="implementer",
            cwd=tmp_path,
            thread_id="implementer-existing",
        )
    )
    thread.run("implement", AgentRunConfig(role="implementer", cwd=tmp_path))

    shared_runtime = fake_runtime.instances[0]
    assert thread.id == "implementer-existing"
    assert shared_runtime.open_configs[0].policy is RuntimePolicy.WORKSPACE_WRITE
    assert shared_runtime.open_configs[0].approval is RuntimeApproval.AUTO_REVIEW
    run_config = shared_runtime.threads[0].run_calls[0]["config"]
    assert run_config.policy is RuntimePolicy.WORKSPACE_WRITE
    assert run_config.approval is RuntimeApproval.AUTO_REVIEW


def test_task_agent_runtime_maps_reviewer_to_deny_all(
    tmp_path: Path, monkeypatch
) -> None:
    fake_runtime = fake_shared_runtime(monkeypatch)

    runtime = AgentRuntime()
    thread = runtime.open_thread(AgentRunConfig(role="reviewer", cwd=tmp_path))
    thread.run("review", AgentRunConfig(role="reviewer", cwd=tmp_path))

    shared_runtime = fake_runtime.instances[0]
    assert shared_runtime.open_configs[0].policy is RuntimePolicy.READ_ONLY
    assert shared_runtime.open_configs[0].approval is RuntimeApproval.DENY_ALL
    run_config = shared_runtime.threads[0].run_calls[0]["config"]
    assert run_config.policy is RuntimePolicy.READ_ONLY
    assert run_config.approval is RuntimeApproval.DENY_ALL


def test_task_agent_runtime_context_manager_delegates(monkeypatch) -> None:
    fake_runtime = fake_shared_runtime(monkeypatch)

    with AgentRuntime():
        pass

    shared_runtime = fake_runtime.instances[0]
    assert shared_runtime.entered is True
    assert shared_runtime.exited is True


def test_source_imports_no_agents_or_openai_types() -> None:
    offenders = []
    for path in Path("agent_control_plane").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from agents" in text or "import agents" in text or "openai.types" in text:
            offenders.append(path)

    assert offenders == []


def test_openai_agents_dependency_is_removed() -> None:
    assert "openai-agents" not in Path("pixi.toml").read_text(encoding="utf-8")
