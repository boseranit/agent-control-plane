from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from hatchet_sdk import DurableContext, Hatchet
from pydantic import BaseModel

from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
    run_research_shell,
)


class HatchetResearchRunInput(BaseModel):
    research_run_id: str
    runtime_root: str = "runs"


def build_hatchet_workflows(hatchet: Hatchet) -> list[Any]:
    @hatchet.durable_task(
        name="research-run",
        input_validator=HatchetResearchRunInput,
        execution_timeout=timedelta(days=30),
    )
    async def research_run(
        input: HatchetResearchRunInput, ctx: DurableContext
    ) -> dict[str, Any]:
        return await run_research_shell(
            _to_research_run_input(input),
            controller_runner=None,
            durable_sleep=lambda seconds: ctx.aio_sleep_for(
                timedelta(seconds=seconds), label="usage limit"
            ),
            metadata_sink=_metadata_sink(ctx),
        )

    return [research_run]


def _to_research_run_input(
    input: HatchetResearchRunInput | ResearchRunInput,
) -> ResearchRunInput:
    if isinstance(input, ResearchRunInput):
        return input
    return ResearchRunInput(
        research_run_id=input.research_run_id,
        runtime_root=input.runtime_root,
    )


def _metadata_sink(ctx: DurableContext):
    def sink(metadata: Mapping[str, Any]) -> None:
        additional_metadata = getattr(ctx, "additional_metadata", None)
        if isinstance(additional_metadata, dict):
            additional_metadata.update(dict(metadata))
        record_metadata = getattr(ctx, "record_metadata", None)
        if callable(record_metadata):
            record_metadata(dict(metadata))

    return sink
