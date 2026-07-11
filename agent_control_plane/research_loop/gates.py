from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .records import AdversaryFinding, ExperimentResult, Verdict


@dataclass(frozen=True)
class AdversaryOutcome:
    survived: bool
    leakage_killed: bool
    not_killed_count: int


@dataclass(frozen=True)
class BhDecision:
    family_size: int
    rank: int
    adjusted_p: float
    passed: bool


def looks_positive(result: ExperimentResult) -> bool:
    if not result.ran_ok:
        return False
    if result.gate_direction == "below":
        return result.gate_value <= result.gate_threshold
    return result.gate_value >= result.gate_threshold


def aggregate_adversary(findings: Iterable[AdversaryFinding]) -> AdversaryOutcome:
    verdicts = list(findings)
    not_killed_count = sum(1 for finding in verdicts if not finding.killed)
    leakage = next((finding for finding in verdicts if finding.lens == "leakage"), None)
    leakage_killed = True if leakage is None else leakage.killed
    survived = not leakage_killed and not_killed_count >= 2
    return AdversaryOutcome(
        survived=survived,
        leakage_killed=leakage_killed,
        not_killed_count=not_killed_count,
    )


def apply_bh_fdr(
    results: Iterable[ExperimentResult],
    *,
    q: float = 0.10,
) -> dict[str, BhDecision]:
    tested = [(result, result.null_p) for result in results if looks_positive(result)]
    family_size = len(tested)
    if family_size == 0:
        return {}

    by_p = sorted(tested, key=lambda item: item[1])
    kmax = 0
    for rank, (_result, p) in enumerate(by_p, start=1):
        if p <= (rank / family_size) * q:
            kmax = rank

    raw_adjusted = [
        min(1.0, (p * family_size) / rank)
        for rank, (_result, p) in enumerate(by_p, start=1)
    ]
    adjusted_by_rank = raw_adjusted[:]
    for index in range(family_size - 2, -1, -1):
        adjusted_by_rank[index] = min(
            adjusted_by_rank[index],
            adjusted_by_rank[index + 1],
        )

    decisions: dict[str, BhDecision] = {}
    for rank, ((result, _p), adjusted_p) in enumerate(
        zip(by_p, adjusted_by_rank),
        start=1,
    ):
        decisions[result.exp_id] = BhDecision(
            family_size=family_size,
            rank=rank,
            adjusted_p=adjusted_p,
            passed=rank <= kmax,
        )
    return decisions


def decide_verdict(result: ExperimentResult, bh_passed: bool) -> Verdict:
    if not looks_positive(result):
        return "inconclusive"
    if aggregate_adversary(result.adversary).survived and bh_passed:
        return "survived"
    return "killed"
