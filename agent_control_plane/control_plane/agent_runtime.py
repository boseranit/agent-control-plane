from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from openai_codex import ApprovalMode as CodexApprovalMode
from openai_codex import Codex
from openai_codex.generated.v2_all import (
    ReadOnlySandboxPolicy,
    WorkspaceWriteSandboxPolicy,
)
from openai_codex.types import ReasoningEffort, SandboxMode


class RuntimePolicy(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class RuntimeApproval(str, Enum):
    AUTO_REVIEW = "auto_review"
    DENY_ALL = "deny_all"


@dataclass(frozen=True)
class AgentRunConfig:
    role: str
    cwd: str | Path
    developer_instructions: str | None = None
    model: str | None = None
    effort: str | None = None
    output_schema: dict[str, Any] | None = None
    thread_id: str | None = None
    session_db_path: str | Path | None = None
    policy: RuntimePolicy | None = None
    approval: RuntimeApproval | None = None


@dataclass(frozen=True)
class AgentTurnResult:
    final_response: Any


class AgentRuntimeProtocol(Protocol):
    def open_thread(self, config: AgentRunConfig) -> AgentThreadProtocol: ...


class AgentThreadProtocol(Protocol):
    id: str

    def run(self, input: str, config: AgentRunConfig) -> AgentTurnResult: ...


class CodexClientProtocol(Protocol):
    def thread_start(self, **kwargs: Any) -> CodexThreadProtocol: ...

    def thread_resume(self, thread_id: str, **kwargs: Any) -> CodexThreadProtocol: ...

    def close(self) -> None: ...


class CodexThreadProtocol(Protocol):
    id: str

    def run(self, input: str, **kwargs: Any) -> Any: ...


class AgentRuntime:
    def __init__(
        self,
        *,
        codex_client: CodexClientProtocol | None = None,
        codex_factory: Callable[[], CodexClientProtocol] | None = None,
        thread_id_factory: Callable[[str], str] | None = None,
        session_db_path: str | Path | None = None,
        agent_name_prefix: str = "control-plane",
    ) -> None:
        del thread_id_factory, session_db_path, agent_name_prefix
        self._codex_client = codex_client
        self._codex_factory = codex_factory
        self._owns_client = codex_client is None

    def __enter__(self) -> AgentRuntime:
        self._client()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._codex_client is not None and self._owns_client:
            self._codex_client.close()
        self._codex_client = None

    def open_thread(self, config: AgentRunConfig) -> AgentThread:
        policy = config.policy or RuntimePolicy.READ_ONLY
        approval = config.approval or RuntimeApproval.AUTO_REVIEW
        cwd = Path(config.cwd).resolve()
        thread_kwargs = {
            "approval_mode": _codex_approval(approval),
            "cwd": str(cwd),
            "developer_instructions": config.developer_instructions,
            "model": config.model,
            "sandbox": _sandbox_mode(policy),
        }
        if config.thread_id is None:
            thread = self._client().thread_start(**thread_kwargs)
        else:
            thread = self._client().thread_resume(config.thread_id, **thread_kwargs)
        return AgentThread(
            thread=thread,
            cwd=cwd,
            model=config.model,
            policy=policy,
            approval=approval,
        )

    def _client(self) -> CodexClientProtocol:
        if self._codex_client is None:
            factory = self._codex_factory or Codex
            self._codex_client = factory()
            self._owns_client = True
        return self._codex_client


class AgentThread:
    def __init__(
        self,
        *,
        thread: CodexThreadProtocol,
        cwd: Path,
        model: str | None,
        policy: RuntimePolicy,
        approval: RuntimeApproval,
    ) -> None:
        self.id = thread.id
        self._thread = thread
        self._cwd = cwd
        self._model = model
        self._policy = policy
        self._approval = approval

    def run(self, input: str, config: AgentRunConfig) -> AgentTurnResult:
        policy = config.policy or self._policy
        approval = config.approval or self._approval
        cwd = Path(config.cwd).resolve() if config.cwd is not None else self._cwd
        result = self._thread.run(
            input,
            approval_mode=_codex_approval(approval),
            cwd=str(cwd),
            effort=_reasoning_effort(config.effort),
            model=config.model or self._model,
            output_schema=config.output_schema,
            sandbox_policy=_sandbox_policy(policy, cwd),
        )
        return AgentTurnResult(final_response=getattr(result, "final_response", None))


def _codex_approval(approval: RuntimeApproval) -> CodexApprovalMode:
    return CodexApprovalMode(approval.value)


def _sandbox_mode(policy: RuntimePolicy) -> SandboxMode:
    if policy == RuntimePolicy.WORKSPACE_WRITE:
        return SandboxMode.workspace_write
    return SandboxMode.read_only


def _sandbox_policy(
    policy: RuntimePolicy, cwd: Path
) -> ReadOnlySandboxPolicy | WorkspaceWriteSandboxPolicy:
    if policy == RuntimePolicy.WORKSPACE_WRITE:
        return WorkspaceWriteSandboxPolicy(
            type="workspaceWrite",
            writable_roots=[str(cwd)],
        )
    return ReadOnlySandboxPolicy(type="readOnly")


def _reasoning_effort(effort: str | None) -> ReasoningEffort | None:
    if effort is None:
        return None
    return ReasoningEffort(effort)
