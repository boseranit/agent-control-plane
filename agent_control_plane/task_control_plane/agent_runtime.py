from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent_control_plane.control_plane.agent_runtime import (
    AgentRuntime as SharedAgentRuntime,
    AgentRunConfig as SharedAgentRunConfig,
    AgentTurnResult,
    RuntimeApproval,
    RuntimePolicy,
)

AgentRole = Literal["planner", "context", "implementer", "reviewer"]


@dataclass(frozen=True)
class AgentRunConfig:
    role: AgentRole
    cwd: str | Path
    developer_instructions: str | None = None
    model: str | None = None
    effort: str | None = None
    output_schema: dict[str, Any] | None = None
    thread_id: str | None = None
    session_db_path: str | Path | None = None


class AgentRuntime:
    def __init__(
        self,
        *,
        thread_id_factory: Callable[[AgentRole], str] | None = None,
        session_db_path: str | Path | None = None,
    ) -> None:
        self._runtime = SharedAgentRuntime(
            thread_id_factory=thread_id_factory,
            session_db_path=session_db_path,
            agent_name_prefix="task-control",
        )

    def __enter__(self) -> AgentRuntime:
        self._runtime.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._runtime.__exit__(*exc_info)

    def open_thread(self, config: AgentRunConfig) -> AgentThread:
        return AgentThread(
            self._runtime.open_thread(
                _shared_config(
                    config,
                    _policy_for_role(config.role),
                    _approval_for_role(config.role),
                )
            )
        )


class AgentThread:
    def __init__(self, thread: Any) -> None:
        self._thread = thread

    @property
    def id(self) -> str:
        return self._thread.id

    def run(self, input: str, config: AgentRunConfig) -> AgentTurnResult:
        return self._thread.run(
            input,
            _shared_config(
                config,
                _policy_for_role(config.role),
                _approval_for_role(config.role),
            ),
        )


def _shared_config(
    config: AgentRunConfig, policy: RuntimePolicy, approval: RuntimeApproval
) -> SharedAgentRunConfig:
    return SharedAgentRunConfig(
        role=config.role,
        cwd=config.cwd,
        developer_instructions=config.developer_instructions,
        model=config.model,
        effort=config.effort,
        output_schema=config.output_schema,
        thread_id=config.thread_id,
        session_db_path=config.session_db_path,
        policy=policy,
        approval=approval,
    )


def _policy_for_role(role: AgentRole) -> RuntimePolicy:
    if role == "implementer":
        return RuntimePolicy.WORKSPACE_WRITE
    return RuntimePolicy.READ_ONLY


def _approval_for_role(role: AgentRole) -> RuntimeApproval:
    if role == "reviewer":
        return RuntimeApproval.DENY_ALL
    return RuntimeApproval.AUTO_REVIEW
