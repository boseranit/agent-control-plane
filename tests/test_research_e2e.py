from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import (
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.controller import (
    run_research_loop,
    start_research_run,
)
from research_helpers import (
    experiment_signal_panel_path,
    signal_panel_writer_command,
    write_evaluation_result_files,
)


def test_fake_runtime_drives_completed_candidate_research_run(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime()
    target_head_before = _git_head(repo)

    run = start_research_run(spec_path)
    result = run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    state = read_json_object(run.state_path)
    assert result == {
        "status": "completed",
        "research_run_id": "e2e-run",
        "experiments_completed": 1,
    }
    assert state["status"] == "completed"
    assert state["current_phase"] == "completed"
    assert state["experiments"]["EXP-0001"]["outcome"] == "completed_candidate"
    assert _git_head(repo) == target_head_before

    expected_artifacts = {
        "context_pack.md",
        "context_summary.json",
        "proposal.json",
        "research_spec.json",
        "experiment_design.json",
        "critique.json",
        "selected_plan.json",
        "data_audit.json",
        "implementation.json",
        "implementation_diff_summary.json",
        "confirmatory_evaluation_result.json",
        "exploratory_diagnostics_result.json",
        "analysis_ledger.json",
        "empirical_critique.json",
        "summary.json",
        "plan_update.json",
    }
    assert expected_artifacts <= {
        path.relative_to(experiment_dir).as_posix()
        for path in experiment_dir.rglob("*")
        if path.is_file()
    }
    assert (experiment_dir / "evaluation" / "manifest.json").exists()
    assert not (experiment_dir / "evaluation" / "eval_inputs").exists()
    assert experiment_signal_panel_path(
        tmp_path / "experiment-data",
        experiment_name=None,
        research_run_id="e2e-run",
        experiment_id="EXP-0001",
    ).exists()

    summary = read_json_object(experiment_dir / "summary.json")
    data_audit = read_json_object(experiment_dir / "data_audit.json")
    implementation = read_json_object(experiment_dir / "implementation.json")
    confirmatory = read_json_object(
        experiment_dir / "confirmatory_evaluation_result.json"
    )
    empirical_critique = read_json_object(experiment_dir / "empirical_critique.json")
    plan_update = read_json_object(experiment_dir / "plan_update.json")

    assert summary["outcome"] == "completed_candidate"
    assert data_audit["passed"] is True
    assert implementation["status"] == "completed"
    assert confirmatory["outcome"] == "completed_candidate"
    assert empirical_critique["recommended_outcome"] == "completed_candidate"
    assert plan_update["followups"][0]["title"] == "inspect candidate worktree"
    assert {config.role for config in runtime.configs} == {
        "research-strategist",
        "research-critic",
        "research-implementer",
        "research-evaluator",
    }


def test_program_root_flow_writes_lineage_and_state_fields(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    program_root = tmp_path / "programs" / "peer-residuals"
    spec_path = _write_spec(
        tmp_path,
        repo,
        data_root,
        program_root=program_root,
    )
    runtime = FakeResearchRuntime()
    target_head_before = _git_head(repo)

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=program_root,
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    worktree = program_root / "worktrees" / "e2e-run" / "EXP-0001"
    state = read_json_object(run.state_path)
    lineage = read_json_object(experiment_dir / "lineage.json")

    assert run.run_directory == (program_root / "runs" / "e2e-run").resolve()
    assert worktree.is_dir()
    assert (experiment_dir / "continuation_summary.json").exists()
    assert lineage["worktree_path"] == str(worktree)
    assert lineage["worktree_branch"] == "research/e2e-run/EXP-0001"
    assert lineage["target_repo_head_at_start"] == target_head_before
    assert lineage["worktree_head_after_implementation"] == target_head_before
    assert lineage["changed_files"] == ["research/candidate.py"]
    assert lineage["reusable_for_followups"] is True
    assert state["experiments"]["EXP-0001"]["lineage_path"] == str(
        experiment_dir / "lineage.json"
    )
    assert state["experiments"]["EXP-0001"]["worktree_path"] == str(worktree)
    assert state["experiments"]["EXP-0001"]["changed_files"] == [
        "research/candidate.py"
    ]
    assert state["threads"]["strategist"] == "research-strategist-thread-1"


def test_strategist_closeout_cannot_upgrade_confirmatory_outcome(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime(
        confirmatory_outcome="completed_rejected",
        closeout_outcome="completed_candidate",
    )

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    state = read_json_object(run.state_path)
    summary = read_json_object(experiment_dir / "summary.json")
    confirmatory = read_json_object(
        experiment_dir / "confirmatory_evaluation_result.json"
    )

    assert confirmatory["outcome"] == "completed_rejected"
    assert summary["outcome"] == "completed_rejected"
    assert state["experiments"]["EXP-0001"]["outcome"] == "completed_rejected"
    assert (experiment_dir / "plan_update.json").exists()


def test_agent_driven_controller_does_not_scan_prior_experiments_for_material_revision(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root, max_experiments=2)
    run = start_research_run(spec_path)
    previous_experiment = run.experiments_directory / "EXP-0001"
    previous_experiment.mkdir(parents=True)
    write_json(previous_experiment / "research_spec.json", _research_spec_payload())
    write_json(
        previous_experiment / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Prior candidate.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Prior candidate.",
        },
    )
    state = read_json_object(run.state_path)
    state["experiments"]["EXP-0001"] = {
        "id": "EXP-0001",
        "status": "terminal",
        "experiment_directory": str(previous_experiment),
        "outcome": "completed_candidate",
        "outcome_reason": "Prior candidate.",
        "failed_stage": None,
        "failure_classification": None,
    }
    state["experiment_count"] = 1
    write_json(run.state_path, state)
    runtime = FakeResearchRuntime(primary_metric="rank_information_coefficient")

    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0002"
    summary = read_json_object(experiment_dir / "summary.json")

    assert summary["outcome"] == "completed_candidate"
    assert (experiment_dir / "critique.json").exists()
    assert not (experiment_dir / "material_revision_critique.json").exists()


def test_repair_changes_are_audited_before_evaluation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime(repair_outside_allowed_paths=True)

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    diff_summary = read_json_object(experiment_dir / "implementation_diff_summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "implementation_boundary_audit"
    assert summary["failure_classification"] == "allowed_path_violation"
    assert diff_summary["allowed_path_violations"] == ["outside.py"]
    assert not (experiment_dir / "confirmatory_evaluation_result.json").exists()


def test_repair_boundary_failure_precedes_verification_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime(
        repair_outside_allowed_paths=True,
        repair_keeps_verification_failing=True,
    )

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    diff_summary = read_json_object(experiment_dir / "implementation_diff_summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "implementation_boundary_audit"
    assert summary["failure_classification"] == "allowed_path_violation"
    assert diff_summary["allowed_path_violations"] == ["outside.py"]
    assert not (experiment_dir / "confirmatory_evaluation_result.json").exists()


def test_invalid_allowed_write_paths_are_boundary_failures(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime(allowed_write_paths=["/absolute/path"])

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")
    diff_summary = read_json_object(experiment_dir / "implementation_diff_summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "implementation_boundary_audit"
    assert summary["failure_classification"] == "allowed_path_violation"
    assert diff_summary["allowed_path_violations"] == ["research/candidate.py"]


def test_run_failed_evaluation_is_terminal_before_empirical_closeout(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = _write_spec(tmp_path, repo, data_root)
    runtime = FakeResearchRuntime(confirmatory_outcome="run_failed")

    run = start_research_run(spec_path)
    run_research_loop(
        run.research_run_id,
        research_program_root=run.run_directory.parents[1],
        agent_runtime=runtime,
    )

    experiment_dir = run.experiments_directory / "EXP-0001"
    summary = read_json_object(experiment_dir / "summary.json")

    assert summary["outcome"] == "run_failed"
    assert summary["failed_stage"] == "evaluation"
    assert summary["failure_classification"] == "evaluation_runtime_defect"
    assert not (experiment_dir / "empirical_critique.json").exists()
    assert not (experiment_dir / "plan_update.json").exists()


class FakeTurnResult:
    def __init__(self, final_response: dict[str, Any]) -> None:
        self.final_response = final_response


class FakeResearchThread:
    def __init__(self, thread_id: str, role: str, runtime: FakeResearchRuntime) -> None:
        self.id = thread_id
        self.role = role
        self.runtime = runtime
        self.inputs: list[str] = []

    def run(self, input: str, config: Any) -> FakeTurnResult:
        self.inputs.append(input)
        if config.role == "research-strategist":
            return FakeTurnResult(
                _strategist_response(
                    input,
                    closeout_outcome=self.runtime.closeout_outcome,
                    primary_metric=self.runtime.primary_metric,
                    material_revision_categories=(
                        self.runtime.material_revision_categories
                    ),
                    repair_during_verification=self.runtime.repair_outside_allowed_paths,
                    allowed_write_paths=self.runtime.allowed_write_paths,
                    write_signal_panel=self.runtime.write_signal_panel,
                )
            )
        if config.role == "research-critic":
            return FakeTurnResult(
                _critic_response(
                    input,
                    recommended_outcome=self.runtime.confirmatory_outcome,
                )
            )
        if config.role == "research-implementer":
            if "Verification failed" in input:
                marker = Path(config.cwd) / "research" / "pass.txt"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("pass\n", encoding="utf-8")
                if self.runtime.repair_outside_allowed_paths:
                    (Path(config.cwd) / "outside.py").write_text(
                        "VALUE = 1\n",
                        encoding="utf-8",
                    )
                if self.runtime.repair_keeps_verification_failing:
                    marker.unlink(missing_ok=True)
            else:
                candidate = Path(config.cwd) / "research" / "candidate.py"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("VALUE = 1\n", encoding="utf-8")
            return FakeTurnResult(
                {
                    "status": "completed",
                    "summary": "Implemented candidate.",
                    "changed_files": ["research/candidate.py"],
                    "commands_declared": [],
                    "risks": [],
                }
            )
        if config.role == "research-evaluator":
            failed_stage = (
                "evaluation"
                if self.runtime.confirmatory_outcome == "run_failed"
                else None
            )
            failure_classification = (
                "evaluation_runtime_defect"
                if self.runtime.confirmatory_outcome == "run_failed"
                else None
            )
            write_evaluation_result_files(
                Path(config.cwd),
                outcome=self.runtime.confirmatory_outcome,
                failed_stage=failed_stage,
                failure_classification=failure_classification,
                ic=0.05,
                evidence="IC above gate",
                exploratory_result={
                    "findings": ["turnover stable"],
                    "metrics": {"turnover": 0.2},
                    "plots": [],
                    "future_experiment_ideas": ["lock turnover gate"],
                },
            )
            return FakeTurnResult({"ignored": True})
        raise AssertionError(f"unexpected role: {config.role}")


class FakeResearchRuntime:
    def __init__(
        self,
        *,
        confirmatory_outcome: str = "completed_candidate",
        closeout_outcome: str = "completed_candidate",
        primary_metric: str = "information_coefficient",
        material_revision_categories: list[str] | None = None,
        repair_outside_allowed_paths: bool = False,
        repair_keeps_verification_failing: bool = False,
        allowed_write_paths: list[str] | None = None,
        write_signal_panel: bool = True,
    ) -> None:
        self.configs: list[Any] = []
        self.threads: dict[str, FakeResearchThread] = {}
        self.role_counts: dict[str, int] = {}
        self.confirmatory_outcome = confirmatory_outcome
        self.closeout_outcome = closeout_outcome
        self.primary_metric = primary_metric
        self.material_revision_categories = material_revision_categories or []
        self.repair_outside_allowed_paths = repair_outside_allowed_paths
        self.repair_keeps_verification_failing = repair_keeps_verification_failing
        self.allowed_write_paths = allowed_write_paths or ["research"]
        self.write_signal_panel = write_signal_panel

    def open_thread(self, config: Any) -> FakeResearchThread:
        self.configs.append(config)
        if config.thread_id:
            thread_id = config.thread_id
        else:
            count = self.role_counts.get(config.role, 0) + 1
            self.role_counts[config.role] = count
            thread_id = f"{config.role}-thread-{count}"
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = FakeResearchThread(thread_id, config.role, self)
            self.threads[thread_id] = thread
        return thread


def _strategist_response(
    input: str,
    *,
    closeout_outcome: str,
    primary_metric: str,
    material_revision_categories: list[str],
    repair_during_verification: bool,
    allowed_write_paths: list[str],
    write_signal_panel: bool,
) -> dict[str, Any]:
    if "proposal.json" in input:
        return {
            "hypothesis": "Peer residuals predict forward returns.",
            "rationale": "Prior context supports testing residual signal.",
            "signal_family": "peer_residual",
            "expected_mechanism": "Crowding mean reverts.",
            "known_risks": ["thin history"],
            "falsification_evidence": ["IC below zero"],
        }
    if "research_spec.json" in input:
        return _research_spec_payload(primary_metric=primary_metric)
    if "experiment_design.json" in input:
        return {
            "prerequisite_commands": [],
            "data_audit_commands": [
                {"name": "data-ok", "argv": [sys.executable, "-c", "pass"]}
            ],
            "verification_commands": [
                _verification_command(
                    repair_during_verification,
                    write_signal_panel=write_signal_panel,
                )
            ],
            "confirmatory_commands": [
                {"name": "eval", "argv": [sys.executable, "-c", "pass"]}
            ],
            "exploratory_commands": [],
            "expected_outputs": [
                "$RESEARCH_EXPERIMENT_DATA_ROOT/signal_panel.parquet",
                "evaluation/eval_outputs/metrics.json",
            ],
            "allowed_write_paths": allowed_write_paths,
            "timeout_seconds": 30,
            "resource_budgets": {},
            "failure_routing": {},
        }
    if "selected_plan.json" in input:
        return {
            "selected": True,
            "plan_id": "candidate-1",
            "rationale": "Admissible bounded experiment.",
            "fresh_selection_reason": "Fresh selected plan.",
            "material_revision_categories": material_revision_categories,
        }
    if "summary.json" in input:
        return {
            "outcome": closeout_outcome,
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate ready for inspection.",
            "confirmatory_findings": ["IC above gate"],
            "exploratory_findings": ["turnover stable"],
        }
    if "plan_update.json" in input:
        return {
            "followups": [
                {
                    "dedupe_key": "inspect-candidate-worktree",
                    "title": "inspect candidate worktree",
                    "kind": "direct_followup",
                    "evidence_basis": ["candidate worktree available"],
                    "mechanism": "Manual inspection may find reusable parts.",
                    "axis_to_vary": "implementation inspection",
                    "specific_change": "Inspect candidate worktree before followup.",
                    "falsifying_evidence": ["No reusable changes found."],
                    "priority": 0.7,
                    "priority_reason": "Builds on completed candidate.",
                    "seed_component_ids": [],
                }
            ],
            "learning_updates": [],
            "blockers": [],
            "reusable_components": [],
            "superseded_idea_ids": [],
        }
    raise AssertionError(f"unexpected strategist input: {input}")


def _verification_command(
    repair_during_verification: bool,
    *,
    write_signal_panel: bool,
) -> dict[str, object]:
    panel_writer = signal_panel_writer_command()
    if not repair_during_verification:
        return {
            "name": "unit",
            "argv": [
                sys.executable,
                "-c",
                panel_writer if write_signal_panel else "pass",
            ],
        }
    command = (
        "from pathlib import Path; "
        "ok = Path('research/pass.txt').exists(); "
        f"{panel_writer if write_signal_panel else ''}"
        "raise SystemExit(0 if ok else 1)"
    )
    return {
        "name": "unit",
        "argv": [
            sys.executable,
            "-c",
            command,
        ],
    }


def _critic_response(input: str, *, recommended_outcome: str) -> dict[str, Any]:
    if "empirical_critique.json" in input:
        return {
            "status_supported": True,
            "concerns": [],
            "overclaiming_risks": [],
            "recommended_outcome": recommended_outcome,
        }
    return {
        "decision": "approve",
        "fatal_issues": [],
        "required_revisions": [],
        "material_revision_categories": [],
        "leakage_risks": [],
        "baseline_concerns": [],
        "gate_concerns": [],
    }


def _research_spec_payload(
    *,
    primary_metric: str = "information_coefficient",
) -> dict[str, Any]:
    return {
        "hypothesis": "Peer residuals predict forward returns.",
        "target": "forward_return_1m",
        "prediction_horizon": "1M",
        "universe": "test_universe",
        "label": "forward_return_1m",
        "feature_availability_assumptions": ["features lagged one bar"],
        "split": {"train": "2026-01", "test": "2026-01"},
        "primary_metric": primary_metric,
        "secondary_metrics": ["turnover"],
        "baselines": ["zero_signal"],
        "null_tests": ["shuffle"],
        "transaction_cost_assumptions": "5 bps",
        "success_gates": {"information_coefficient": 0.03},
        "failure_gates": {"information_coefficient": 0.0},
        "inconclusive_gates": {"min_observations": 10},
    }


def _write_spec(
    tmp_path: Path,
    repo: Path,
    data_root: Path,
    *,
    max_experiments: int = 1,
    program_root: Path | None = None,
) -> Path:
    path = tmp_path / "research.yaml"
    resolved_program_root = program_root or tmp_path / "programs" / "e2e-run"
    path.write_text(
        f"""
research_run_id: e2e-run
target_repository: {repo}
research_program_root: {resolved_program_root}
max_experiments: {max_experiments}
research_brief: |
  Test full fake-runtime flow.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {data_root}
experiment_data_root: {tmp_path / "experiment-data"}
worktree:
  create: true
implementation:
  max_repairs: 1
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return path


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"],
        cwd=repo,
        check=True,
    )
    (repo / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
