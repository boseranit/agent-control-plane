from __future__ import annotations

import asyncio
import subprocess
from dataclasses import is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.control_plane.usage_limit import (
    UsageLimitEvent,
    UsageLimitWait,
)
from agent_control_plane.research_experiment_controller import hatchet_workflow
from agent_control_plane.research_experiment_controller.controller import (
    run_research_loop,
    start_research_run,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    ExperimentDesign,
    SelectedPlan,
)
from agent_control_plane.research_experiment_controller.experiment_flow import (
    ExperimentFlowSelection,
    ExperimentFlowRequest,
    run_experiment_flow,
)
from agent_control_plane.research_experiment_controller.hatchet_workflow import (
    build_hatchet_workflows,
)
from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
    run_research_shell,
)


class FakeHatchet:
    def __init__(self) -> None:
        self.registrations: list[tuple[str, str]] = []
        self.registration_kwargs: list[dict[str, object]] = []

    def durable_task(self, **kwargs: object) -> Any:
        self.registrations.append(("durable", str(kwargs["name"])))
        self.registration_kwargs.append(dict(kwargs))

        def register(function: Any) -> Any:
            return function

        return register

    def task(self, **kwargs: object) -> Any:
        self.registrations.append(("task", str(kwargs["name"])))

        def register(function: Any) -> Any:
            return function

        return register


class FakeDurableContext:
    def __init__(self) -> None:
        self.sleeps: list[timedelta] = []
        self.additional_metadata: dict[str, object] = {}

    async def aio_sleep_for(
        self, duration: timedelta, label: str | None = None
    ) -> None:
        del label
        self.sleeps.append(duration)


def test_build_hatchet_workflows_registers_only_durable_research_run() -> None:
    hatchet = FakeHatchet()

    workflows = build_hatchet_workflows(hatchet)

    assert len(workflows) == 1
    assert hatchet.registrations == [("durable", "research-run")]


def test_shell_input_is_dataclass_and_hatchet_input_is_adapter_pydantic() -> None:
    hatchet = FakeHatchet()

    build_hatchet_workflows(hatchet)

    input_validator = hatchet.registration_kwargs[0]["input_validator"]
    assert is_dataclass(ResearchRunInput)
    assert not issubclass(ResearchRunInput, BaseModel)
    assert input_validator is hatchet_workflow.HatchetResearchRunInput
    assert issubclass(hatchet_workflow.HatchetResearchRunInput, BaseModel)


def test_run_research_shell_delegates_once_and_returns_result() -> None:
    seen: list[ResearchRunInput] = []

    def controller_runner(input: ResearchRunInput) -> dict[str, object]:
        seen.append(input)
        return {
            "status": "completed",
            "research_run_id": input.research_run_id,
            "experiments_completed": 1,
        }

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(research_run_id="run-1", runtime_root="tmp-runs"),
            controller_runner=controller_runner,
        )
    )

    assert result == {
        "status": "completed",
        "research_run_id": "run-1",
        "experiments_completed": 1,
    }
    assert seen == [ResearchRunInput(research_run_id="run-1", runtime_root="tmp-runs")]


def test_run_research_shell_reports_only_generic_metadata() -> None:
    metadata: list[dict[str, object]] = []

    def controller_runner(input: ResearchRunInput) -> dict[str, object]:
        return {
            "status": "completed",
            "research_run_id": input.research_run_id,
            "current_phase": "completed",
            "controller_state_version": 1,
            "outcome": "completed_candidate",
            "experiment_id": "EXP-0001",
        }

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(research_run_id="run-1"),
            controller_runner=controller_runner,
            metadata_sink=metadata.append,
        )
    )

    assert result["status"] == "completed"
    assert metadata == [
        {
            "run_id": "run-1",
            "current_phase": "completed",
            "controller_state_version": 1,
            "status": "completed",
        }
    ]


def test_usage_limit_wait_sleeps_durably_and_retries_same_run() -> None:
    seen: list[ResearchRunInput] = []
    sleeps: list[float] = []

    def controller_runner(input: ResearchRunInput) -> dict[str, object]:
        seen.append(input)
        if len(seen) == 1:
            return {"status": "usage_limit_wait", "sleep_seconds": 5.0}
        return {"status": "completed", "research_run_id": input.research_run_id}

    async def durable_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(research_run_id="run-1", runtime_root="tmp-runs"),
            controller_runner=controller_runner,
            durable_sleep=durable_sleep,
        )
    )

    assert result == {"status": "completed", "research_run_id": "run-1"}
    assert sleeps == [5.0]
    assert seen == [
        ResearchRunInput(research_run_id="run-1", runtime_root="tmp-runs"),
        ResearchRunInput(research_run_id="run-1", runtime_root="tmp-runs"),
    ]


