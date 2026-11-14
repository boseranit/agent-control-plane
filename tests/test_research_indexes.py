from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller.cli import main
from agent_control_plane.research_experiment_controller.indexes import (
    refresh_research_indexes,
)
from agent_control_plane.research_experiment_controller.paths import (
    ResearchProgramPaths,
)
from agent_control_plane.research_experiment_controller.research_state import (
    ExperimentRecord,
    empty_research_state,
    write_research_state,
)


def test_refresh_indexes_preserves_human_program_index_and_lists_evidence(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    program_root = archive / "programs" / "factor-residuals"
    paths = ResearchProgramPaths(program_root)
    paths.create_directories()
    human_index = program_root / "INDEX.md"
    human_index.write_text(
        "# Human synthesis\n\nDo not replace me.\n", encoding="utf-8"
    )

    run_id = "run-1"
    experiment_id = "EXP-0001"
    experiment_dir = paths.experiment_directory(run_id, experiment_id)
    experiment_dir.mkdir(parents=True)
    write_json(
        paths.state_path(run_id),
        {
            "research_run_id": run_id,
            "status": "completed",
            "current_phase": "completed",
            "experiment_count": 1,
            "experiments": {
                experiment_id: {"outcome": "completed_candidate"},
            },
        },
    )
    write_json(
        experiment_dir / "summary.json",
        {
            "outcome": "completed_candidate",
            "summary": "Candidate signal survived the locked evaluation.",
        },
    )
    paths.worktree_directory(run_id, experiment_id).mkdir(parents=True)

    memory = empty_research_state("factor-residuals")
    memory.experiment_index["removed-run/EXP-0002"] = ExperimentRecord(
        experiment_dir="/retired/EXP-0002",
        outcome="completed_rejected",
    )
    write_research_state(paths.memory / "research_state.json", memory)

    written = refresh_research_indexes(program_root)

    assert human_index.read_text(encoding="utf-8") == (
        "# Human synthesis\n\nDo not replace me.\n"
    )
    assert set(written) == {
        paths.runs / "INDEX.md",
        paths.run_directory(run_id) / "INDEX.md",
        archive / "INDEX.md",
    }
    runs_index = (paths.runs / "INDEX.md").read_text(encoding="utf-8")
    run_index = (paths.run_directory(run_id) / "INDEX.md").read_text(encoding="utf-8")
    archive_index = (archive / "INDEX.md").read_text(encoding="utf-8")
    assert "[run-1](run-1/INDEX.md)" in runs_index
    assert "removed-run" in runs_index
    assert "Run directory not retained" in runs_index
    assert "[EXP-0001](experiments/EXP-0001/summary.json)" in run_index
    assert "[worktree](../../worktrees/run-1/EXP-0001/)" in run_index
    assert "[factor-residuals](programs/factor-residuals/INDEX.md)" in archive_index


def test_refresh_indexes_rejects_outcome_mismatch(tmp_path: Path) -> None:
    paths = ResearchProgramPaths(tmp_path / "program")
    paths.create_directories()
    experiment_dir = paths.experiment_directory("run-1", "EXP-0001")
    experiment_dir.mkdir(parents=True)
    write_json(
        paths.state_path("run-1"),
        {
            "research_run_id": "run-1",
            "experiment_count": 1,
            "experiments": {"EXP-0001": {"outcome": "completed_candidate"}},
        },
    )
    write_json(
        experiment_dir / "summary.json",
        {"outcome": "completed_rejected", "summary": "Mismatch."},
    )

    with pytest.raises(ValueError, match="outcome mismatch"):
        refresh_research_indexes(paths.root)
    assert not (paths.runs / "INDEX.md").exists()


def test_cli_index_refreshes_program_views(tmp_path: Path) -> None:
    paths = ResearchProgramPaths(tmp_path / "program")
    paths.create_directories()

    assert main(["index", "--research-program-root", str(paths.root)]) == 0
    assert (paths.runs / "INDEX.md").is_file()
