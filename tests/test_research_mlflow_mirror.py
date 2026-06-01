from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller import experiment_flow
from agent_control_plane.research_experiment_controller.experiment_flow import (
    ExperimentFlowRequest,
    ExperimentFlowSelection,
    run_experiment_flow,
)
from agent_control_plane.research_experiment_controller.mlflow_mirror import (
    mirror_to_mlflow,
)
from agent_control_plane.research_experiment_controller.ledger import (
    read_ledger_events,
)
from agent_control_plane.research_experiment_controller.research_run_mirror import (
    ResearchRunMirrorRequest,
    mirror_research_run,
)
from agent_control_plane.research_experiment_controller.research_run_spec import (
    CodexConfig,
    ImplementationConfig,
    MLflowConfig,
    ResearchBudget,
    ResearchRunSpec,
    WorktreeConfig,
)
from agent_control_plane.research_experiment_controller.artifacts import SelectedPlan


class FakeRun:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def __enter__(self) -> "FakeRun":
        self.events.append(("enter_run", None))
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.events.append(("exit_run", None))


class FakeMlflowClient:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def set_tracking_uri(self, uri: str) -> None:
        self.events.append(("set_tracking_uri", uri))

    def set_experiment(self, name: str) -> None:
        self.events.append(("set_experiment", name))

    def start_run(self, *, run_name: str) -> FakeRun:
        self.events.append(("start_run", run_name))
        return FakeRun(self.events)

    def log_params(self, params: dict[str, object]) -> None:
        self.events.append(("log_params", params))

    def set_tags(self, tags: dict[str, object]) -> None:
        self.events.append(("set_tags", tags))

    def log_metric(self, key: str, value: float) -> None:
        self.events.append(("log_metric", (key, value)))

    def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None:
        self.events.append(("log_artifact", (local_path, artifact_path)))


class FailingMirror:
    def __call__(self, request: ResearchRunMirrorRequest) -> dict[str, object]:
        del request
        raise RuntimeError("mlflow down")


def test_mirror_to_mlflow_logs_only_approved_params_and_tags(
    tmp_path: Path,
) -> None:
    client = FakeMlflowClient()

    result = mirror_to_mlflow(
        ResearchRunMirrorRequest(
            run_dir=tmp_path,
            tracking_uri="file:/tmp/mlruns",
            experiment_name="peer-residual-v1",
            research_run_id="run-1",
            experiment_id="EXP-0001",
            outcome="completed_candidate",
            failed_stage=None,
            failure_classification=None,
            git_sha="abc123",
        ),
        mlflow_client=client,
    )

    assert result == {"status": "mirrored"}
    assert ("set_tracking_uri", "file:/tmp/mlruns") in client.events
    assert ("set_experiment", "peer-residual-v1") in client.events
    assert ("start_run", "EXP-0001") in client.events
    assert (
        "log_params",
        {
            "research_run_id": "run-1",
            "experiment_id": "EXP-0001",
        },
    ) in client.events
    assert (
        "set_tags",
        {
            "outcome": "completed_candidate",
            "failed_stage": "",
            "failure_classification": "",
            "git_sha": "abc123",
        },
    ) in client.events


def test_mirror_to_mlflow_flattens_numeric_metrics_from_allowed_files(
    tmp_path: Path,
) -> None:
    write_json(
        tmp_path / "command_metrics.json",
        {
            "command_count": 3,
            "passed": True,
            "nested": {"duration_seconds": 1.5, "ignored": None},
        },
    )
    write_json(
        tmp_path / "metrics.json",
        {"ic": 0.04, "label": "peer-residual", "drawdown": -0.2},
    )
    write_json(
        tmp_path / "confirmatory_evaluation_result.json",
        {
            "metrics": {"sharpe": 1.2, "by_month": [0.1, False, "skip"]},
            "gate_results": {"passed_count": 2},
        },
    )
    write_json(tmp_path / "ignored.json", {"not_logged": 99})
    client = FakeMlflowClient()

    mirror_to_mlflow(
        ResearchRunMirrorRequest(
            run_dir=tmp_path,
            tracking_uri=None,
            experiment_name=None,
            research_run_id="run-1",
            experiment_id="EXP-0001",
            outcome="completed_candidate",
            failed_stage=None,
            failure_classification=None,
            git_sha="abc123",
        ),
        mlflow_client=client,
    )

    assert set(event for event in client.events if event[0] == "log_metric") == {
        ("log_metric", ("command_metrics.command_count", 3.0)),
        ("log_metric", ("command_metrics.nested.duration_seconds", 1.5)),
        ("log_metric", ("metrics.drawdown", -0.2)),
        ("log_metric", ("metrics.ic", 0.04)),
        (
            "log_metric",
            ("confirmatory_evaluation_result.gate_results.passed_count", 2.0),
        ),
        ("log_metric", ("confirmatory_evaluation_result.metrics.by_month.0", 0.1)),
        ("log_metric", ("confirmatory_evaluation_result.metrics.sharpe", 1.2)),
    }


