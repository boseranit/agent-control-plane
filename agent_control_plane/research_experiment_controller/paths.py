from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResearchProgramPaths:
    root: str | Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    @property
    def runs(self) -> Path:
        return Path(self.root) / "runs"

    @property
    def worktrees(self) -> Path:
        return Path(self.root) / "worktrees"

    @property
    def memory(self) -> Path:
        return Path(self.root) / "memory"

    def create_directories(self) -> None:
        for path in (self.runs, self.worktrees, self.memory):
            path.mkdir(parents=True, exist_ok=True)

    def run_directory(self, research_run_id: str) -> Path:
        _require_non_empty_id(research_run_id, "Research Run ID")
        return self.runs / research_run_id

    def spec_snapshot_path(self, research_run_id: str) -> Path:
        return self.run_directory(research_run_id) / "research_run_spec.yaml"

    def state_path(self, research_run_id: str) -> Path:
        return self.run_directory(research_run_id) / "state.json"

    def ledger_path(self, research_run_id: str) -> Path:
        return self.run_directory(research_run_id) / "ledger.jsonl"

    def experiments_directory(self, research_run_id: str) -> Path:
        return self.run_directory(research_run_id) / "experiments"

    def experiment_directory(
        self,
        research_run_id: str,
        experiment_id: str,
    ) -> Path:
        _require_non_empty_id(experiment_id, "Research Experiment ID")
        return self.experiments_directory(research_run_id) / experiment_id

    def worktree_directory(
        self,
        research_run_id: str,
        experiment_id: str,
    ) -> Path:
        _require_non_empty_id(research_run_id, "Research Run ID")
        _require_non_empty_id(experiment_id, "Research Experiment ID")
        return self.worktrees / research_run_id / experiment_id


def _require_non_empty_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
