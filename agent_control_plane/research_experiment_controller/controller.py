from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.control_plane.usage_limit import UsageLimitWait
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
    load_research_run_spec_snapshot,
    resolved_spec_dict,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.research_state import (
    ensure_research_state,
    import_run_dirs_into_research_state,
    merge_terminal_experiment,
)
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    load_terminal_summary,
    next_experiment_id,
    record_terminal_experiment,
)


@dataclass(frozen=True)
class ResearchRun:
    research_run_id: str
    paths: ResearchProgramPaths
    state: dict[str, Any]

    @property
    def research_program_root(self) -> Path:
        return Path(self.paths.root)

    @property
    def run_directory(self) -> Path:
        return self.paths.run_directory(self.research_run_id)

    @property
    def spec_snapshot_path(self) -> Path:
        return self.paths.spec_snapshot_path(self.research_run_id)

    @property
    def state_path(self) -> Path:
        return self.paths.state_path(self.research_run_id)

    @property
    def ledger_path(self) -> Path:
        return self.paths.ledger_path(self.research_run_id)

    @property
    def experiments_directory(self) -> Path:
        return self.paths.experiments_directory(self.research_run_id)


class ResearchRunError(RuntimeError):
    """Raised when a Research Run cannot be started or loaded."""


ExperimentRunner = Callable[[ExperimentFlowRequest], dict[str, Any]]


