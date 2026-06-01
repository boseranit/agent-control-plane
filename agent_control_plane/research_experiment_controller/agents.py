from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.agent_runtime import (
    AgentRunConfig,
    RuntimeApproval,
    RuntimePolicy,
)

PROMPT_DIRECTORY = Path(__file__).parent / "prompts"


class ResearchAgentRole(str, Enum):
    STRATEGIST = "strategist"
    CRITIC = "critic"
    IMPLEMENTER = "implementer"
    EVALUATOR = "evaluator"


def agent_config(
    role: ResearchAgentRole,
    cwd: str | Path,
    *,
    model: str | None = None,
    effort: str | None = None,
    output_schema: dict[str, Any] | None = None,
    thread_id: str | None = None,
    session_db_path: str | Path | None = None,
) -> AgentRunConfig:
    return AgentRunConfig(
        role=f"research-{role.value}",
        cwd=cwd,
        developer_instructions=prompt_for_role(role),
        model=model,
        effort=effort,
        output_schema=output_schema,
        thread_id=thread_id,
        session_db_path=session_db_path,
        policy=_policy_for_role(role),
        approval=RuntimeApproval.AUTO_REVIEW,
    )


def open_strategist_thread(
    runtime: Any,
    state: dict[str, Any],
    cwd: str | Path,
    **config_kwargs: Any,
) -> Any:
    threads = _threads(state)
    thread_id = _thread_id(threads.get(ResearchAgentRole.STRATEGIST.value))
    thread = runtime.open_thread(
        agent_config(
            ResearchAgentRole.STRATEGIST,
            cwd,
            thread_id=thread_id,
            **config_kwargs,
        )
    )
    threads[ResearchAgentRole.STRATEGIST.value] = thread.id
    return thread


def open_critic_thread(
    runtime: Any,
    state: dict[str, Any],
    cwd: str | Path,
    **config_kwargs: Any,
) -> Any:
    _threads(state).pop(ResearchAgentRole.CRITIC.value, None)
    return runtime.open_thread(
        agent_config(ResearchAgentRole.CRITIC, cwd, **config_kwargs)
    )


def open_implementer_thread(
    runtime: Any,
    state: dict[str, Any],
    experiment_worktree: str | Path,
    **config_kwargs: Any,
) -> Any:
    return _open_workspace_thread(
        runtime,
        state,
        role=ResearchAgentRole.IMPLEMENTER,
        workspace=experiment_worktree,
        **config_kwargs,
    )


def open_evaluator_thread(
    runtime: Any,
    state: dict[str, Any],
    evaluator_workspace: str | Path,
    **config_kwargs: Any,
) -> Any:
    return _open_workspace_thread(
        runtime,
        state,
        role=ResearchAgentRole.EVALUATOR,
        workspace=evaluator_workspace,
        **config_kwargs,
    )


def prompt_for_role(role: ResearchAgentRole) -> str:
    return (PROMPT_DIRECTORY / f"{role.value}-agent.md").read_text(encoding="utf-8")


def _policy_for_role(role: ResearchAgentRole) -> RuntimePolicy:
    if role in {ResearchAgentRole.IMPLEMENTER, ResearchAgentRole.EVALUATOR}:
        return RuntimePolicy.WORKSPACE_WRITE
    return RuntimePolicy.READ_ONLY


def _threads(state: dict[str, Any]) -> dict[str, Any]:
    threads = state.setdefault("threads", {})
    if not isinstance(threads, dict):
        raise ValueError("Research Run state threads must be an object.")
    return threads


def _thread_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("Research Agent thread id must be a non-empty string.")
    return value


def _open_workspace_thread(
    runtime: Any,
    state: dict[str, Any],
    *,
    role: ResearchAgentRole,
    workspace: str | Path,
    **config_kwargs: Any,
) -> Any:
    workspace_path = Path(workspace)
    thread_ids = _workspace_thread_ids(state, role)
    workspace_key = str(workspace_path.resolve())
    thread_id = _thread_id(thread_ids.get(workspace_key))
    thread = runtime.open_thread(
        agent_config(
            role,
            workspace_path,
            thread_id=thread_id,
            **config_kwargs,
        )
    )
    thread_ids[workspace_key] = thread.id
    return thread


def _workspace_thread_ids(
    state: dict[str, Any], role: ResearchAgentRole
) -> dict[str, Any]:
    threads = _threads(state)
    thread_ids = threads.setdefault(role.value, {})
    if not isinstance(thread_ids, dict):
        raise ValueError(f"Research Agent {role.value} threads must be an object.")
    return thread_ids
