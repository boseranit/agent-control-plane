from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane.agent_runtime import RuntimePolicy
from agent_control_plane.research_experiment_controller.agents import (
    ResearchAgentRole,
    agent_config,
    open_critic_thread,
    open_evaluator_thread,
    open_implementer_thread,
    open_strategist_thread,
    prompt_for_role,
)


class FakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id


class FakeRuntime:
    def __init__(self) -> None:
        self.configs = []

    def open_thread(self, config):
        self.configs.append(config)
        thread_id = config.thread_id or f"{config.role}-thread-{len(self.configs)}"
        return FakeThread(thread_id)


def test_research_agent_config_uses_current_runtime_api(tmp_path: Path) -> None:
    config = agent_config(ResearchAgentRole.STRATEGIST, tmp_path)

    assert config.role == "research-strategist"
    assert config.developer_instructions == prompt_for_role(
        ResearchAgentRole.STRATEGIST
    )
    assert config.policy is RuntimePolicy.READ_ONLY


def test_research_agent_roles_have_expected_runtime_policies(
    tmp_path: Path,
) -> None:
    assert agent_config(ResearchAgentRole.STRATEGIST, tmp_path).policy is (
        RuntimePolicy.READ_ONLY
    )
    assert agent_config(ResearchAgentRole.CRITIC, tmp_path).policy is (
        RuntimePolicy.READ_ONLY
    )
    assert agent_config(ResearchAgentRole.IMPLEMENTER, tmp_path).policy is (
        RuntimePolicy.WORKSPACE_WRITE
    )
    assert agent_config(ResearchAgentRole.EVALUATOR, tmp_path).policy is (
        RuntimePolicy.WORKSPACE_WRITE
    )


def test_research_agent_prompts_encode_shared_boundaries() -> None:
    for role in ResearchAgentRole:
        prompt = prompt_for_role(role)

        assert "Artifacts are authoritative" in prompt
        assert "Materiality is controller-owned" in prompt
        assert "Do not wait for human input in v1" in prompt
        assert "proceed with explicit assumptions" in prompt


def test_strategist_thread_persists_per_research_run_state(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    state = {"threads": {}}

    first = open_strategist_thread(runtime, state, tmp_path)
    second = open_strategist_thread(runtime, state, tmp_path)

    assert first.id == "research-strategist-thread-1"
    assert second.id == first.id
    assert state["threads"]["strategist"] == first.id
    assert runtime.configs[0].thread_id is None
    assert runtime.configs[1].thread_id == first.id
    assert runtime.configs[1].policy is RuntimePolicy.READ_ONLY


def test_critic_thread_is_fresh_per_critique_pass(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    state = {"threads": {"critic": "critic-thread-old"}}

    first = open_critic_thread(runtime, state, tmp_path)
    second = open_critic_thread(runtime, state, tmp_path)

    assert first.id == "research-critic-thread-1"
    assert second.id == "research-critic-thread-2"
    assert "critic" not in state["threads"]
    assert runtime.configs[0].thread_id is None
    assert runtime.configs[1].thread_id is None
    assert runtime.configs[1].policy is RuntimePolicy.READ_ONLY


def test_implementer_thread_persists_per_experiment_worktree(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    state = {"threads": {}}
    worktree = tmp_path / "worktrees" / "EXP-0001"
    other_worktree = tmp_path / "worktrees" / "EXP-0002"

    first = open_implementer_thread(runtime, state, worktree)
    second = open_implementer_thread(runtime, state, worktree)
    third = open_implementer_thread(runtime, state, other_worktree)

    assert first.id == "research-implementer-thread-1"
    assert second.id == first.id
    assert third.id == "research-implementer-thread-3"
    assert state["threads"]["implementer"] == {
        str(worktree.resolve()): first.id,
        str(other_worktree.resolve()): third.id,
    }
    assert runtime.configs[0].cwd == worktree
    assert runtime.configs[0].policy is RuntimePolicy.WORKSPACE_WRITE
    assert runtime.configs[1].thread_id == first.id


def test_evaluator_thread_persists_per_evaluator_workspace(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    state = {"threads": {}}
    workspace = tmp_path / "runs" / "EXP-0001" / "evaluation"

    first = open_evaluator_thread(runtime, state, workspace)
    second = open_evaluator_thread(runtime, state, workspace)

    assert first.id == "research-evaluator-thread-1"
    assert second.id == first.id
    assert state["threads"]["evaluator"] == {str(workspace.resolve()): first.id}
    assert runtime.configs[0].cwd == workspace
    assert runtime.configs[0].policy is RuntimePolicy.WORKSPACE_WRITE
    assert runtime.configs[1].thread_id == first.id