def start_research_run(
    research_run_spec_path: str | Path,
) -> ResearchRun:
    spec = load_research_run_spec(research_run_spec_path)
    paths = spec.research_program.paths
    run_directory = paths.run_directory(spec.research_run_id)
    paths.create_directories()
    try:
        run_directory.mkdir(parents=True)
    except FileExistsError as exc:
        raise ResearchRunError(
            f"Research Run already exists: {spec.research_run_id}"
        ) from exc
    try:
        ensure_research_state(paths)
        if spec.continuation.prior_run_dirs:
            import_run_dirs_into_research_state(
                paths=paths,
                prior_run_dirs=spec.continuation.prior_run_dirs,
            )

        spec_snapshot_path = run_directory / "research_run_spec.yaml"
        state_path = run_directory / "state.json"
        ledger_path = run_directory / "ledger.jsonl"
        experiments_directory = run_directory / "experiments"
        experiments_directory.mkdir()

        spec_snapshot_path.write_text(
            yaml.safe_dump(
                resolved_spec_dict(spec, include_research_program_root=False),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        state = create_initial_state(
            research_run_id=spec.research_run_id,
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
    except Exception:
        if run_directory.exists():
            shutil.rmtree(run_directory)
        raise

    return ResearchRun(
        research_run_id=spec.research_run_id,
        paths=paths,
        state=state,
    )


def load_research_run(
    research_run_id: str,
    *,
    research_program_root: str | Path,
) -> ResearchRun:
    paths = ResearchProgramPaths(research_program_root)
    run_directory = paths.run_directory(research_run_id)
    spec_snapshot_path = paths.spec_snapshot_path(research_run_id)
    state_path = paths.state_path(research_run_id)
    ledger_path = paths.ledger_path(research_run_id)
    experiments_directory = paths.experiments_directory(research_run_id)

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

    snapshot = load_research_run_spec_snapshot(
        spec_snapshot_path,
        research_program_root=paths.root,
    )
    state = read_json_object(state_path)
    if snapshot.research_run_id != research_run_id:
        raise ResearchRunError(
            "Research Run snapshot does not match requested Research Run ID."
        )
    if state.get("research_run_id") != research_run_id:
        raise ResearchRunError(
            "Research Run state does not match requested Research Run ID."
        )

    return ResearchRun(
        research_run_id=research_run_id,
        paths=paths,
        state=state,
    )


def run_research_loop(
    research_run_id: str,
    *,
    research_program_root: str | Path,
    experiment_runner: ExperimentRunner | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    run = load_research_run(
        research_run_id,
        research_program_root=research_program_root,
    )
    spec = load_research_run_spec_snapshot(
        run.spec_snapshot_path,
        research_program_root=run.research_program_root,
    )
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
            run,
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
    run: ResearchRun,
    *,
    experiment_runner: ExperimentRunner | None = None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    state = read_json_object(run.state_path)
    spec = load_research_run_spec_snapshot(
        run.spec_snapshot_path,
        research_program_root=run.research_program_root,
    )
    if state.get("current_phase") not in {"initialized", "ready_for_experiment"}:
        raise ResearchRunError(
            f"Research phase is not ready for an experiment: {state.get('current_phase')}"
        )

    request = ExperimentFlowRequest(
        experiment_id=next_experiment_id(state),
        spec=spec,
        state=state,
    )
    experiment_dir = request.experiment_directory
    if experiment_dir.exists():
        raise ResearchRunError(
            f"Research Experiment already exists: {request.experiment_id}"
        )
    experiment_dir.mkdir(parents=True)

    state["active_experiment_id"] = request.experiment_id
    state["current_phase"] = "running_experiment"
    write_json(run.state_path, state)
    append_ledger_event(
        run.ledger_path,
        event_type="phase_changed",
        research_run_id=run.research_run_id,
        current_phase="running_experiment",
        experiment_id=request.experiment_id,
    )

    runner = experiment_runner or _default_experiment_runner(agent_runtime)
    try:
        result = runner(request)
    except UsageLimitWait as exc:
        return _propagate_usage_limit_wait(
            run,
            state,
            request=request,
            sleep_seconds=exc.event.sleep_seconds,
        )
    except Exception as exc:
        terminal_summary = classify_run_failed(
            str(exc) or type(exc).__name__,
            failure_classification="runner_exception",
        ).model_dump(mode="json")
        write_json(experiment_dir / "summary.json", terminal_summary)
        return _record_terminal_result(
            run,
            state,
            experiment_id=request.experiment_id,
            experiment_dir=experiment_dir,
        )

    if result.get("status") == "usage_limit_wait":
        return _propagate_usage_limit_wait(
            run,
            state,
            request=request,
            sleep_seconds=float(result["sleep_seconds"]),
        )

    if result.get("status") != "experiment_completed":
        terminal_summary = classify_run_failed(
            _non_completed_reason(result),
            failure_classification=_failure_classification(result),
        ).model_dump(mode="json")
        write_json(experiment_dir / "summary.json", terminal_summary)
        return _record_terminal_result(
            run,
            state,
            experiment_id=request.experiment_id,
            experiment_dir=experiment_dir,
        )

    return _record_terminal_result(
        run,
        state,
        experiment_id=request.experiment_id,
        experiment_dir=experiment_dir,
    )


def _propagate_usage_limit_wait(
    run: ResearchRun,
    state: dict[str, Any],
    *,
    request: ExperimentFlowRequest,
    sleep_seconds: float,
) -> dict[str, Any]:
    state["active_experiment_id"] = None
    state["current_phase"] = "ready_for_experiment"
    write_json(run.state_path, state)
    for cleanup_dir in (
        request.experiment_directory,
        request.experiment_data_directory,
    ):
        if cleanup_dir.exists():
            shutil.rmtree(cleanup_dir)
    append_ledger_event(
        run.ledger_path,
        event_type="usage_limit_wait",
        research_run_id=run.research_run_id,
        experiment_id=request.experiment_id,
        sleep_seconds=max(sleep_seconds, 0.0),
    )
    return {
        "status": "usage_limit_wait",
        "research_run_id": run.research_run_id,
        "experiment_id": request.experiment_id,
        "current_phase": state["current_phase"],
        "controller_state_version": state.get("controller_state_version"),
        "sleep_seconds": max(sleep_seconds, 0.0),
    }


def _record_terminal_result(
    run: ResearchRun,
    state: dict[str, Any],
    *,
    experiment_id: str,
    experiment_dir: Path,
) -> dict[str, Any]:
    terminal_summary = load_terminal_summary(experiment_dir)
    merge_terminal_experiment(
        paths=run.paths,
        research_run_id=run.research_run_id,
        experiment_id=experiment_id,
        experiment_dir=experiment_dir,
    )
    record_terminal_experiment(
        state,
        experiment_id=experiment_id,
        experiment_dir=experiment_dir,
        terminal_summary=terminal_summary,
    )
    state["current_phase"] = "ready_for_experiment"
    write_json(run.state_path, state)
    append_ledger_event(
        run.ledger_path,
        event_type="experiment_completed",
        research_run_id=run.research_run_id,
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
