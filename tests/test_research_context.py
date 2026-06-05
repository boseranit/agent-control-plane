from __future__ import annotations

import subprocess
from pathlib import Path

from agent_control_plane.control_plane.json_artifacts import (
    file_sha256,
    read_json_object,
    write_json,
)
from agent_control_plane.research_experiment_controller.context import (
    write_context_outputs,
)
from agent_control_plane.research_experiment_controller.controller import (
    start_research_run,
)
from agent_control_plane.research_experiment_controller.ledger import (
    append_ledger_event,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def commit_file(repo: Path, relative_path: str, text: str) -> str:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {relative_path}"], cwd=repo, check=True
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def write_research_run_spec(tmp_path: Path, repo: Path, data_root: Path) -> Path:
    path = tmp_path / "research-run.yaml"
    experiment_data_root = tmp_path / "experiment-data"
    path.write_text(
        f"""
research_run_id: peer-residual-v1
target_repository: {repo}
max_experiments: 5
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-02"
    max_runtime_minutes: 7
data_root: {data_root}
experiment_data_root: {experiment_data_root}
research_program_root: {tmp_path / "programs" / "peer-residual-v1"}
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return path


def write_program_research_run_spec(
    tmp_path: Path,
    repo: Path,
    data_root: Path,
    program_root: Path,
) -> Path:
    path = tmp_path / "program-research-run.yaml"
    experiment_data_root = tmp_path / "experiment-data"
    path.write_text(
        f"""
research_run_id: current-run
target_repository: {repo}
research_program_root: {program_root}
max_experiments: 5
max_prior_experiments: 12
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-02"
    max_runtime_minutes: 7
data_root: {data_root}
experiment_data_root: {experiment_data_root}
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return path


def write_run_context(run):
    return write_context_outputs(
        run.paths,
        run.research_run_id,
    )


def write_research_state(program_root: Path, payload: dict) -> None:
    write_json(
        program_root / "memory" / "research_state.json",
        {
            "artifact_kind": "research_state",
            "schema_version": 1,
            "ideas": {},
            "experiments": {},
            "learning_updates": {},
            "known_blockers": {},
            "reusable_components": {},
            "metric_observations": [],
        }
        | payload,
    )


def test_context_outputs_include_spec_budget_and_git_facts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    git_head = commit_file(repo, "README.md", "tracked\n")
    (repo / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    data_root = tmp_path / "data"
    spec_path = write_research_run_spec(tmp_path, repo, data_root)
    run = start_research_run(spec_path)

    output = write_run_context(run)

    summary = read_json_object(output.context_summary_path)
    assert output.context_pack_path == run.run_directory / "context_pack.md"
    assert "continuation_summary" not in summary
    assert summary["spec"]["research_run_id"] == "peer-residual-v1"
    assert summary["spec"]["max_experiments"] == 5
    assert summary["spec"]["stop_on_prerequisites_failed"] is True
    assert summary["spec"]["research_brief"] == "Test peer residual forecasting.\n"
    assert summary["budget"] == {
        "name": "smoke",
        "month_start": "2026-01",
        "month_end": "2026-02",
        "max_runtime_minutes": 7,
        "default_command_timeout_seconds": 420,
    }
    assert summary["data_root"] == str(data_root)
    assert summary["experiment_data_root"] == str(tmp_path / "experiment-data")
    assert "experiment data root:" in output.context_pack_text
    assert summary["git"]["repo_root"] == str(repo.resolve())
    assert summary["git"]["head"] == git_head
    assert summary["git"]["status_text"] == "?? scratch.txt\n"
    assert summary["git"]["changed_files"] == ["scratch.txt"]
    assert "Test peer residual forecasting." in output.context_pack_text
    assert "default timeout seconds: 420" in output.context_pack_text
    assert "scratch.txt" in output.context_pack_text


def test_context_outputs_include_program_continuation_summary(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    data_root = tmp_path / "data"
    program_root = tmp_path / "programs" / "peer-residuals"
    spec_path = write_program_research_run_spec(
        tmp_path,
        repo,
        data_root,
        program_root,
    )
    run = start_research_run(spec_path)
    (program_root / "program.md").write_text(
        "Peer residual program agenda.\n",
        encoding="utf-8",
    )
    (program_root / "notes").mkdir()
    (program_root / "notes" / "data-contract.md").write_text(
        "Use point-in-time bars.\n",
        encoding="utf-8",
    )
    prior_run = program_root / "runs" / "prior-run"
    prior_dir = prior_run / "experiments" / "EXP-0003"
    write_json(prior_run / "state.json", {"experiments": {}})
    write_json(
        prior_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate.",
        },
    )
    write_json(
        prior_dir / "research_spec.json",
        {
            "hypothesis": "Peer residuals forecast returns.",
            "primary_metric": "ic",
            "prediction_horizon": "1h",
            "label": "forward_return_1h",
        },
    )
    write_json(
        prior_dir / "confirmatory_evaluation_result.json",
        {
            "metrics": {"ic": 0.04},
            "gate_results": {"ic": "passed"},
        },
    )
    write_json(
        prior_dir / "exploratory_diagnostics_result.json",
        {
            "future_experiment_ideas": ["try 2h horizon"],
        },
    )
    write_json(
        prior_dir / "implementation.json",
        {
            "status": "completed",
            "summary": "Built peer residual feature.",
            "changed_files": ["research/ignored_implementation.py"],
        },
    )
    write_json(
        prior_dir / "implementation_diff_summary.json",
        {"changed_files": ["research/ignored_diff.py"]},
    )
    write_json(
        prior_dir / "lineage.json",
        {
            "research_run_id": "prior-run",
            "experiment_id": "EXP-0003",
            "experiment_dir": str(prior_dir),
            "worktree_path": str(program_root / "worktrees" / "prior-run" / "EXP-0003"),
            "worktree_branch": "research/prior-run/EXP-0003",
            "changed_files": ["research/peer_residual.py"],
            "implementation_summary": "Built peer residual feature.",
            "reusable_for_followups": True,
        },
    )
    prior_worktree = program_root / "worktrees" / "prior-run" / "EXP-0003"
    write_research_state(
        program_root,
        {
            "ideas": {
                "IDEA-0001": {
                    "dedupe_key": "add-turnover-gate",
                    "title": "add turnover gate",
                    "kind": "direct_followup",
                    "evidence_basis": ["prior-run/EXP-0003"],
                    "mechanism": "Turnover gate may reduce costs.",
                    "axis_to_vary": "turnover gate",
                    "specific_change": "Add turnover gate to success criteria.",
                    "falsifying_evidence": ["IC/cost gate fails after turnover gate."],
                    "priority": 0.9,
                    "priority_reason": "Directly follows passed candidate.",
                    "seed_component_ids": ["peer-residual-feature"],
                    "source_experiments": ["prior-run/EXP-0003"],
                    "status": "pending",
                }
            },
            "experiments": {
                "prior-run/EXP-0003": {
                    "experiment_dir": str(prior_dir),
                    "outcome": "completed_candidate",
                    "outcome_reason": "Locked gates passed.",
                    "failed_stage": None,
                    "failure_classification": None,
                    "hypothesis": "Peer residuals forecast returns.",
                    "primary_metric": "ic",
                    "prediction_horizon": "1h",
                    "label": "forward_return_1h",
                    "selected_plan_rationale": None,
                    "selected_idea_ids": [],
                    "fresh_selection_reason": None,
                    "seed_component_ids": [],
                    "worktree_path": str(prior_worktree),
                    "worktree_branch": "research/prior-run/EXP-0003",
                    "changed_files": ["research/peer_residual.py"],
                    "implementation_summary": "Built peer residual feature.",
                    "lineage_path": str(prior_dir / "lineage.json"),
                }
            },
            "known_blockers": {
                "illiquid-universe": {
                    "blocker_type": "data_quality",
                    "description": "illiquid universe",
                    "resolution_condition": "Add liquidity filter.",
                    "affected_idea_ids": [],
                    "source_experiments": ["prior-run/EXP-0003"],
                }
            },
            "reusable_components": {
                "peer-residual-feature": {
                    "worktree_path": str(prior_worktree),
                    "changed_files": ["research/peer_residual.py"],
                    "summary": "Built peer residual feature.",
                    "reusable_for": ["turnover gate followup"],
                    "risk_notes": [],
                    "source_experiments": ["prior-run/EXP-0003"],
                }
            },
            "metric_observations": [
                {
                    "source_experiment": "prior-run/EXP-0003",
                    "metric_path": "ic",
                    "value": 0.04,
                }
            ],
        },
    )

    output = write_run_context(run)

    assert "continuation_summary" not in output.context_summary
    continuation = output.continuation_summary
    assert continuation is not None
    assert output.continuation_summary_path == (
        run.run_directory / "continuation_summary.json"
    )
    assert (program_root / "memory" / "continuation_summary.json").exists()
    assert continuation["program_root"] == str(program_root.resolve())
    assert continuation["human_context"] == {
        "program_md": "Peer residual program agenda.\n",
        "notes": [
            {"path": "notes/data-contract.md", "text": "Use point-in-time bars.\n"}
        ],
    }
    assert all(
        record["path"] != "memory/research_state.json"
        for record in continuation["memory_context"]
    )
    prior_experiment = continuation["prior_experiments"][0]
    assert prior_experiment["worktree"] == {
        "path": str(prior_worktree),
        "source": "lineage",
    }
    assert continuation["pending_followups"][0]["idea_id"] == "IDEA-0001"
    assert continuation["pending_followups"][0]["title"] == "add turnover gate"
    assert continuation["pending_followups"][0]["priority"] == 0.9
    assert continuation["pending_followups"][0]["suggested_seed_worktree"] == str(
        prior_worktree
    )
    assert continuation["future_experiment_ideas"][0]["title"] == "add turnover gate"
    assert continuation["reusable_implementations"][0]["changed_files"] == [
        "research/peer_residual.py"
    ]
    assert continuation["do_not_repeat"][0]["reason"] == "illiquid universe"
    assert continuation["metric_history"] == [
        {
            "source_experiment": "prior-run/EXP-0003",
            "metric_path": "ic",
            "value": 0.04,
        }
    ]
    assert continuation["best_metric_runs"] == [
        {
            "source_experiment": "prior-run/EXP-0003",
            "metric": "metrics.ic",
            "value": 0.04,
        }
    ]
    assert "## Research Program Continuation" in output.context_pack_text
    assert "add turnover gate" in output.context_pack_text


def test_continuation_summary_does_not_treat_seed_worktree_as_own_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    program_root = tmp_path / "programs" / "peer-residuals"
    run = start_research_run(
        write_program_research_run_spec(
            tmp_path,
            repo,
            tmp_path / "data",
            program_root,
        )
    )
    prior_run = program_root / "runs" / "seeded-run"
    prior_dir = prior_run / "experiments" / "EXP-0007"
    write_json(prior_run / "state.json", {"experiments": {}})
    write_json(
        prior_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Built variation.",
            "failed_stage": None,
            "failure_classification": None,
        },
    )
    write_json(
        prior_dir / "implementation_diff_summary.json",
        {"changed_files": ["research/variation.py"]},
    )
    write_research_state(
        program_root,
        {
            "ideas": {
                "IDEA-0001": {
                    "dedupe_key": "vary-horizon",
                    "title": "vary horizon",
                    "kind": "controlled_variation",
                    "evidence_basis": ["seeded-run/EXP-0007"],
                    "mechanism": "Horizon may change residual decay.",
                    "axis_to_vary": "prediction horizon",
                    "specific_change": "Evaluate a different horizon.",
                    "falsifying_evidence": ["No metric improvement."],
                    "priority": 0.6,
                    "priority_reason": "Cheap controlled variation.",
                    "seed_component_ids": [],
                    "source_experiments": ["seeded-run/EXP-0007"],
                    "status": "pending",
                }
            },
            "experiments": {
                "seeded-run/EXP-0007": {
                    "experiment_dir": str(prior_dir),
                    "outcome": "completed_candidate",
                    "outcome_reason": "Built variation.",
                    "failed_stage": None,
                    "failure_classification": None,
                    "hypothesis": None,
                    "primary_metric": None,
                    "prediction_horizon": None,
                    "label": None,
                    "selected_plan_rationale": "Adapt older implementation.",
                    "selected_idea_ids": [],
                    "fresh_selection_reason": None,
                    "seed_component_ids": [],
                    "worktree_path": None,
                    "worktree_branch": None,
                    "changed_files": [],
                    "implementation_summary": None,
                    "lineage_path": None,
                }
            },
        },
    )

    output = write_run_context(run)

    experiment = output.continuation_summary["prior_experiments"][0]
    assert experiment["worktree"] is None
    assert experiment["changed_files"] == []
    assert experiment["reusable"] is False
    assert (
        output.continuation_summary["pending_followups"][0]["title"] == "vary horizon"
    )
    assert (
        output.continuation_summary["pending_followups"][0]["suggested_seed_worktree"]
        is None
    )
    assert output.continuation_summary["reusable_implementations"] == []


def test_continuation_summary_does_not_fallback_from_missing_lineage(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    program_root = tmp_path / "programs" / "peer-residuals"
    run = start_research_run(
        write_program_research_run_spec(
            tmp_path,
            repo,
            tmp_path / "data",
            program_root,
        )
    )
    prior_run = program_root / "runs" / "state-run"
    prior_dir = prior_run / "experiments" / "EXP-0004"
    worktree = program_root / "worktrees" / "state-run" / "EXP-0004"
    write_json(
        prior_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "State records ignored worktree.",
            "failed_stage": None,
            "failure_classification": None,
        },
    )
    write_json(
        prior_run / "state.json",
        {
            "experiments": {
                "EXP-0004": {
                    "worktree_path": str(worktree),
                    "changed_files": ["research/state_source.py"],
                }
            }
        },
    )
    write_json(
        prior_dir / "implementation_diff_summary.json",
        {"changed_files": ["research/diff_source.py"]},
    )
    write_json(
        prior_dir / "implementation.json",
        {
            "status": "completed",
            "summary": "Implementation records ignored changed files.",
            "changed_files": ["research/implementation_source.py"],
        },
    )

    output = write_run_context(run)

    assert output.continuation_summary["prior_experiments"] == []


def test_context_outputs_are_byte_identical_across_repeated_writes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    spec_path = write_research_run_spec(tmp_path, repo, tmp_path / "data")
    run = start_research_run(spec_path)

    first = write_run_context(run)
    first_markdown = first.context_pack_path.read_bytes()
    first_json = first.context_summary_path.read_bytes()

    second = write_run_context(run)

    assert second.context_pack_path.read_bytes() == first_markdown
    assert second.context_summary_path.read_bytes() == first_json


def test_prior_synthesis_separates_outcomes_and_completed_prerequisites(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    run = start_research_run(write_research_run_spec(tmp_path, repo, tmp_path / "data"))
    experiments_dir = run.run_directory / "experiments"
    write_json(
        experiments_dir / "EXP-0001" / "summary.json",
        {
            "outcome": "blocked",
            "outcome_reason": "Waiting on vendor approval.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Blocked.",
        },
    )
    write_json(
        experiments_dir / "EXP-0002" / "summary.json",
        {
            "outcome": "prerequisites_failed",
            "outcome_reason": "Feature family missing.",
            "failed_stage": "data_audit",
            "failure_classification": "feature_family_missing",
            "summary": "Prerequisite failed.",
        },
    )
    write_json(
        experiments_dir / "EXP-0002" / "data_audit.json",
        {
            "passed": False,
            "outcome_reason": "Feature family missing.",
            "failed_stage": "data_audit",
            "failure_classification": "feature_family_missing",
        },
    )
    write_json(
        experiments_dir / "EXP-0003" / "summary.json",
        {
            "outcome": "completed_candidate",
            "outcome_reason": "Locked gates passed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Candidate.",
        },
    )
    write_json(
        experiments_dir / "EXP-0003" / "data_audit.json",
        {
            "passed": True,
            "outcome_reason": "Bars and features available.",
            "failed_stage": None,
            "failure_classification": None,
        },
    )
    write_json(
        experiments_dir / "EXP-0004" / "summary.json",
        {
            "outcome": "invalid",
            "outcome_reason": "Gate was revised after results.",
            "failed_stage": "critic",
            "failure_classification": "post_hoc_gate",
            "summary": "Invalid.",
        },
    )
    state = read_json_object(run.state_path)
    state["experiments"] = {
        "EXP-0004": {"experiment_directory": str(experiments_dir / "EXP-0004")},
        "EXP-0002": {"experiment_directory": str(experiments_dir / "EXP-0002")},
        "EXP-0001": {"experiment_directory": str(experiments_dir / "EXP-0001")},
        "EXP-0003": {"experiment_directory": str(experiments_dir / "EXP-0003")},
    }
    write_json(run.state_path, state)
    append_ledger_event(
        run.ledger_path,
        event_type="prerequisite_completed",
        research_run_id="peer-residual-v1",
        experiment_id="EXP-0003",
        prerequisite="raw bars backfilled",
    )
    append_ledger_event(
        run.ledger_path,
        event_type="prerequisite_command_failed",
        research_run_id="peer-residual-v1",
        experiment_id="EXP-0002",
        prerequisite="failed feature build",
        status="failed",
    )
    append_ledger_event(
        run.ledger_path,
        event_type="prerequisite_completed",
        research_run_id="peer-residual-v1",
        experiment_id="EXP-0002",
        prerequisite="explicit false prerequisite",
        passed=False,
    )

    output = write_run_context(run)

    prior = output.context_summary["prior_synthesis"]
    assert prior["blockers"] == [
        {
            "experiment_id": "EXP-0001",
            "outcome": "blocked",
            "reason": "Waiting on vendor approval.",
            "failed_stage": None,
            "failure_classification": None,
        },
        {
            "experiment_id": "EXP-0002",
            "outcome": "prerequisites_failed",
            "reason": "Feature family missing.",
            "failed_stage": "data_audit",
            "failure_classification": "feature_family_missing",
        },
    ]
    assert prior["failures"] == [
        {
            "experiment_id": "EXP-0002",
            "outcome": "prerequisites_failed",
            "reason": "Feature family missing.",
            "failed_stage": "data_audit",
            "failure_classification": "feature_family_missing",
        },
        {
            "experiment_id": "EXP-0004",
            "outcome": "invalid",
            "reason": "Gate was revised after results.",
            "failed_stage": "critic",
            "failure_classification": "post_hoc_gate",
        },
    ]
    assert prior["completed_outcomes"] == [
        {
            "experiment_id": "EXP-0003",
            "outcome": "completed_candidate",
            "reason": "Locked gates passed.",
        }
    ]
    assert prior["completed_prerequisites"] == [
        {
            "experiment_id": "EXP-0003",
            "source": "data_audit.json",
            "reason": "Bars and features available.",
        },
        {
            "experiment_id": "EXP-0003",
            "source": "ledger",
            "reason": "raw bars backfilled",
        },
    ]


def test_prior_synthesis_counts_repeated_blockers_deterministically(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    run = start_research_run(write_research_run_spec(tmp_path, repo, tmp_path / "data"))
    experiments_dir = run.run_directory / "experiments"
    for experiment_id, reason, classification in [
        ("EXP-0002", "Feature family missing in smoke window.", "feature_missing"),
        ("EXP-0001", "Feature family missing in research window.", "feature_missing"),
        ("EXP-0004", "Waiting on data vendor.", None),
        ("EXP-0003", "Waiting on data vendor.", None),
    ]:
        write_json(
            experiments_dir / experiment_id / "summary.json",
            {
                "outcome": "blocked",
                "outcome_reason": reason,
                "failed_stage": None,
                "failure_classification": classification,
                "summary": "Blocked.",
            },
        )

    output = write_run_context(run)

    assert output.context_summary["prior_synthesis"]["repeated_blockers"] == [
        {
            "kind": "failure_classification",
            "value": "feature_missing",
            "count": 2,
            "experiment_ids": ["EXP-0001", "EXP-0002"],
        },
        {
            "kind": "reason",
            "value": "Waiting on data vendor.",
            "count": 2,
            "experiment_ids": ["EXP-0003", "EXP-0004"],
        },
    ]


def test_context_inventory_ledger_and_metric_history_are_stable(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    run = start_research_run(write_research_run_spec(tmp_path, repo, tmp_path / "data"))
    (run.run_directory / "z-note.txt").write_text("z\n", encoding="utf-8")
    (run.run_directory / "a-note.txt").write_text("a\n", encoding="utf-8")
    (run.run_directory / "context_pack.md").write_text("old\n", encoding="utf-8")
    (run.run_directory / "context_summary.json").write_text("old\n", encoding="utf-8")
    experiment_dir = run.run_directory / "experiments" / "EXP-0001"
    write_json(experiment_dir / "metrics.json", {"ic": 0.04, "nested": {"sharpe": 1.5}})
    write_json(
        experiment_dir / "command_metrics.json",
        {"commands": [{"duration_seconds": 3.2, "exit_code": 0}], "timed_out": False},
    )
    write_json(
        experiment_dir / "confirmatory_evaluation_result.json",
        {
            "outcome": "completed_candidate",
            "metrics": {"turnover": 12, "drawdown": -0.2},
            "gate_results": {"passed": True},
        },
    )
    append_ledger_event(
        run.ledger_path,
        event_type="first_custom",
        research_run_id="peer-residual-v1",
    )
    append_ledger_event(
        run.ledger_path,
        event_type="second_custom",
        research_run_id="peer-residual-v1",
    )

    output = write_run_context(run)

    inventory = output.context_summary["artifact_inventory"]
    assert [item["path"] for item in inventory] == sorted(
        item["path"] for item in inventory
    )
    assert "context_pack.md" not in [item["path"] for item in inventory]
    assert "context_summary.json" not in [item["path"] for item in inventory]
    assert {
        "path": "a-note.txt",
        "sha256": file_sha256(run.run_directory / "a-note.txt"),
        "size": 2,
    } in inventory
    assert [event["event_type"] for event in output.context_summary["ledger_history"]][
        -2:
    ] == ["first_custom", "second_custom"]
    assert "a-note.txt" in output.context_pack_text
    assert "first_custom" in output.context_pack_text
    assert "commands[0].duration_seconds" in output.context_pack_text
    assert output.context_summary["prior_synthesis"]["metric_history"] == [
        {
            "experiment_id": "EXP-0001",
            "source": "command_metrics.json",
            "metric_path": "commands[0].duration_seconds",
            "value": 3.2,
        },
        {
            "experiment_id": "EXP-0001",
            "source": "command_metrics.json",
            "metric_path": "commands[0].exit_code",
            "value": 0,
        },
        {
            "experiment_id": "EXP-0001",
            "source": "confirmatory_evaluation_result.json",
            "metric_path": "metrics.drawdown",
            "value": -0.2,
        },
        {
            "experiment_id": "EXP-0001",
            "source": "confirmatory_evaluation_result.json",
            "metric_path": "metrics.turnover",
            "value": 12,
        },
        {
            "experiment_id": "EXP-0001",
            "source": "metrics.json",
            "metric_path": "ic",
            "value": 0.04,
        },
        {
            "experiment_id": "EXP-0001",
            "source": "metrics.json",
            "metric_path": "nested.sharpe",
            "value": 1.5,
        },
    ]


def test_prior_synthesis_excludes_active_experiment_until_terminal_summary_exists(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_file(repo, "README.md", "tracked\n")
    run = start_research_run(write_research_run_spec(tmp_path, repo, tmp_path / "data"))
    active_dir = run.run_directory / "experiments" / "EXP-0001"
    write_json(active_dir / "metrics.json", {"ic": 0.99})
    append_ledger_event(
        run.ledger_path,
        event_type="prerequisite_completed",
        research_run_id="peer-residual-v1",
        experiment_id="EXP-0001",
        prerequisite="active backfill",
    )
    state = read_json_object(run.state_path)
    state["active_experiment_id"] = "EXP-0001"
    write_json(run.state_path, state)

    active_output = write_run_context(run)

    assert active_output.context_summary["prior_synthesis"]["metric_history"] == []
    assert (
        active_output.context_summary["prior_synthesis"]["completed_prerequisites"]
        == []
    )

    write_json(
        active_dir / "summary.json",
        {
            "outcome": "completed_rejected",
            "outcome_reason": "Gate failed.",
            "failed_stage": None,
            "failure_classification": None,
            "summary": "Rejected.",
        },
    )

    terminal_output = write_run_context(run)

    assert terminal_output.context_summary["prior_synthesis"]["completed_outcomes"] == [
        {
            "experiment_id": "EXP-0001",
            "outcome": "completed_rejected",
            "reason": "Gate failed.",
        }
    ]
    assert terminal_output.context_summary["prior_synthesis"]["metric_history"] == [
        {
            "experiment_id": "EXP-0001",
            "source": "metrics.json",
            "metric_path": "ic",
            "value": 0.99,
        }
    ]
    assert terminal_output.context_summary["prior_synthesis"][
        "completed_prerequisites"
    ] == [
        {
            "experiment_id": "EXP-0001",
            "source": "ledger",
            "reason": "active backfill",
        }
    ]
