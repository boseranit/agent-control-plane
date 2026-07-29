from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from agent_control_plane.research_agent_defaults import DEFAULT_RESEARCH_AGENT_MODEL

from .gates import apply_bh_fdr, decide_verdict, looks_positive
from .gitops import (
    CommitFailedError,
    DirtyRepositoryError,
    assert_changes_within,
    changed_files,
    commit_all,
    reset_hard_and_clean,
)
from .index import patch_hypothesis_status, render_index
from .mirror import Mirror, MirrorRequest, NoOpMirror, mirror_experiment
from .records import (
    AdversaryFinding,
    ExperimentResult,
    ExperimentSpec,
    GateSpec,
    HypothesisDoc,
    HypothesisFrontmatter,
    ensure_record_tree,
    experiment_result_path,
    experiment_run_path,
    find_hypothesis,
    next_experiment_id,
    read_experiment_result,
    read_experiment_results,
    write_experiment_result,
    write_experiment_spec,
    write_hypothesis,
)
from .roles import (
    adversary_role_config,
    implementer_role_config,
    strategist_role_config,
)
from .runtime import AgentRuntime

ADVERSARY_LENSES = ("leakage", "overfit-power", "regime-robustness")


@dataclass(frozen=True)
class LoopConfig:
    repo: Path
    slug: str
    max_experiments: int
    model: str = DEFAULT_RESEARCH_AGENT_MODEL
    reasoning_effort: str = "high"
    baseline_required: bool = True
    mirror_tracking_uri: Optional[str] = None
    mirror_experiment_name: Optional[str] = None
    max_consecutive_failures: int = 3
    error_backoff_seconds: float = 30.0


@dataclass
class LoopSummary:
    stop_reason: str
    experiments_completed: int = 0
    no_ops: int = 0
    reported_failures: int = 0
    errors: int = 0
    commits: list[str] = field(default_factory=list)


class StrategyHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^H\d+$")
    title: str
    thesis: str
    signal: str
    target: str
    universe: str
    horizon: str
    gate: GateSpec
    leakage_guard: str


class StrategyTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected: bool
    hypothesis: Optional[StrategyHypothesis] = None
    spec: Optional[ExperimentSpec] = None
    new_hypotheses: list[StrategyHypothesis] = Field(default_factory=list)
    key_learnings: list[str] = Field(default_factory=list)
    should_stop: bool = False


class ImplementerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    result: ExperimentResult
    key_changes: list[str] = Field(default_factory=list)
    key_learnings: list[str] = Field(default_factory=list)


