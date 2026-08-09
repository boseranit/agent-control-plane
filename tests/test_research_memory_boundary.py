from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_control_plane.control_plane.agent_runtime import AgentMemoryLimitExceeded
from agent_control_plane.control_plane.command_runner import CommandResult
from agent_control_plane.control_plane.json_artifacts import read_json_object
from agent_control_plane.control_plane.systemd_scope import ResourceLimitExceeded
from agent_control_plane.research_experiment_controller import experiment_flow
from agent_control_plane.research_experiment_controller import prerequisites
from agent_control_plane.research_experiment_controller import verification
from agent_control_plane.research_experiment_controller.agents import (
    ResearchAgentRole,
)
from agent_control_plane.research_experiment_controller.artifacts import (
    ExperimentDesign,
)
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
)


def _memory_failure(tmp_path: Path, *, name: str) -> CommandResult:
    return CommandResult(
        name=name,
        argv=["memory-hog"],
        cwd=str(tmp_path),
        status="memory_limit_exceeded",
        exit_code=137,
        duration_seconds=0.1,
        timeout_seconds=60,
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
        maximum_memory_bytes=123456,
        memory_limit_exceeded=True,
    )


def test_verification_memory_kill_is_not_sent_to_implementation_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repairs: list[object] = []
    monkeypatch.setattr(
        verification,
        "run_command",
        lambda *args, **kwargs: _memory_failure(tmp_path, name="verification"),
    )

    with pytest.raises(ResourceLimitExceeded, match="Verification command"):
        verification.run_verification_commands(
            verification_commands=[{"name": "verification", "argv": ["test"]}],
            cwd=tmp_path,
            run_dir=tmp_path / "run",
            timeout_seconds=60,
            max_repairs=3,
            maximum_memory_bytes=123456,
            repair_callback=repairs.append,
        )

    metrics = read_json_object(tmp_path / "run" / "command_metrics.json")
    assert repairs == []
    assert metrics["command_count"] == 1
    assert metrics["commands"][0]["memory_limit_exceeded"] is True


def test_data_audit_memory_kill_is_a_systemic_resource_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo.mkdir()
    data_root.mkdir()
    monkeypatch.setattr(
        prerequisites,
        "run_command",
        lambda *args, **kwargs: _memory_failure(tmp_path, name="audit"),
    )

    with pytest.raises(ResourceLimitExceeded, match="Data-audit command"):
        prerequisites.run_data_audit_phase(
            PrerequisiteAuditRequest(
                data_root=data_root,
                experiment_data_root=tmp_path / "experiment-data",
                prerequisite_commands=[],
                data_audit_commands=[{"name": "audit", "argv": ["audit"]}],
                cwd=repo,
                run_dir=tmp_path / "run",
                timeout_seconds=60,
                maximum_memory_bytes=123456,
            )
        )

    metrics = read_json_object(tmp_path / "run" / "command_metrics.json")
    assert metrics["command_count"] == 1
    assert metrics["commands"][0]["memory_limit_exceeded"] is True


def test_agent_memory_kill_never_enters_usage_limit_retry() -> None:
    calls = 0

    def memory_kill() -> None:
        nonlocal calls
        calls += 1
        raise AgentMemoryLimitExceeded("limit exceeded; retry after 1 second")

    with pytest.raises(AgentMemoryLimitExceeded):
        experiment_flow._run_agent_turn_with_usage_limit(
            role=ResearchAgentRole.EVALUATOR,
            run=memory_kill,
        )

    assert calls == 1


def test_evaluator_memory_kill_remains_a_systemic_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MemoryLimitedThread:
        id = "evaluator-thread"

        def run(self, input: str, config: object) -> None:
            raise AgentMemoryLimitExceeded("evaluator process tree exceeded limit")

    class MemoryLimitedRuntime:
        def open_thread(self, config: object) -> MemoryLimitedThread:
            return MemoryLimitedThread()

    workspace = SimpleNamespace(
        path=tmp_path / "evaluation",
        manifest_path=tmp_path / "evaluation" / "manifest.json",
        boundary_evidence=SimpleNamespace(),
    )
    request = SimpleNamespace(
        state={},
        spec=SimpleNamespace(
            target_repository=tmp_path,
            data_root=tmp_path / "data",
            codex=SimpleNamespace(model=None, effort=None),
        ),
        experiment_data_directory=tmp_path / "experiment-data",
        experiment_directory=tmp_path / "experiment",
        ledger_path=tmp_path / "ledger.jsonl",
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )
    monkeypatch.setattr(
        experiment_flow,
        "create_evaluator_workspace",
        lambda **kwargs: workspace,
    )
    monkeypatch.setattr(
        experiment_flow,
        "git_snapshot",
        lambda path: SimpleNamespace(head="abc123"),
    )
    monkeypatch.setattr(experiment_flow, "_canonical_artifacts", lambda path: {})
    monkeypatch.setattr(experiment_flow, "_locked_artifacts", lambda request: [])
    monkeypatch.setattr(experiment_flow, "_persist_thread_state", lambda request: None)
    monkeypatch.setattr(experiment_flow, "append_ledger_event", lambda *a, **k: None)
    monkeypatch.setattr(experiment_flow, "_evaluation_input", lambda *a, **k: "run")

    with pytest.raises(AgentMemoryLimitExceeded, match="evaluator process tree"):
        experiment_flow._run_evaluation_if_needed(
            request=request,
            experiment_design=ExperimentDesign(
                confirmatory_commands=[{"name": "eval", "argv": ["eval"]}]
            ),
            worktree=None,
            agent_runtime=MemoryLimitedRuntime(),
        )