def test_controller_usage_limit_wait_sleeps_and_retries_without_run_failed(
    tmp_path: Path,
) -> None:
    spec_path = write_research_run_spec(tmp_path)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    attempts: list[str] = []
    sleeps: list[float] = []

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        attempts.append(request.experiment_id)
        if len(attempts) == 1:
            raise usage_limit_wait(7.0)
        write_json(
            request.experiment_directory / "summary.json",
            {
                "outcome": "no_op",
                "outcome_reason": "Retried after usage limit.",
                "failed_stage": None,
                "failure_classification": None,
                "summary": "Retried after usage limit.",
            },
        )
        return {
            "status": "experiment_completed",
            "experiment_id": request.experiment_id,
            "outcome": "no_op",
        }

    async def durable_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(
                research_run_id=run.research_run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            controller_runner=lambda input: run_research_loop(
                input.research_run_id,
                runtime_root=input.runtime_root,
                experiment_runner=experiment_runner,
            ),
            durable_sleep=durable_sleep,
        )
    )

    state = read_json_object(run.state_path)
    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result == {
        "status": "completed",
        "research_run_id": run.research_run_id,
        "experiments_completed": 1,
    }
    assert sleeps == [7.0]
    assert attempts == ["EXP-0001", "EXP-0001"]
    assert state["experiments"]["EXP-0001"]["outcome"] == "no_op"
    assert summary["outcome"] == "no_op"
    assert summary["failure_classification"] is None


def test_evaluation_agent_usage_limit_wait_sleeps_and_retries_without_run_failed(
    tmp_path: Path,
) -> None:
    spec_path = write_research_run_spec(tmp_path)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    runtime = UsageLimitThenEvaluationRuntime()
    sleeps: list[float] = []
    selection = ExperimentFlowSelection(
        selected_plan=SelectedPlan(
            selected=True,
            plan_id="eval-plan",
            rationale="Needs evaluator.",
        ),
        experiment_design=ExperimentDesign(
            confirmatory_commands=[{"name": "eval", "argv": ["/bin/true"]}]
        ),
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=selection,
            agent_runtime=runtime,
        )

    async def durable_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(
                research_run_id=run.research_run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            controller_runner=lambda input: run_research_loop(
                input.research_run_id,
                runtime_root=input.runtime_root,
                experiment_runner=experiment_runner,
            ),
            durable_sleep=durable_sleep,
        )
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result["status"] == "completed"
    assert sleeps == [9.0]
    assert runtime.run_calls == 2
    assert summary["outcome"] == "completed_candidate"
    assert summary["failure_classification"] is None


def test_plain_evaluation_usage_limit_error_sleeps_durably_not_run_failed(
    tmp_path: Path,
) -> None:
    spec_path = write_research_run_spec(tmp_path)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    runtime = PlainUsageLimitThenEvaluationRuntime()
    sleeps: list[float] = []
    selection = ExperimentFlowSelection(
        selected_plan=SelectedPlan(
            selected=True,
            plan_id="plain-usage-limit-plan",
            rationale="Needs evaluator.",
        ),
        experiment_design=ExperimentDesign(
            confirmatory_commands=[{"name": "eval", "argv": ["/bin/true"]}]
        ),
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=selection,
            agent_runtime=runtime,
        )

    async def durable_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(
                research_run_id=run.research_run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            controller_runner=lambda input: run_research_loop(
                input.research_run_id,
                runtime_root=input.runtime_root,
                experiment_runner=experiment_runner,
            ),
            durable_sleep=durable_sleep,
        )
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    assert result["status"] == "completed"
    assert sleeps == [13.0]
    assert runtime.run_calls == 2
    assert summary["outcome"] == "completed_candidate"
    assert summary["failure_classification"] is None