class ResearchLoop:
    def __init__(
        self,
        config: LoopConfig,
        runtime: AgentRuntime,
        *,
        mirror: Optional[Mirror] = None,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.mirror = mirror or NoOpMirror()
        self.strategist_thread_id: Optional[str] = None
        self._pending_commit: Optional[_PendingCommit] = None

    def run(self) -> LoopSummary:
        repo = Path(self.config.repo)
        root = ensure_record_tree(repo, self.config.slug)
        brief_path = root / "PRD.md"
        if not brief_path.is_file():
            raise ValueError(f"expected research brief at {brief_path}")

        completed = 0
        no_ops = 0
        reported_failures = 0
        errors = 0
        consecutive_failures = 0
        commits: list[str] = []

        def summary(stop_reason: str) -> LoopSummary:
            return LoopSummary(
                stop_reason=stop_reason,
                experiments_completed=completed,
                no_ops=no_ops,
                reported_failures=reported_failures,
                errors=errors,
                commits=commits,
            )

        while completed < self.config.max_experiments:
            try:
                outcome = self._run_one()
            except DirtyRepositoryError:
                raise
            except Exception:
                # A pending failed commit keeps its dirty records for repair.
                if self._pending_commit is None:
                    reset_hard_and_clean(repo)
                no_ops = 0
                errors += 1
                consecutive_failures += 1
                if consecutive_failures >= self.config.max_consecutive_failures:
                    return summary("max_consecutive_failures")
                delay = self.config.error_backoff_seconds * (
                    2 ** (consecutive_failures - 1)
                )
                if delay > 0:
                    time.sleep(delay)
                continue

            if outcome.kind == "no_op":
                consecutive_failures = 0
                no_ops += 1
                if no_ops >= 2:
                    return summary("two_consecutive_no_ops")
                continue
            no_ops = 0

            if outcome.kind in ("reported_failure", "commit_failed"):
                if outcome.kind == "reported_failure":
                    reported_failures += 1
                consecutive_failures += 1
                if consecutive_failures >= self.config.max_consecutive_failures:
                    return summary("max_consecutive_failures")
                continue

            consecutive_failures = 0
            completed += 1
            if outcome.commit_sha:
                commits.append(outcome.commit_sha)
            if outcome.kind == "baseline_not_reproduced":
                return summary("baseline_not_reproduced")

        return summary("max_experiments")

    def _run_one(self) -> "_ExperimentOutcome":
        repo = Path(self.config.repo)
        root = ensure_record_tree(repo, self.config.slug)
        if self._pending_commit is not None:
            return self._retry_pending_commit(repo, root, self._pending_commit)

        dirty = changed_files(repo)
        record_prefix = f"eda/{self.config.slug}/"
        if dirty and all((path.startswith(record_prefix) for path in dirty)):
            reset_hard_and_clean(repo)
        elif dirty:
            raise DirtyRepositoryError(dirty)

        strategy = self._run_strategy(root)
        if not strategy.selected or strategy.should_stop:
            return _ExperimentOutcome(kind="no_op")
        if strategy.hypothesis is None or strategy.spec is None:
            return _ExperimentOutcome(kind="no_op")
        self._write_backlog(root, strategy.new_hypotheses)
        spec = self._freeze_selected_spec(root, strategy)

        implemented = self._run_implementer(root, spec)
        if not implemented.success:
            reset_hard_and_clean(repo)
            return _ExperimentOutcome(kind="reported_failure")
        if not experiment_run_path(root, spec.exp_id).is_file():
            reset_hard_and_clean(repo)
            return _ExperimentOutcome(kind="reported_failure")

        corrected = implemented.result.model_copy(
            update={
                "exp_id": spec.exp_id,
                "hypothesis_id": spec.hypothesis_id,
                "gate_metric": spec.gate.metric,
                "gate_threshold": spec.gate.threshold,
                "gate_direction": spec.gate.direction,
            }
        )
        result = corrected.model_copy(
            update={"looks_positive": looks_positive(corrected)}
        )
        if result.looks_positive:
            result = result.model_copy(
                update={"adversary": self._run_adversary(root, result)}
            )

        final_result = self._finalize_result_family(root, result)
        append_notes(
            root,
            final_result,
            [*strategy.key_learnings, *implemented.key_learnings],
        )
        render_index(root)

        commit_message = (
            f"{final_result.exp_id}: {final_result.verdict} - "
            f"{strategy.hypothesis.title}"
        )
        try:
            assert_changes_within(repo, record_prefix)
            commit_sha = commit_all(repo, commit_message)
        except CommitFailedError as exc:
            self._pending_commit = _PendingCommit(
                message=commit_message, exp_id=final_result.exp_id, error=exc
            )
            return _ExperimentOutcome(kind="commit_failed")
        return self._after_commit(root, final_result, commit_sha)

    def _retry_pending_commit(
        self, repo: Path, root: Path, pending: "_PendingCommit"
    ) -> "_ExperimentOutcome":
        role = implementer_role_config(
            cwd=str(repo),
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
        )
        self.runtime.run_turn(
            role=role, prompt=commit_repair_prompt(root, pending.error)
        )
        try:
            assert_changes_within(repo, f"eda/{self.config.slug}/")
            commit_sha = commit_all(repo, pending.message)
        except CommitFailedError as exc:
            self._pending_commit = _PendingCommit(
                message=pending.message, exp_id=pending.exp_id, error=exc
            )
            return _ExperimentOutcome(kind="commit_failed")
        self._pending_commit = None
        return self._after_commit(
            root, read_experiment_result(root, pending.exp_id), commit_sha
        )

    def _after_commit(
        self, root: Path, final_result: ExperimentResult, commit_sha: str
    ) -> "_ExperimentOutcome":
        mirror_experiment(
            self.mirror,
            self._mirror_request(root, final_result, commit_sha),
        )
        if (
            self.config.baseline_required
            and final_result.exp_id == "EXP-0001"
            and final_result.verdict != "survived"
        ):
            return _ExperimentOutcome(
                kind="baseline_not_reproduced",
                commit_sha=commit_sha,
            )
        return _ExperimentOutcome(kind="completed", commit_sha=commit_sha)

    def _run_strategy(self, root: Path) -> StrategyTurn:
        role = strategist_role_config(
            cwd=str(self.config.repo),
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
            output_schema=StrategyTurn.model_json_schema(),
        )
        result = self.runtime.run_turn(
            role=role,
            prompt=strategy_prompt(root),
            prior_thread_id=self.strategist_thread_id,
            on_thread_started=self._set_strategist_thread,
        )
        return StrategyTurn.model_validate(result.structured or {})

    def _run_implementer(self, root: Path, spec: ExperimentSpec) -> ImplementerTurn:
        role = implementer_role_config(
            cwd=str(self.config.repo),
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
            output_schema=ImplementerTurn.model_json_schema(),
        )
        result = self.runtime.run_turn(
            role=role,
            prompt=implementer_prompt(root, spec),
        )
        return ImplementerTurn.model_validate(result.structured or {})

    def _run_adversary(
        self,
        root: Path,
        result: ExperimentResult,
    ) -> list[AdversaryFinding]:
        findings: list[AdversaryFinding] = []
        role = adversary_role_config(
            cwd=str(self.config.repo),
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
            output_schema=AdversaryFinding.model_json_schema(),
        )
        for lens in ADVERSARY_LENSES:
            turn = self.runtime.run_turn(
                role=role,
                prompt=adversary_prompt(root, result.exp_id, lens),
            )
            # The lens is code-owned: record the one we asked for, not the echo.
            findings.append(
                AdversaryFinding.model_validate(
                    {**(turn.structured or {}), "lens": lens}
                )
            )
        return findings

    def _freeze_selected_spec(
        self, root: Path, strategy: StrategyTurn
    ) -> ExperimentSpec:
        assert strategy.spec is not None
        assert strategy.hypothesis is not None
        exp_id = next_experiment_id(root)
        spec = strategy.spec.model_copy(
            update={
                "exp_id": exp_id,
                "hypothesis_id": strategy.hypothesis.id,
                "allowed_write_paths": _allowed_write_paths(
                    Path(self.config.repo), root, exp_id
                ),
            }
        )
        write_hypothesis(root, _hypothesis_doc(strategy.hypothesis, exp_id))
        write_experiment_spec(root, spec)
        return spec

    def _write_backlog(self, root: Path, hypotheses: list[StrategyHypothesis]) -> None:
        for hypothesis in hypotheses:
            write_hypothesis(root, _hypothesis_doc(hypothesis, None))

    def _finalize_result_family(
        self,
        root: Path,
        current_result: ExperimentResult,
    ) -> ExperimentResult:
        write_experiment_result(root, current_result)
        results = read_experiment_results(root)
        decisions = apply_bh_fdr(results)
        final_current = current_result
        for result in results:
            decision = decisions.get(result.exp_id)
            final = result.model_copy(
                update={
                    "bh_adjusted_p": None if decision is None else decision.adjusted_p,
                    "verdict": decide_verdict(
                        result, decision.passed if decision else False
                    ),
                    "looks_positive": looks_positive(result),
                }
            )
            write_experiment_result(root, final)
            patch_hypothesis_status(root, final)
            if final.exp_id == current_result.exp_id:
                final_current = final
        return final_current

    def _mirror_request(
        self,
        root: Path,
        result: ExperimentResult,
        git_sha: str,
    ) -> MirrorRequest:
        # The mirror must never fail the run; a missing hypothesis file becomes
        # a conventional path the adapter skips as a non-file.
        try:
            hypothesis_path = find_hypothesis(root, result.hypothesis_id)[0]
        except FileNotFoundError:
            hypothesis_path = Path(root) / "hypotheses" / f"{result.hypothesis_id}.md"
        return MirrorRequest(
            research_run_id=self.config.slug,
            exp_id=result.exp_id,
            record_root=Path(root),
            result_path=experiment_result_path(root, result.exp_id),
            spec_path=Path(root) / "experiments" / f"{result.exp_id}-spec.json",
            run_path=experiment_run_path(root, result.exp_id),
            hypothesis_path=hypothesis_path,
            tracking_uri=self.config.mirror_tracking_uri,
            experiment_name=self.config.mirror_experiment_name,
            git_sha=git_sha,
        )

    def _set_strategist_thread(self, thread_id: str) -> None:
        self.strategist_thread_id = thread_id


@dataclass(frozen=True)
class _ExperimentOutcome:
    kind: str
    commit_sha: Optional[str] = None


@dataclass(frozen=True)
class _PendingCommit:
    message: str
    exp_id: str
    error: CommitFailedError


def strategy_prompt(root: Path) -> str:
    return "\n".join(
        [
            "Read these committed records by path before selecting the next experiment:",
            str(Path(root) / "PRD.md"),
            str(Path(root) / "INDEX.md"),
            str(Path(root) / "notes.md"),
            str(Path(root) / "hypotheses"),
            str(Path(root) / "experiments"),
            str(Path(root) / "results"),
            "Return one selected plan or selected=false.",
        ]
    )


def implementer_prompt(root: Path, spec: ExperimentSpec) -> str:
    return "\n".join(
        [
            f"Run frozen spec {Path(root) / 'experiments' / f'{spec.exp_id}-spec.json'}.",
            f"Write script {experiment_run_path(root, spec.exp_id)}.",
            f"Write result {experiment_result_path(root, spec.exp_id)}.",
            "Echo gate and scorecard numbers faithfully.",
        ]
    )


def adversary_prompt(
    root: Path,
    exp_id: str,
    lens: str,
) -> str:
    return "\n".join(
        [
            f"Lens: {lens}",
            f"Spec: {Path(root) / 'experiments' / f'{exp_id}-spec.json'}",
            f"Script: {experiment_run_path(root, exp_id)}",
            f"Result: {experiment_result_path(root, exp_id)}",
            "Return lens, killed, reason, evidence.",
        ]
    )


def commit_repair_prompt(root: Path, error: CommitFailedError) -> str:
    return "\n".join(
        [
            "The git commit for these records failed.",
            f"Failed commit message: {error.message}",
            f"Record root: {root}",
            "stderr:",
            error.stderr or "<empty>",
            "stdout:",
            error.stdout or "<empty>",
            f"Fix whatever blocks the commit, only touching files under {root}.",
            "Do not run git commit yourself.",
        ]
    )


def append_notes(
    root: Path,
    result: ExperimentResult,
    learnings: list[str],
) -> Path:
    path = Path(root) / "notes.md"
    lines = [
        f"### {result.exp_id} - {result.verdict}",
        f"gate {result.gate_metric} = {result.gate_value:g}",
    ]
    for learning in learnings:
        lines.append(f"- {learning}")
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _hypothesis_doc(
    hypothesis: StrategyHypothesis, exp_id: Optional[str]
) -> HypothesisDoc:
    slug = _slugify(hypothesis.title)
    experiments = [] if exp_id is None else [exp_id]
    return HypothesisDoc(
        frontmatter=HypothesisFrontmatter(
            id=hypothesis.id,
            slug=slug,
            status="ready-to-run",
            experiments=experiments,
        ),
        body=(
            f"## Thesis\n{hypothesis.thesis}\n\n"
            f"## Signal\n{hypothesis.signal}\n\n"
            f"## Target / universe / horizon\n"
            f"{hypothesis.target} / {hypothesis.universe} / {hypothesis.horizon}\n\n"
            f"## Gate\n"
            f"{hypothesis.gate.metric} {hypothesis.gate.direction} "
            f"{hypothesis.gate.threshold:g}\n\n"
            f"## Leakage guard\n{hypothesis.leakage_guard}\n\n"
            "## Decision\n"
        ),
    )


def _allowed_write_paths(repo: Path, root: Path, exp_id: str) -> list[str]:
    record_root = Path(root)
    rel_root = record_root.relative_to(Path(repo))
    return [
        (rel_root / "experiments" / f"{exp_id}-run.py").as_posix(),
        (rel_root / "results" / f"{exp_id}-result.json").as_posix(),
    ]


def _slugify(value: str) -> str:
    slug = "-".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return "-".join(part for part in slug.split("-") if part) or "hypothesis"
