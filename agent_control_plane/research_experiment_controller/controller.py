from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.ledger import (
    append_ledger_event,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    load_research_run_spec,
    resolved_spec_dict,
)
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    research_run_directory,
)


@dataclass(frozen=True)
class ResearchRun:
    research_run_id: str
    run_directory: Path
    spec_snapshot_path: Path
    state_path: Path
    ledger_path: Path
    experiments_directory: Path
    state: dict[str, Any]


class ResearchRunError(RuntimeError):
    """Raised when a Research Run cannot be started or loaded."""


def start_research_run(
    research_run_spec_path: str | Path,
    *,
    runtime_root: str | Path = "runs",
) -> ResearchRun:
    spec = load_research_run_spec(research_run_spec_path)
    run_directory = research_run_directory(runtime_root, spec.research_run_id)
    try:
        run_directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise ResearchRunError(
            f"Research Run already exists: {spec.research_run_id}"
        ) from exc

    spec_snapshot_path = run_directory / "research_run_spec.yaml"
    state_path = run_directory / "state.json"
    ledger_path = run_directory / "ledger.jsonl"
    experiments_directory = run_directory / "experiments"
    experiments_directory.mkdir()

    spec_snapshot_path.write_text(
        yaml.safe_dump(resolved_spec_dict(spec), sort_keys=False),
        encoding="utf-8",
    )
    state = create_initial_state(
        research_run_id=spec.research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=spec_snapshot_path,
        max_experiments=spec.max_experiments,
    )
    write_json(state_path, state)

    append_ledger_event(
        ledger_path,
        event_type="research_run_started",
        research_run_id=spec.research_run_id,
    )
    append_ledger_event(
        ledger_path,
        event_type="phase_changed",
        research_run_id=spec.research_run_id,
        current_phase=state["current_phase"],
    )
    append_ledger_event(
        ledger_path,
        event_type="artifact_written",
        research_run_id=spec.research_run_id,
        artifact_name="research_run_spec",
        artifact_path=str(spec_snapshot_path),
    )
    append_ledger_event(
        ledger_path,
        event_type="artifact_written",
        research_run_id=spec.research_run_id,
        artifact_name="state",
        artifact_path=str(state_path),
    )

    return ResearchRun(
        research_run_id=spec.research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=spec_snapshot_path,
        state_path=state_path,
        ledger_path=ledger_path,
        experiments_directory=experiments_directory,
        state=state,
    )


def load_research_run(
    research_run_id: str,
    *,
    runtime_root: str | Path = "runs",
) -> ResearchRun:
    run_directory = research_run_directory(runtime_root, research_run_id)
    spec_snapshot_path = run_directory / "research_run_spec.yaml"
    state_path = run_directory / "state.json"
    ledger_path = run_directory / "ledger.jsonl"
    experiments_directory = run_directory / "experiments"

    if not run_directory.exists():
        raise ResearchRunError(f"Research Run does not exist: {research_run_id}")
    if not spec_snapshot_path.exists():
        raise ResearchRunError(
            f"Research Run is missing snapshotted spec: {spec_snapshot_path}"
        )
    if not state_path.exists():
        raise ResearchRunError(f"Research Run is missing state: {state_path}")
    if not ledger_path.exists():
        raise ResearchRunError(f"Research Run is missing ledger: {ledger_path}")
    if not experiments_directory.is_dir():
        raise ResearchRunError(
            f"Research Run is missing experiments directory: {experiments_directory}"
        )

    snapshot = load_research_run_spec(spec_snapshot_path)
    state = read_json_object(state_path)
    if snapshot.research_run_id != research_run_id:
        raise ResearchRunError(
            "Research Run snapshot does not match requested Research Run ID."
        )
    if state.get("research_run_id") != research_run_id:
        raise ResearchRunError(
            "Research Run state does not match requested Research Run ID."
        )
    if Path(str(state.get("spec_snapshot_path", ""))).resolve() != (
        spec_snapshot_path.resolve()
    ):
        raise ResearchRunError("Research Run state does not point at its snapshot.")

    return ResearchRun(
        research_run_id=research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=spec_snapshot_path,
        state_path=state_path,
        ledger_path=ledger_path,
        experiments_directory=experiments_directory,
        state=state,
    )
