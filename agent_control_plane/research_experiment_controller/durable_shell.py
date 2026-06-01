from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_control_plane.control_plane.agent_runtime import AgentRuntime
from agent_control_plane.control_plane.json_artifacts import read_json_object


@dataclass(frozen=True)
class ResearchRunInput:
    research_run_id: str
    runtime_root: str = "runs"


ControllerRunner = Callable[[ResearchRunInput], dict[str, Any]]
DurableSleeper = Callable[[float], Awaitable[None] | None]


class MetadataSink(Protocol):
    def __call__(self, metadata: Mapping[str, Any]) -> None: ...


async def run_research_shell(
    input: ResearchRunInput,
    *,
    controller_runner: ControllerRunner | None = None,
    durable_sleep: DurableSleeper | None = None,
    metadata_sink: MetadataSink | None = None,
) -> dict[str, Any]:
    run_controller = controller_runner or _run_controller_loop
    while True:
        result = run_controller(input)
        if metadata_sink is not None:
            metadata_sink(_generic_run_metadata(input, result))
        if result.get("status") == "usage_limit_wait":
            await _durable_sleep(durable_sleep, float(result["sleep_seconds"]))
            continue
        return result


async def _durable_sleep(
    durable_sleep: DurableSleeper | None,
    sleep_seconds: float,
) -> None:
    sleeper = durable_sleep or asyncio.sleep
    sleep_result = sleeper(max(sleep_seconds, 0.0))
    if inspect.isawaitable(sleep_result):
        await sleep_result


def _generic_run_metadata(
    input: ResearchRunInput,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    state = _state_metadata(input)
    return {
        "run_id": input.research_run_id,
        "current_phase": state.get("current_phase", result.get("current_phase")),
        "controller_state_version": state.get(
            "controller_state_version", result.get("controller_state_version")
        ),
        "status": state.get("status", result.get("status")),
    }


def _state_metadata(input: ResearchRunInput) -> dict[str, Any]:
    state_path = (
        Path(input.runtime_root).resolve() / input.research_run_id / "state.json"
    )
    if not state_path.exists():
        return {}
    state = read_json_object(state_path)
    return {
        "current_phase": state.get("current_phase"),
        "controller_state_version": state.get("controller_state_version"),
        "status": state.get("status"),
    }


def _run_controller_loop(input: ResearchRunInput) -> dict[str, Any]:
    from agent_control_plane.research_experiment_controller.controller import (
        run_research_loop,
    )

    run_directory = Path(input.runtime_root).resolve() / input.research_run_id
    with AgentRuntime(
        agent_name_prefix="research-experiment",
        session_db_path=run_directory / "agent_sessions.sqlite3",
    ) as agent_runtime:
        return run_research_loop(
            input.research_run_id,
            runtime_root=input.runtime_root,
            agent_runtime=agent_runtime,
        )
