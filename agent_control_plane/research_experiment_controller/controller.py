from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.experiment_flow import (
    ExperimentFlowRequest,
    run_experiment_flow,
)
from agent_control_plane.research_experiment_controller.ledger import (
    append_ledger_event,
)
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_run_failed,
    should_stop_research_run,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    load_research_run_spec,
    resolved_spec_dict,
)
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    experiment_directory,
    load_terminal_summary,
    next_experiment_id,
    record_terminal_experiment,
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


@dataclass(frozen=True)
class ResearchPhaseInput:
    research_run_id: str
    run_directory: Path
    spec_snapshot_path: Path
    state_path: Path
    ledger_path: Path
    experiments_directory: Path


ExperimentRunner = Callable[[ExperimentFlowRequest], dict[str, Any]]


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


def run_research_loop(
    research_run_id: str,
    *,
    runtime_root: str | Path = "runs",
    experiment_runner: ExperimentRunner | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    run = load_research_run(research_run_id, runtime_root=runtime_root)
    spec = load_research_run_spec(run.spec_snapshot_path)
    while True:
        state = read_json_object(run.state_path)
        if state.get("status") == "completed":
            return _loop_result(research_run_id, state)
        if state.get("status") != "running":
            raise ResearchRunError("Research Run state is not running.")
        if len(_experiments(state)) >= _max_experiments(state):
            _complete_research_run(run, state)
            return _loop_result(research_run_id, state)

        result = run_current_phase_once(
            ResearchPhaseInput(
                research_run_id=run.research_run_id,
                run_directory=run.run_directory,
                spec_snapshot_path=run.spec_snapshot_path,
                state_path=run.state_path,
                ledger_path=run.ledger_path,
                experiments_directory=run.experiments_directory,
            ),
            experiment_runner=experiment_runner,
            agent_runtime=agent_runtime,
        )
        if result.get("status") != "experiment_completed":
            return result
        state = read_json_object(run.state_path)
        if should_stop_research_run(
            outcome=str(result.get("outcome")),
            stop_on_prerequisites_failed=spec.stop_on_prerequisites_failed,
        ):
            _complete_research_run(run, state)
            return _loop_result(research_run_id, state)


def run_current_phase_once(
    phase_input: ResearchPhaseInput,
    *,
    experiment_runner: ExperimentRunner | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    state = read_json_object(phase_input.state_path)
    spec = load_research_run_spec(phase_input.spec_snapshot_path)
    if state.get("current_phase") not in {"initialized", "ready_for_experiment"}:
        raise ResearchRunError(
            f"Research phase is not ready for an experiment: {state.get('current_phase')}"
        )

    experiment_id = next_experiment_id(state)
    experiment_dir = experiment_directory(phase_input.run_directory, experiment_id)
    if experiment_dir.exists():
        raise ResearchRunError(f"Research Experiment already exists: {experiment_id}")
    experiment_dir.mkdir(parents=True)

    state["active_experiment_id"] = experiment_id
    state["current_phase"] = "running_experiment"
    write_json(phase_input.state_path, state)
    append_ledger_event(
        phase_input.ledger_path,
        event_type="phase_changed",
        research_run_id=phase_input.research_run_id,
        current_phase="running_experiment",
        experiment_id=experiment_id,
    )

    runner = experiment_runner or _default_experiment_runner(agent_runtime)
    request = ExperimentFlowRequest(
        research_run_id=phase_input.research_run_id,
        experiment_id=experiment_id,
        run_directory=phase_input.run_directory,
        experiment_directory=experiment_dir,
        ledger_path=phase_input.ledger_path,
        spec=spec,
        state=state,
    )
    try:
        result = runner(request)
    except Exception as exc:
        terminal_summary = classify_run_failed(
            str(exc) or type(exc).__name__,
            failure_classification="runner_exception",
        ).model_dump(mode="json")
        write_json(experiment_dir / "summary.json", terminal_summary)
        return _record_terminal_result(
            phase_input,
            state,
            experiment_id=experiment_id,
            experiment_dir=experiment_dir,
        )

    if result.get("status") != "experiment_completed":
        terminal_summary = classify_run_failed(
            _non_completed_reason(result),
            failure_classification=_failure_classification(result),
        ).model_dump(mode="json")
        write_json(experiment_dir / "summary.json", terminal_summary)
        return _record_terminal_result(
            phase_input,
            state,
            experiment_id=experiment_id,
            experiment_dir=experiment_dir,
        )

    return _record_terminal_result(
        phase_input,
        state,
        experiment_id=experiment_id,
        experiment_dir=experiment_dir,
    )


def _record_terminal_result(
    phase_input: ResearchPhaseInput,
    state: dict[str, Any],
    *,
    experiment_id: str,
    experiment_dir: Path,
) -> dict[str, Any]:
    terminal_summary = load_terminal_summary(experiment_dir)
    record_terminal_experiment(
        state,
        experiment_id=experiment_id,
        experiment_dir=experiment_dir,
        terminal_summary=terminal_summary,
    )
    state["current_phase"] = "ready_for_experiment"
    write_json(phase_input.state_path, state)
    append_ledger_event(
        phase_input.ledger_path,
        event_type="experiment_completed",
        research_run_id=phase_input.research_run_id,
        experiment_id=experiment_id,
        outcome=terminal_summary["outcome"],
    )
    return {
        "status": "experiment_completed",
        "experiment_id": experiment_id,
        **terminal_summary,
    }


def _non_completed_reason(result: dict[str, Any]) -> str:
    reason = result.get("outcome_reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    return f"Experiment runner returned non-terminal status: {result.get('status')}."


def _failure_classification(result: dict[str, Any]) -> str:
    status = result.get("status")
    if isinstance(status, str) and status.strip():
        return status
    return "non_completed_runner_result"


def _default_experiment_runner(
    agent_runtime: Any | None,
) -> ExperimentRunner:
    def runner(request: ExperimentFlowRequest) -> dict[str, Any]:
        return run_experiment_flow(request, agent_runtime=agent_runtime)

    return runner


def _experiments(state: dict[str, Any]) -> dict[str, Any]:
    experiments = state.get("experiments")
    if not isinstance(experiments, dict):
        raise ResearchRunError("Research Run state experiments must be an object.")
    return experiments


def _max_experiments(state: dict[str, Any]) -> int:
    max_experiments = state.get("max_experiments")
    if isinstance(max_experiments, bool) or not isinstance(max_experiments, int):
        raise ResearchRunError("Research Run state max_experiments must be an integer.")
    return max_experiments


def _complete_research_run(run: ResearchRun, state: dict[str, Any]) -> None:
    state["status"] = "completed"
    state["current_phase"] = "completed"
    state["active_experiment_id"] = None
    write_json(run.state_path, state)
    append_ledger_event(
        run.ledger_path,
        event_type="phase_changed",
        research_run_id=run.research_run_id,
        current_phase="completed",
    )


def _loop_result(research_run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "completed",
        "research_run_id": research_run_id,
        "experiments_completed": len(_experiments(state)),
    }
