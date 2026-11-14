from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.control_plane import agent_runtime as agent_runtime_module
from agent_control_plane.control_plane.agent_runtime import (
    AgentMemoryLimitExceeded,
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


class FakeMemoryScope:
    def __init__(self, maximum_memory_bytes: int) -> None:
        self.maximum_memory_bytes = maximum_memory_bytes
        self.commands: list[tuple[str, ...]] = []
        self.result_value: str | None = None
        self.stopped = False
        self.cleaned = False

    def command_argv(self, argv: tuple[str, ...]) -> tuple[str, ...]:
        self.commands.append(argv)
        return ("memory-scope", *argv)

    def result(self) -> str | None:
        return self.result_value

    def stop(self) -> None:
        self.stopped = True

    def cleanup(self) -> None:
        self.cleaned = True


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
    assert sdk_value(run_call["sandbox"]) == "read-only"


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
    assert resume_call["cwd"] == str(tmp_path.resolve())
    assert sdk_value(resume_call["approval_mode"]) == "deny_all"
    assert sdk_value(resume_call["sandbox"]) == "workspace-write"

    run_call = thread._thread.run_calls[0]
    assert run_call["cwd"] == str(tmp_path.resolve())
    assert sdk_value(run_call["approval_mode"]) == "deny_all"
    assert sdk_value(run_call["effort"]) == "xhigh"
    assert sdk_value(run_call["sandbox"]) == "workspace-write"


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
    assert sdk_value(thread._thread.run_calls[0]["sandbox"]) == "workspace-write"


def test_shared_agent_runtime_closes_owned_codex_client(tmp_path: Path) -> None:
    codex = FakeCodex()

    with AgentRuntime(codex_factory=lambda: codex) as runtime:
        runtime.open_thread(AgentRunConfig(role="strategist", cwd=tmp_path))

    assert codex.closed is True


def test_owned_agent_runtime_launches_codex_inside_one_memory_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum_memory_bytes = 123456
    scope = FakeMemoryScope(maximum_memory_bytes)
    codex = FakeCodex()
    configs: list[object] = []

    class FakeScopeFactory:
        @classmethod
        def create(cls, requested_bytes: int, *, purpose: str) -> FakeMemoryScope:
            assert requested_bytes == maximum_memory_bytes
            assert purpose == "codex-app-server"
            return scope

    def codex_factory(config: object) -> FakeCodex:
        configs.append(config)
        return codex

    monkeypatch.setattr(
        agent_runtime_module,
        "SystemdMemoryScope",
        FakeScopeFactory,
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "bundled_codex_path",
        lambda: Path("/opt/codex/bin/codex"),
    )

    with AgentRuntime(
        codex_factory=codex_factory,
        maximum_memory_bytes=maximum_memory_bytes,
    ) as runtime:
        runtime.open_thread(AgentRunConfig(role="strategist", cwd=tmp_path))

    assert len(configs) == 1
    assert getattr(configs[0], "launch_args_override") == (
        "memory-scope",
        "/opt/codex/bin/codex",
        "app-server",
        "--listen",
        "stdio://",
    )
    assert scope.commands == [
        (
            "/opt/codex/bin/codex",
            "app-server",
            "--listen",
            "stdio://",
        )
    ]
    assert codex.closed is True
    assert scope.stopped is True
    assert scope.cleaned is True


def test_agent_turn_reports_a_hard_memory_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum_memory_bytes = 123456
    scope = FakeMemoryScope(maximum_memory_bytes)
    scope.result_value = "oom-kill"

    class FailingThread(FakeCodexThread):
        def run(self, input: str, **kwargs: object) -> object:
            raise RuntimeError("app server connection closed")

    class FailingCodex(FakeCodex):
        def thread_start(self, **kwargs: object) -> FailingThread:
            return FailingThread("thread-1")

    class FakeScopeFactory:
        @classmethod
        def create(cls, requested_bytes: int, *, purpose: str) -> FakeMemoryScope:
            return scope

    monkeypatch.setattr(
        agent_runtime_module,
        "SystemdMemoryScope",
        FakeScopeFactory,
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "bundled_codex_path",
        lambda: Path("/opt/codex/bin/codex"),
    )

    with AgentRuntime(
        codex_factory=lambda config: FailingCodex(),
        maximum_memory_bytes=maximum_memory_bytes,
    ) as runtime:
        thread = runtime.open_thread(AgentRunConfig(role="strategist", cwd=tmp_path))
        with pytest.raises(AgentMemoryLimitExceeded, match="123456 bytes"):
            thread.run("plan", AgentRunConfig(role="strategist", cwd=tmp_path))


def test_agent_runtime_rejects_memory_limit_for_external_client() -> None:
    with pytest.raises(ValueError, match="externally owned"):
        AgentRuntime(codex_client=FakeCodex(), maximum_memory_bytes=123456)