def test_mirror_to_mlflow_logs_all_run_artifacts_recursively_sorted(
    tmp_path: Path,
) -> None:
    (tmp_path / "nested" / "deep").mkdir(parents=True)
    (tmp_path / "nested" / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "nested" / "deep" / "c.txt").write_text("c\n", encoding="utf-8")
    client = FakeMlflowClient()

    mirror_to_mlflow(
        ResearchRunMirrorRequest(
            run_dir=tmp_path,
            tracking_uri=None,
            experiment_name=None,
            research_run_id="run-1",
            experiment_id="EXP-0001",
            outcome="completed_candidate",
            failed_stage=None,
            failure_classification=None,
            git_sha="abc123",
        ),
        mlflow_client=client,
    )

    assert set(event for event in client.events if event[0] == "log_artifact") == {
        ("log_artifact", (str(tmp_path / "a.txt"), None)),
        ("log_artifact", (str(tmp_path / "nested" / "b.txt"), "nested")),
        (
            "log_artifact",
            (str(tmp_path / "nested" / "deep" / "c.txt"), "nested/deep"),
        ),
    }


def test_mirror_failure_appends_ledger_event_and_continues(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"

    result = mirror_research_run(
        ResearchRunMirrorRequest(
            run_dir=tmp_path,
            tracking_uri="file:/tmp/mlruns",
            experiment_name="peer-residual-v1",
            research_run_id="run-1",
            experiment_id="EXP-0001",
            outcome="completed_rejected",
            failed_stage=None,
            failure_classification=None,
            git_sha="abc123",
        ),
        ledger_path=ledger_path,
        mirror=FailingMirror(),
    )

    assert result == {"status": "mlflow_mirror_failed", "message": "mlflow down"}
    assert read_ledger_events(ledger_path) == [
        {
            "event_type": "mlflow_mirror_failed",
            "research_run_id": "run-1",
            "experiment_id": "EXP-0001",
            "message": "mlflow down",
        }
    ]


def test_run_experiment_flow_mirrors_after_summary_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    git_sha = _init_git_repo(repo)
    run_dir = tmp_path / "run"
    experiment_dir = run_dir / "experiments" / "EXP-0001"
    calls: list[tuple[ResearchRunMirrorRequest, Path]] = []

    def fake_mirror(
        request: ResearchRunMirrorRequest,
        *,
        ledger_path: str | Path,
    ) -> dict[str, str]:
        assert (experiment_dir / "summary.json").exists()
        calls.append((request, Path(ledger_path)))
        return {"status": "mirrored"}

    monkeypatch.setattr(experiment_flow, "mirror_research_run", fake_mirror)

    result = run_experiment_flow(
        ExperimentFlowRequest(
            research_run_id="run-1",
            experiment_id="EXP-0001",
            run_directory=run_dir,
            experiment_directory=experiment_dir,
            ledger_path=run_dir / "ledger.jsonl",
            spec=_spec(tmp_path, repo, mlflow_enabled=True),
            state={"threads": {}},
        ),
        selection=ExperimentFlowSelection(
            selected_plan=SelectedPlan(
                selected=False,
                rationale="No admissible experiment selected.",
            ),
            experiment_design=None,
        ),
    )

    assert result["status"] == "experiment_completed"
    assert len(calls) == 1
    request, ledger_path = calls[0]
    assert Path(request.run_dir) == experiment_dir
    assert request.tracking_uri == "file:/tmp/mlruns"
    assert request.experiment_name == "peer-residual-v1"
    assert request.research_run_id == "run-1"
    assert request.experiment_id == "EXP-0001"
    assert request.outcome == "no_op"
    assert request.failed_stage is None
    assert request.failure_classification is None
    assert request.git_sha == git_sha
    assert ledger_path == run_dir / "ledger.jsonl"


def test_run_experiment_flow_skips_mirror_when_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    def fail_if_called(*args, **kwargs) -> dict[str, str]:
        del args, kwargs
        raise AssertionError("mirror should not run")

    monkeypatch.setattr(experiment_flow, "mirror_research_run", fail_if_called)

    result = run_experiment_flow(
        ExperimentFlowRequest(
            research_run_id="run-1",
            experiment_id="EXP-0001",
            run_directory=tmp_path / "run",
            experiment_directory=tmp_path / "run" / "experiments" / "EXP-0001",
            ledger_path=tmp_path / "run" / "ledger.jsonl",
            spec=_spec(tmp_path, repo, mlflow_enabled=False),
            state={"threads": {}},
        ),
        selection=ExperimentFlowSelection(
            selected_plan=SelectedPlan(
                selected=False,
                rationale="No admissible experiment selected.",
            ),
            experiment_design=None,
        ),
    )

    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "no_op"


def test_run_experiment_flow_ignores_mirror_failure_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    def failing_mirror_status(*args, **kwargs) -> dict[str, str]:
        del args, kwargs
        return {"status": "mlflow_mirror_failed", "message": "mlflow down"}

    monkeypatch.setattr(experiment_flow, "mirror_research_run", failing_mirror_status)

    result = run_experiment_flow(
        ExperimentFlowRequest(
            research_run_id="run-1",
            experiment_id="EXP-0001",
            run_directory=tmp_path / "run",
            experiment_directory=tmp_path / "run" / "experiments" / "EXP-0001",
            ledger_path=tmp_path / "run" / "ledger.jsonl",
            spec=_spec(tmp_path, repo, mlflow_enabled=True),
            state={"threads": {}},
        ),
        selection=ExperimentFlowSelection(
            selected_plan=SelectedPlan(
                selected=False,
                rationale="No admissible experiment selected.",
            ),
            experiment_design=None,
        ),
    )

    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "no_op"
    assert result["failure_classification"] is None


def test_mlflow_import_boundary() -> None:
    package_root = (
        Path(__file__).resolve().parents[1]
        / "agent_control_plane"
        / "research_experiment_controller"
    )
    mlflow_imports: list[str] = []
    adapter_imports: list[str] = []

    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "mlflow" or alias.name.startswith("mlflow."):
                        mlflow_imports.append(path.name)
                    if alias.name.endswith(".mlflow_mirror"):
                        adapter_imports.append(path.name)
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "mlflow" or module.startswith("mlflow."):
                    mlflow_imports.append(path.name)
                if module.endswith(".mlflow_mirror"):
                    adapter_imports.append(path.name)

    assert mlflow_imports == ["mlflow_mirror.py"]
    assert adapter_imports == ["research_run_mirror.py"]


def _init_git_repo(path: Path) -> str:
    path.mkdir()
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
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _spec(tmp_path: Path, repo: Path, *, mlflow_enabled: bool) -> ResearchRunSpec:
    budget = ResearchBudget(
        month_start="2026-01",
        month_end="2026-01",
        max_runtime_minutes=5,
    )
    return ResearchRunSpec(
        source_path=tmp_path / "spec.yaml",
        version=1,
        research_run_id="run-1",
        target_repository=repo,
        max_experiments=1,
        research_brief="Test mirror wiring.",
        budget="smoke",
        budgets={"smoke": budget},
        selected_budget=budget,
        data_root=tmp_path / "data",
        worktree=WorktreeConfig(create=False, root=Path(".worktrees")),
        mlflow=MLflowConfig(
            enabled=mlflow_enabled,
            tracking_uri="file:/tmp/mlruns",
            experiment_name="peer-residual-v1",
        ),
        codex=CodexConfig(),
        implementation=ImplementationConfig(),
        stop_on_prerequisites_failed=True,
    )
