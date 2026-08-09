from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane.agent_runtime import (
    RuntimeApproval,
    RuntimePolicy,
)
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
    assert config.approval is RuntimeApproval.AUTO_REVIEW


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


def test_research_agent_prompts_encode_optional_artifact_backfill_policy() -> None:
    strategist = prompt_for_role(ResearchAgentRole.STRATEGIST)
    implementer = prompt_for_role(ResearchAgentRole.IMPLEMENTER)
    critic = prompt_for_role(ResearchAgentRole.CRITIC)
    evaluator = prompt_for_role(ResearchAgentRole.EVALUATOR)

    assert "expected_outputs" in strategist
    assert "deterministic command groups" in strategist
    assert "argv is an array of strings, never a shell string" in strategist
    assert "read canonical inputs from $HLM_DATA_ROOT" in implementer
    assert "$RESEARCH_EXPERIMENT_DATA_ROOT/runtime-data" in implementer
    assert (
        "declared evaluation outputs under $RESEARCH_EXPERIMENT_DATA_ROOT"
        in implementer
    )
    assert (
        "Do not write generated experiment data into the canonical data root"
        in implementer
    )
    assert (
        "require an explicit post-implementation verification backfill command"
        in critic
    )
    assert "experiment backfills into canonical data" in critic
    assert "declared experiment-local evaluation evidence" in critic
    assert (
        "read experiment-local outputs under the experiment data root before canonical data"
        in evaluator
    )
    assert "declared experiment-local evaluation outputs" in evaluator
    assert (
        "Exploratory diagnostics are attached to the locked confirmatory plan"
        in evaluator
    )


def test_research_agent_prompts_encode_continuation_behavior() -> None:
    strategist = prompt_for_role(ResearchAgentRole.STRATEGIST)
    implementer = prompt_for_role(ResearchAgentRole.IMPLEMENTER)
    evaluator = prompt_for_role(ResearchAgentRole.EVALUATOR)

    assert "continuation_summary.json" in strategist
    assert "direct_followup" in strategist
    assert "controlled_variation" in strategist
    assert "reusable worktree paths" in strategist
    assert "prior implementation worktree" in implementer
    assert "reused/adapted pieces" in implementer
    assert "Future experiment ideas must be testable directly" in evaluator


def test_strategist_prompt_uses_current_schema_names() -> None:
    strategist = prompt_for_role(ResearchAgentRole.STRATEGIST)

    assert '{"selected": false, "rationale": "..."}' in strategist
    assert "ends the Research Experiment" in strategist
    assert "Proposal/proposal.json" in strategist
    assert "ResearchSpec/research_spec.json" in strategist
    assert "may use any JSON value" in strategist
    assert "ExperimentDesign/experiment_design.json" in strategist
    assert "SelectedPlan/selected_plan.json" in strategist
    assert "Summary/summary.json" in strategist
    assert "PlanUpdate/plan_update.json" in strategist
    assert (
        "name, argv, timeout_seconds, phase, and failure_classification" in strategist
    )
    assert "do not include cwd, env, or id" in strategist
    assert "expected_outputs" in strategist
    assert "selected_idea_ids" in strategist
    assert "fresh_selection_reason" in strategist
    assert "seed_component_ids" in strategist
    assert "blockers" in strategist
    assert "reusable_components" in strategist
    assert "output schema" not in strategist


def test_strategist_prompt_encodes_context_and_closeout_outputs() -> None:
    strategist = prompt_for_role(ResearchAgentRole.STRATEGIST)

    assert "The controller owns context artifact creation" in strategist
    assert "For empirical-closeout turns" in strategist
    assert "Summary/summary.json" in strategist
    assert "PlanUpdate/plan_update.json" in strategist
    assert "evidence supplied by the controller" in strategist


def test_strategist_prompt_encodes_plan_update_cards_without_schema_dump() -> None:
    strategist = prompt_for_role(ResearchAgentRole.STRATEGIST)

    assert "followups, learning_updates, blockers, reusable_components" in strategist
    assert "superseded_idea_ids" in strategist
    assert "use empty lists when none apply" in strategist
    assert "only other pending ideas made obsolete" in strategist
    assert "Do not include selected_plan.selected_idea_ids" in strategist
    assert '"properties"' not in strategist
    assert '"additionalProperties"' not in strategist


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
