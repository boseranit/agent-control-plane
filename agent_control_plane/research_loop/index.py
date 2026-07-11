from __future__ import annotations

from collections import Counter
from pathlib import Path

from .records import (
    ExperimentResult,
    find_hypothesis,
    read_experiment_results,
    write_hypothesis,
)


def patch_hypothesis_status(root: Path, result: ExperimentResult) -> Path:
    path, doc = find_hypothesis(root, result.hypothesis_id)
    if result.verdict is not None:
        doc.frontmatter.status = result.verdict
    if result.exp_id not in doc.frontmatter.experiments:
        doc.frontmatter.experiments.append(result.exp_id)
    return write_hypothesis(root, doc)


def render_index(root: Path) -> Path:
    root = Path(root)
    results = read_experiment_results(root)
    counts = Counter(result.verdict or "inconclusive" for result in results)
    lines = [
        "# Research Loop Index",
        "",
        (
            "Status: "
            f"survived: {counts['survived']} | "
            f"killed: {counts['killed']} | "
            f"inconclusive: {counts['inconclusive']}"
        ),
        "",
        "| Hypothesis | Experiment | gate metric+value | bh_adjusted_p | verdict | driving reason |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            "| "
            f"{result.hypothesis_id} | "
            f"{result.exp_id} | "
            f"{result.gate_metric}={_fmt(result.gate_value)} | "
            f"{_fmt(result.bh_adjusted_p)} | "
            f"{result.verdict or 'inconclusive'} | "
            f"{_driving_reason(result)} |"
        )
    path = root / "INDEX.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _driving_reason(result: ExperimentResult) -> str:
    killed = next((finding for finding in result.adversary if finding.killed), None)
    if killed is not None:
        return killed.reason
    if result.adversary:
        return result.adversary[0].reason
    if result.error:
        return result.error
    return f"{result.gate_metric} {_fmt(result.gate_value)}"


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"
