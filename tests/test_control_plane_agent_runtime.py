from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane.agent_runtime import (
    AgentRunConfig,
    AgentRuntime,
    RuntimeApproval,
    RuntimePolicy,
)


class FakeCodex:
    def __init__(self) -> None:
        self.started_threads: list[dict[str, object]] = []
        self.resumed_threads: list[dict[str, object]] = []
        self.closed = False

    def thread_start(self, **kwargs: object) -> "FakeCodexThread":
        self.started_threads.append(kwargs)
        return FakeCodexThread(f"thread-{len(self.started_threads)}")

    def thread_resume(self, thread_id: str, **kwargs: object) -> "FakeCodexThread":
        self.resumed_threads.append({"thread_id": thread_id, **kwargs})
        return FakeCodexThread(thread_id)

    def close(self) -> None:
        self.closed = True


class FakeCodexThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.run_calls: list[dict[str, object]] = []

    def run(self, input: str, **kwargs: object) -> object:
        self.run_calls.append({"input": input, **kwargs})
        return type("TurnResult", (), {"final_response": '{"status": "ok"}'})()


def sdk_value(value: object) -> object:
    return getattr(value, "value", value)


def test_shared_agent_runtime_starts_read_only_codex_thread(tmp_path: Path) -> None:
    codex = FakeCodex()
    runtime = AgentRuntime(codex_client=codex)
    schema = {"title": "StrategistOutput", "type": "object"}

    thread = runtime.open_thread(
        AgentRunConfig(
            role="strategist",
            cwd=tmp_path,
            developer_instructions="# Strategist Agent",
            model="gpt-5-codex",
            policy=RuntimePolicy.READ_ONLY,
        )
    )
    result = thread.run(
        "plan",
        AgentRunConfig(
            role="strategist",
            cwd=tmp_path,
            effort="high",
            output_schema=schema,
        ),
    )

    assert result.final_response == '{"status": "ok"}'
    assert thread.id == "thread-1"
    assert len(codex.started_threads) == 1
    start_call = codex.started_threads[0]
    assert start_call["cwd"] == str(tmp_path.resolve())
    assert start_call["developer_instructions"] == "# Strategist Agent"
    assert start_call["model"] == "gpt-5-codex"
    assert sdk_value(start_call["approval_mode"]) == "auto_review"
    assert sdk_value(start_call["sandbox"]) == "read-only"

    run_call = thread._thread.run_calls[0]
    assert run_call["input"] == "plan"
    assert sdk_value(run_call["approval_mode"]) == "auto_review"
    assert run_call["cwd"] == str(tmp_path.resolve())
    assert sdk_value(run_call["effort"]) == "high"
    assert run_call["model"] == "gpt-5-codex"
    assert run_call["output_schema"] == schema
    assert run_call["sandbox_policy"].type == "readOnly"


def test_shared_agent_runtime_resumes_workspace_write_thread(tmp_path: Path) -> None:
    codex = FakeCodex()
    runtime = AgentRuntime(codex_client=codex)

    thread = runtime.open_thread(
        AgentRunConfig(
            role="evaluator",
            cwd=tmp_path,
            thread_id="evaluator-existing",
            policy=RuntimePolicy.WORKSPACE_WRITE,
            approval=RuntimeApproval.DENY_ALL,
        )
    )
    thread.run(
        "evaluate",
        AgentRunConfig(
            role="evaluator",
            cwd=tmp_path,
            effort="xhigh",
            policy=RuntimePolicy.WORKSPACE_WRITE,
            approval=RuntimeApproval.DENY_ALL,
        ),
    )

    assert thread.id == "evaluator-existing"
    assert codex.started_threads == []
    resume_call = codex.resumed_threads[0]
    assert resume_call["thread_id"] == "evaluator-existing"
    assert sdk_value(resume_call["approval_mode"]) == "deny_all"
    assert sdk_value(resume_call["sandbox"]) == "workspace-write"

    run_call = thread._thread.run_calls[0]
    assert sdk_value(run_call["approval_mode"]) == "deny_all"
    assert sdk_value(run_call["effort"]) == "xhigh"
    assert run_call["sandbox_policy"].type == "workspaceWrite"


def test_shared_agent_runtime_run_config_can_override_thread_policy(
    tmp_path: Path,
) -> None:
    codex = FakeCodex()
    runtime = AgentRuntime(codex_client=codex)
    thread = runtime.open_thread(
        AgentRunConfig(role="critic", cwd=tmp_path, policy=RuntimePolicy.READ_ONLY)
    )

    thread.run(
        "repair",
        AgentRunConfig(
            role="critic",
            cwd=tmp_path,
            policy=RuntimePolicy.WORKSPACE_WRITE,
        ),
    )

    assert sdk_value(codex.started_threads[0]["sandbox"]) == "read-only"
    assert thread._thread.run_calls[0]["sandbox_policy"].type == "workspaceWrite"


def test_shared_agent_runtime_closes_owned_codex_client(tmp_path: Path) -> None:
    codex = FakeCodex()

    with AgentRuntime(codex_factory=lambda: codex) as runtime:
        runtime.open_thread(AgentRunConfig(role="strategist", cwd=tmp_path))

    assert codex.closed is True