def test_usage_limit_retry_removes_dirty_in_progress_worktree(
    tmp_path: Path,
) -> None:
    spec_path = write_research_run_spec(tmp_path, worktree_create=True)
    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")
    runtime = DirtyWorktreeUsageLimitThenEvaluationRuntime()
    sleeps: list[float] = []
    selection = ExperimentFlowSelection(
        selected_plan=SelectedPlan(
            selected=True,
            plan_id="dirty-worktree-plan",
            rationale="Needs worktree and evaluator.",
        ),
        experiment_design=ExperimentDesign(
            confirmatory_commands=[{"name": "eval", "argv": ["/bin/true"]}]
        ),
    )

    def experiment_runner(request: ExperimentFlowRequest) -> dict[str, object]:
        return run_experiment_flow(
            request,
            selection=selection,
            agent_runtime=runtime,
        )

    async def durable_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        run_research_shell(
            ResearchRunInput(
                research_run_id=run.research_run_id,
                runtime_root=str(tmp_path / "runs"),
            ),
            controller_runner=lambda input: run_research_loop(
                input.research_run_id,
                runtime_root=input.runtime_root,
                experiment_runner=experiment_runner,
            ),
            durable_sleep=durable_sleep,
        )
    )

    summary = read_json_object(run.experiments_directory / "EXP-0001" / "summary.json")
    worktree_path = (
        (tmp_path / "repo").resolve() / ".worktrees" / run.research_run_id / "EXP-0001"
    )
    assert result["status"] == "completed"
    assert sleeps == [11.0]
    assert runtime.run_calls == 2
    assert summary["outcome"] == "completed_candidate"
    assert summary["failure_classification"] is None
    assert not (worktree_path / "dirty.txt").exists()


def test_hatchet_workflow_delegates_to_shell_with_ctx_sleep_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_shell(
        input: ResearchRunInput,
        *,
        controller_runner: object,
        durable_sleep: object,
        metadata_sink: object,
    ) -> dict[str, object]:
        del controller_runner
        metadata_sink(
            {
                "run_id": input.research_run_id,
                "current_phase": "completed",
                "controller_state_version": 1,
                "status": "completed",
            }
        )
        await durable_sleep(3.0)
        return {"status": "completed", "research_run_id": input.research_run_id}

    monkeypatch.setattr(hatchet_workflow, "run_research_shell", fake_shell)
    workflow = build_hatchet_workflows(FakeHatchet())[0]
    ctx = FakeDurableContext()

    result = asyncio.run(workflow(ResearchRunInput(research_run_id="run-1"), ctx))

    assert result == {"status": "completed", "research_run_id": "run-1"}
    assert ctx.sleeps == [timedelta(seconds=3)]
    assert ctx.additional_metadata == {
        "run_id": "run-1",
        "current_phase": "completed",
        "controller_state_version": 1,
        "status": "completed",
    }


def test_hatchet_worker_starts_research_experiment_controller_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_control_plane.research_experiment_controller import hatchet_worker

    class FakeWorker:
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    class FakeHatchetClient:
        def __init__(self) -> None:
            self.worker_instance = FakeWorker()
            self.worker_kwargs: dict[str, object] | None = None

        def worker(self, name: str, **kwargs: object) -> FakeWorker:
            self.worker_kwargs = {"name": name, **kwargs}
            return self.worker_instance

    fake_hatchet = FakeHatchetClient()
    monkeypatch.setattr(hatchet_worker, "Hatchet", lambda: fake_hatchet)
    monkeypatch.setattr(
        hatchet_worker,
        "build_hatchet_workflows",
        lambda hatchet: ["research-workflow"],
    )

    hatchet_worker.main()

    assert fake_hatchet.worker_kwargs == {
        "name": "research-experiment-controller",
        "workflows": ["research-workflow"],
        "slots": 1,
        "durable_slots": 1,
    }
    assert fake_hatchet.worker_instance.started is True


def test_hatchet_sdk_imports_stay_in_research_adapter_modules() -> None:
    package_dir = Path(hatchet_workflow.__file__).parent
    allowed = {"hatchet_workflow.py", "hatchet_worker.py"}
    offenders = [
        path.name
        for path in package_dir.glob("*.py")
        if "hatchet_sdk" in path.read_text(encoding="utf-8")
        and path.name not in allowed
    ]

    assert offenders == []


def test_research_hatchet_adapter_has_no_human_event_wait_path() -> None:
    package_dir = Path(hatchet_workflow.__file__).parent
    checked = [
        package_dir / "durable_shell.py",
        package_dir / "hatchet_workflow.py",
        package_dir / "hatchet_worker.py",
    ]

    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert "aio_wait_for_event" not in text
        assert "approval" not in text.lower()


def test_controller_does_not_run_git_subprocess_for_worktree_cleanup() -> None:
    controller_path = Path(
        "agent_control_plane/research_experiment_controller/controller.py"
    )
    text = controller_path.read_text(encoding="utf-8")

    assert "subprocess" not in text
    assert "git worktree" not in text


