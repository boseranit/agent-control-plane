from __future__ import annotations

from hatchet_sdk import Hatchet

from agent_control_plane.research_experiment_controller.hatchet_workflow import (
    build_hatchet_workflows,
)


def main() -> None:
    hatchet = Hatchet()
    worker = hatchet.worker(
        "research-experiment-controller",
        workflows=build_hatchet_workflows(hatchet),
        slots=1,
        durable_slots=1,
    )
    worker.start()


if __name__ == "__main__":
    main()
