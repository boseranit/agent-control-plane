from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class SandboxPolicy(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class ApprovalPolicy(str, Enum):
    AUTO_REVIEW = "auto_review"
    DENY_ALL = "deny_all"


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    cwd: Optional[str] = None
    developer_instructions: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    thread_id: Optional[str] = None
    sandbox: SandboxPolicy = SandboxPolicy.READ_ONLY
    approval: ApprovalPolicy = ApprovalPolicy.DENY_ALL


class AgentTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    turn_id: Optional[str] = None
    structured: Optional[dict[str, Any]] = None
    text: Optional[str] = None


class AgentTurnTimeoutError(TimeoutError):
    def __init__(
        self,
        *,
        role: str,
        thread_id: str,
        timeout_seconds: float,
        turn_id: Optional[str] = None,
    ) -> None:
        self.role = role
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.timeout_seconds = timeout_seconds
        turn_desc = f"turn {turn_id}" if turn_id is not None else "turn"
        super().__init__(
            f"role {role} {turn_desc} on thread {thread_id} "
            f"timed out after {timeout_seconds:g}s"
        )


@runtime_checkable
class AgentRuntime(Protocol):
    def run_turn(
        self,
        *,
        role: RoleConfig,
        prompt: str,
        prior_thread_id: Optional[str] = None,
        on_thread_started: Optional[Callable[[str], None]] = None,
        on_turn_started: Optional[Callable[[str, str], None]] = None,
    ) -> AgentTurnResult: ...