def write_research_run_spec(tmp_path: Path, *, worktree_create: bool = False) -> Path:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo.mkdir()
    data_root.mkdir()
    init_git_repo(repo)
    path = tmp_path / "research-run.yaml"
    path.write_text(
        f"""
research_run_id: usage-limit-run
target_repository: {repo}
max_experiments: 1
research_brief: |
  Test usage-limit propagation.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {data_root}
worktree:
  create: {str(worktree_create).lower()}
implementation:
  max_repairs: 1
""",
        encoding="utf-8",
    )
    return path


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def usage_limit_wait(seconds: float) -> UsageLimitWait:
    detected_at = datetime.fromisoformat("2026-06-01T10:00:00+10:00")
    return UsageLimitWait(
        UsageLimitEvent(
            role="research-implementer",
            detected_at=detected_at,
            suggested_retry_at=detected_at + timedelta(seconds=seconds),
            sleep_seconds=seconds,
            message="Usage limit reached.",
        )
    )


class UsageLimitThenEvaluationRuntime:
    def __init__(self) -> None:
        self.run_calls = 0

    def open_thread(self, config: object) -> object:
        del config
        return UsageLimitThenEvaluationThread(self)


class UsageLimitThenEvaluationThread:
    id = "research-evaluator-thread"

    def __init__(self, runtime: UsageLimitThenEvaluationRuntime) -> None:
        self.runtime = runtime

    def run(self, input: str, config: object) -> object:
        del input, config
        self.runtime.run_calls += 1
        if self.runtime.run_calls == 1:
            raise usage_limit_wait(9.0)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "confirmatory_evaluation_result": {
                        "outcome": "completed_candidate",
                        "outcome_reason": "Retry produced evidence.",
                        "failed_stage": None,
                        "failure_classification": None,
                        "metrics": {"ic": 0.03},
                        "gate_results": {"ic": "passed"},
                        "pre_registered_evidence": ["confirmatory retry"],
                    },
                    "exploratory_diagnostics_result": {},
                    "analysis_ledger": {"entries": []},
                }
            },
        )()


class PlainUsageLimitThenEvaluationRuntime:
    def __init__(self) -> None:
        self.run_calls = 0

    def open_thread(self, config: object) -> object:
        del config
        return PlainUsageLimitThenEvaluationThread(self)


class PlainUsageLimitThenEvaluationThread:
    id = "research-evaluator-thread"

    def __init__(self, runtime: PlainUsageLimitThenEvaluationRuntime) -> None:
        self.runtime = runtime

    def run(self, input: str, config: object) -> object:
        del input, config
        self.runtime.run_calls += 1
        if self.runtime.run_calls == 1:
            raise RuntimeError("Usage limit reached. retry-after: 13")
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "confirmatory_evaluation_result": {
                        "outcome": "completed_candidate",
                        "outcome_reason": "Retry after parsed usage limit.",
                        "failed_stage": None,
                        "failure_classification": None,
                        "metrics": {"ic": 0.05},
                        "gate_results": {"ic": "passed"},
                        "pre_registered_evidence": ["parsed usage retry"],
                    },
                    "exploratory_diagnostics_result": {},
                    "analysis_ledger": {"entries": []},
                }
            },
        )()


class DirtyWorktreeUsageLimitThenEvaluationRuntime:
    def __init__(self) -> None:
        self.run_calls = 0

    def open_thread(self, config: object) -> object:
        return DirtyWorktreeUsageLimitThenEvaluationThread(self, config)


class DirtyWorktreeUsageLimitThenEvaluationThread:
    id = "research-evaluator-thread"

    def __init__(
        self,
        runtime: DirtyWorktreeUsageLimitThenEvaluationRuntime,
        config: object,
    ) -> None:
        self.runtime = runtime
        self.config = config

    def run(self, input: str, config: object) -> object:
        del input
        self.runtime.run_calls += 1
        if self.runtime.run_calls == 1:
            worktree_path = _manifest_worktree_path(config)
            (worktree_path / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            raise usage_limit_wait(11.0)
        return type(
            "TurnResult",
            (),
            {
                "final_response": {
                    "confirmatory_evaluation_result": {
                        "outcome": "completed_candidate",
                        "outcome_reason": "Retry used a clean worktree.",
                        "failed_stage": None,
                        "failure_classification": None,
                        "metrics": {"ic": 0.04},
                        "gate_results": {"ic": "passed"},
                        "pre_registered_evidence": ["clean retry"],
                    },
                    "exploratory_diagnostics_result": {},
                    "analysis_ledger": {"entries": []},
                }
            },
        )()


def _manifest_worktree_path(config: object) -> Path:
    manifest = read_json_object(Path(getattr(config, "cwd")) / "manifest.json")
    return Path(str(manifest["worktree_path"]))
