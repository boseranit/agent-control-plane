"""The Codex adapter: maps the neutral agent runtime onto the Codex SDK.

This is the ONLY module in the package that knows about the Codex SDK (design
"Simplified Package Shape" → important boundary rule; issue 004 confines the SDK
to one adapter). It implements :class:`research_loop.runtime.AgentRuntime`
by translating a neutral :class:`RoleConfig` into Codex ``thread_start`` /
``thread_resume`` calls and a neutral turn into ``thread.turn(...)`` (which
returns a ``TurnHandle`` we drain under a wall-clock timeout and can
``interrupt()``), then parsing the SDK ``TurnResult`` back into a neutral
:class:`AgentTurnResult`.

CRITICAL: ``openai_codex`` is imported LAZILY, inside the methods/helpers that
need it - never at module import time. The test environment does not install the
SDK, and the import-boundary test parses this package's source to confirm every
OTHER module avoids the SDK. Keeping the import lazy lets the adapter module be
imported (and referenced) without the SDK present.
"""

from __future__ import annotations

import contextlib
import copy
import json
import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Callable, Optional

from ..runtime import (
    AgentTurnResult,
    AgentTurnTimeoutError,
    ApprovalPolicy,
    RoleConfig,
    SandboxPolicy,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; never imported at runtime
    from openai_codex import ApprovalMode, Codex, Sandbox

__all__ = [
    "CodexRuntime",
    "CodexRuntimeError",
    "open_codex_runtime",
]


class CodexRuntimeError(RuntimeError):
    """Raised when the Codex SDK returns an unusable turn result."""


_DEFAULT_TURN_TIMEOUT_SECONDS = 30 * 60


def _map_sandbox(policy: SandboxPolicy) -> "Sandbox":
    """Map a neutral sandbox policy onto a Codex ``Sandbox`` (lazy import)."""
    from openai_codex import Sandbox

    if policy is SandboxPolicy.WORKSPACE_WRITE:
        return Sandbox.workspace_write
    return Sandbox.read_only


def _map_approval(policy: ApprovalPolicy) -> "ApprovalMode":
    """Map a neutral approval policy onto a Codex ``ApprovalMode`` (lazy import)."""
    from openai_codex import ApprovalMode

    if policy is ApprovalPolicy.AUTO_REVIEW:
        return ApprovalMode.auto_review
    return ApprovalMode.deny_all


def _map_effort(reasoning_effort: Optional[str]):
    """Map a neutral reasoning-effort string onto a Codex ``ReasoningEffort``.

    Returns ``None`` when unset so the SDK applies its own default. Lazy import.
    """
    if reasoning_effort is None:
        return None
    from openai_codex.generated.v2_all import ReasoningEffort

    return ReasoningEffort(reasoning_effort)


class CodexRuntime:
    """A :class:`research_loop.runtime.AgentRuntime` backed by the Codex SDK.

    Constructed with an open Codex client (a ``Codex`` context manager instance).
    The controller depends only on the neutral runtime interface; the concrete
    construction of this adapter lives at the application/CLI edge.
    """

    def __init__(
        self, codex: "Codex", *, turn_timeout_seconds: Optional[float] = None
    ) -> None:
        self._codex = codex
        self._turn_timeout_seconds = (
            turn_timeout_seconds or _DEFAULT_TURN_TIMEOUT_SECONDS
        )

    def run_turn(
        self,
        *,
        role: RoleConfig,
        prompt: str,
        prior_thread_id: Optional[str] = None,
        on_thread_started: Optional[Callable[[str], None]] = None,
        on_turn_started: Optional[Callable[[str, str], None]] = None,
    ) -> AgentTurnResult:
        """Open or resume the role's thread and run one turn through the SDK.

        Opens a thread (``thread_start``) when ``prior_thread_id is None`` and
        resumes it (``thread_resume``) otherwise, mapping the neutral role config
        onto cwd / developer instructions / model / sandbox / approval mode. The
        turn runs with the role's reasoning effort and structured
        ``output_schema``; the SDK's ``final_response`` JSON string is parsed
        into the neutral result's ``structured`` payload.
        """
        sandbox = _map_sandbox(role.sandbox)
        approval = _map_approval(role.approval)
        thread_kwargs = {
            "cwd": role.cwd,
            "developer_instructions": role.developer_instructions,
            "model": role.model,
            "sandbox": sandbox,
            "approval_mode": approval,
        }

        if prior_thread_id is None:
            thread = self._codex.thread_start(**thread_kwargs)
        else:
            thread = self._codex.thread_resume(prior_thread_id, **thread_kwargs)
        if on_thread_started is not None:
            on_thread_started(thread.id)

        output_schema = _codex_output_schema(role.output_schema)
        # Start the turn (server-side turn id is known immediately) and persist
        # it before the turn blocks, so a stall can be ledgered/interrupted by id.
        handle = thread.turn(
            prompt,
            effort=_map_effort(role.reasoning_effort),
            model=role.model,
            output_schema=output_schema,
            sandbox=sandbox,
        )
        if on_turn_started is not None:
            on_turn_started(thread.id, handle.id)

        turn = _drain_handle_with_timeout(
            handle,
            role=role.role,
            thread_id=thread.id,
            timeout_seconds=self._turn_timeout_seconds,
        )

        # A failed / interrupted / in-progress turn must NOT be parsed as a
        # result: its final_response may be missing or stale and would otherwise
        # be persisted as a real artifact. Surface the SDK status/error instead.
        _ensure_turn_completed(turn)
        structured = _parse_structured(turn.final_response, role.output_schema)
        return AgentTurnResult(
            thread_id=thread.id,
            turn_id=handle.id,
            structured=structured,
            # ``text`` carries the final assistant text only when no structured
            # schema was requested; for a structured turn the payload is in
            # ``structured`` and final_response is just its JSON encoding.
            text=turn.final_response if role.output_schema is None else None,
        )


@contextlib.contextmanager
def open_codex_runtime() -> "Iterator[CodexRuntime]":
    """Open a live Codex client and yield a :class:`CodexRuntime`.

    This is the ONE place a real Codex client is constructed. The application /
    CLI edge wraps a whole agent-driven session in
    ``with open_codex_runtime() as runtime: ...``; the underlying ``Codex``
    client is opened as a context manager and CLOSED on exit (whether the
    session succeeds or raises).

    ``openai_codex`` is imported LAZILY here so this module still imports without
    the SDK installed and the import-boundary test stays satisfied — this adapter
    remains the only module that references the SDK.
    """
    from openai_codex import Codex

    with Codex() as codex:
        yield CodexRuntime(codex)


def _drain_handle_with_timeout(
    handle: Any,
    *,
    role: str,
    thread_id: str,
    timeout_seconds: float,
) -> Any:
    """Drain a started ``TurnHandle`` to its ``TurnResult`` under a wall clock.

    ``handle.run()`` blocks in a worker thread on the SDK's per-turn notification
    queue. We wait at most ``timeout_seconds``; if the turn is still running we
    request a real provider-side cancel (``handle.interrupt()`` — a separate
    JSON-RPC request whose response routes through its own waiter, so it does not
    contend with the worker's blocking ``queue.get``) and raise
    :class:`AgentTurnTimeoutError`.

    The worker is a daemon: a pathologically wedged turn can never block the
    controller. Normally the interrupt's terminal notification unblocks the drain
    (which then unregisters its stream); worst case the daemon dies at process
    exit. This is portable (no ``signal``/SIGALRM), so it works off the main
    thread too — unlike the previous itimer-based timeout.
    """
    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _drain() -> None:
        try:
            result_box["turn"] = handle.run()
        except BaseException as exc:  # noqa: BLE001 - surfaced on the caller thread
            error_box["exc"] = exc

    worker = threading.Thread(
        target=_drain, name=f"codex-turn-{thread_id}", daemon=True
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        with contextlib.suppress(Exception):
            handle.interrupt()
        raise AgentTurnTimeoutError(
            role=role,
            thread_id=thread_id,
            turn_id=handle.id,
            timeout_seconds=timeout_seconds,
        )
    if "exc" in error_box:
        raise error_box["exc"]
    return result_box["turn"]


def _codex_output_schema(schema: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return a Codex-compatible structured-output schema.

    The Codex/OpenAI structured-output API requires each object schema's
    ``required`` list to contain every declared property. Pydantic omits fields
    with defaults from ``required`` even when our runtime models accept those
    defaults, so normalize a deep copy at the provider boundary instead of
    changing artifact semantics.
    """
    if schema is None:
        return None
    normalized = copy.deepcopy(schema)
    _require_all_object_properties(normalized)
    _prune_unreferenced_defs(normalized)
    return normalized


def _prune_unreferenced_defs(schema: dict[str, Any]) -> None:
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return

    referenced: set[str] = set()
    pending = _local_def_refs(schema)
    while pending:
        name = pending.pop()
        if name in referenced:
            continue
        referenced.add(name)
        target = defs.get(name)
        if target is not None:
            pending.update(_local_def_refs(target))

    for name in list(defs):
        if name not in referenced:
            del defs[name]
    if not defs:
        del schema["$defs"]


def _local_def_refs(node: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            refs.add(ref.removeprefix("#/$defs/"))
        for key, value in node.items():
            if key == "$defs":
                continue
            refs.update(_local_def_refs(value))
    elif isinstance(node, list):
        for value in node:
            refs.update(_local_def_refs(value))
    return refs


def _require_all_object_properties(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node.setdefault("properties", {})
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
        for value in node.values():
            _require_all_object_properties(value)
    elif isinstance(node, list):
        for value in node:
            _require_all_object_properties(value)


def _ensure_turn_completed(turn: Any) -> None:
    """Raise if the SDK turn did not complete successfully (lazy import).

    Guards against treating a ``failed`` / ``interrupted`` / ``in_progress`` turn
    — or one that carries an ``error`` — as a successful result.
    """
    from openai_codex.generated.v2_all import TurnStatus

    if turn.status is not TurnStatus.completed or turn.error is not None:
        raise CodexRuntimeError(
            f"Codex turn did not complete (status={turn.status!r}, "
            f"error={turn.error!r})"
        )


def _parse_structured(
    final_response: Optional[str], output_schema: Optional[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Parse the SDK final response into a dict when a schema was requested.

    With an ``output_schema`` set, the SDK returns ``final_response`` as a JSON
    string; parse it. Without a schema there is no structured output to parse.
    """
    if output_schema is None:
        return None
    if final_response is None:
        raise CodexRuntimeError(
            "Codex returned no final_response for a structured-output turn"
        )
    try:
        parsed = json.loads(final_response)
    except json.JSONDecodeError as exc:
        raise CodexRuntimeError(
            f"Codex structured final_response was not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise CodexRuntimeError(
            "Codex structured final_response did not decode to a JSON object"
        )
    return parsed
