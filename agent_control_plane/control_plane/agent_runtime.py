from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from codex_cli_bin import bundled_codex_path
from openai_codex import ApprovalMode as CodexApprovalMode
from openai_codex import Codex, CodexConfig as CodexClientConfig, Sandbox
from openai_codex.types import ReasoningEffort

from agent_control_plane.control_plane.systemd_scope import SystemdMemoryScope


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


class AgentMemoryLimitExceeded(RuntimeError):
    """The owned Codex process tree crossed its configured memory ceiling."""


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
        codex_factory: Callable[..., CodexClientProtocol] | None = None,
        thread_id_factory: Callable[[str], str] | None = None,
        session_db_path: str | Path | None = None,
        agent_name_prefix: str = "control-plane",
        maximum_memory_bytes: int | None = None,
    ) -> None:
        del thread_id_factory, session_db_path, agent_name_prefix
        if maximum_memory_bytes is not None and (
            isinstance(maximum_memory_bytes, bool)
            or not isinstance(maximum_memory_bytes, int)
            or maximum_memory_bytes <= 0
        ):
            raise ValueError("Agent maximum memory must be a positive integer.")
        if codex_client is not None and maximum_memory_bytes is not None:
            raise ValueError(
                "A memory limit cannot be applied to an externally owned Codex client."
            )
        self._codex_client = codex_client
        self._codex_factory = codex_factory
        self._owns_client = codex_client is None
        self._maximum_memory_bytes = maximum_memory_bytes
        self._memory_scope: SystemdMemoryScope | None = None

    def __enter__(self) -> AgentRuntime:
        self._client()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        client = self._codex_client
        scope = self._memory_scope
        self._codex_client = None
        self._memory_scope = None
        try:
            if client is not None and self._owns_client:
                client.close()
        finally:
            if scope is not None:
                scope.stop()
                scope.cleanup()

    def open_thread(self, config: AgentRunConfig) -> AgentThread:
        policy = config.policy or RuntimePolicy.READ_ONLY
        approval = config.approval or RuntimeApproval.AUTO_REVIEW
        cwd = Path(config.cwd).resolve()
        thread_kwargs = {
            "approval_mode": _codex_approval(approval),
            "cwd": str(cwd),
            "developer_instructions": config.developer_instructions,
            "model": config.model,
            "sandbox": _sandbox(policy),
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
            memory_scope=self._memory_scope,
            maximum_memory_bytes=self._maximum_memory_bytes,
        )

    def _client(self) -> CodexClientProtocol:
        if self._codex_client is None:
            factory = self._codex_factory or Codex
            scope = self._new_memory_scope()
            try:
                if scope is None:
                    self._codex_client = factory()
                else:
                    self._codex_client = factory(
                        CodexClientConfig(
                            launch_args_override=scope.command_argv(
                                (
                                    str(bundled_codex_path()),
                                    "app-server",
                                    "--listen",
                                    "stdio://",
                                )
                            )
                        )
                    )
            except Exception as exc:
                if scope is not None:
                    result = scope.result()
                    scope.stop()
                    scope.cleanup()
                    if result == "oom-kill":
                        raise AgentMemoryLimitExceeded(
                            _memory_limit_message(scope.maximum_memory_bytes)
                        ) from exc
                raise
            self._memory_scope = scope
            self._owns_client = True
        return self._codex_client

    def _new_memory_scope(self) -> SystemdMemoryScope | None:
        if self._maximum_memory_bytes is None:
            return None
        return SystemdMemoryScope.create(
            self._maximum_memory_bytes,
            purpose="codex-app-server",
        )


class AgentThread:
    def __init__(
        self,
        *,
        thread: CodexThreadProtocol,
        cwd: Path,
        model: str | None,
        policy: RuntimePolicy,
        approval: RuntimeApproval,
        memory_scope: SystemdMemoryScope | None,
        maximum_memory_bytes: int | None,
    ) -> None:
        self.id = thread.id
        self._thread = thread
        self._cwd = cwd
        self._model = model
        self._policy = policy
        self._approval = approval
        self._memory_scope = memory_scope
        self._maximum_memory_bytes = maximum_memory_bytes

    def run(self, input: str, config: AgentRunConfig) -> AgentTurnResult:
        policy = config.policy or self._policy
        approval = config.approval or self._approval
        cwd = Path(config.cwd).resolve() if config.cwd is not None else self._cwd
        try:
            result = self._thread.run(
                input,
                approval_mode=_codex_approval(approval),
                cwd=str(cwd),
                effort=_reasoning_effort(config.effort),
                model=config.model or self._model,
                output_schema=config.output_schema,
                sandbox=_sandbox(policy),
            )
        except Exception as exc:
            if (
                self._memory_scope is not None
                and self._memory_scope.result() == "oom-kill"
            ):
                assert self._maximum_memory_bytes is not None
                raise AgentMemoryLimitExceeded(
                    _memory_limit_message(self._maximum_memory_bytes)
                ) from exc
            raise
        return AgentTurnResult(final_response=getattr(result, "final_response", None))


def _memory_limit_message(maximum_memory_bytes: int) -> str:
    return (
        "Codex agent process tree exceeded the hard memory limit of "
        f"{maximum_memory_bytes} bytes."
    )


def _codex_approval(approval: RuntimeApproval) -> CodexApprovalMode:
    return CodexApprovalMode(approval.value)


def _sandbox(policy: RuntimePolicy) -> Sandbox:
    if policy == RuntimePolicy.WORKSPACE_WRITE:
        return Sandbox.workspace_write
    return Sandbox.read_only


def _reasoning_effort(effort: str | None) -> ReasoningEffort | None:
    if effort is None:
        return None
    return ReasoningEffort(effort)
