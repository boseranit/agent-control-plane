# Research Loop

Stable language for `research_loop`: agents run bounded quantitative
experiments; code owns the statistical verdicts. Committed records are the
source of truth; agent thread memory is only continuity.

## Language

**Brief**:
The human-authored run contract at `eda/<slug>/PRD.md`: objective, baseline
reference, locked comparison anchor, scorecard, slice axes, boundaries,
guardrails. Run-specific facts live here, never in role prompts.
_Avoid_: run spec, config

**Record Tree**:
The committed per-run directory `eda/<slug>/` (`PRD.md`, `INDEX.md`, `notes.md`,
hypotheses/, experiments/, results/). Files are the loop state; there is no
separate state file.
_Avoid_: run directory, workspace

**Hypothesis**:
One testable idea as a markdown file with frontmatter status
(`ready-to-run | needs-data | survived | killed | inconclusive`). The
ready-to-run backlog is the follow-up queue.
_Avoid_: plan, proposal

**Experiment**:
One bounded test of one hypothesis slice, id `EXP-NNNN`: one frozen spec, one
self-contained run script, one result, one commit.
_Avoid_: cycle, iteration

**Frozen Spec**:
The immutable scientific contract for one Experiment (slice, gate, control
null, seed, data range, allowed write paths). Redesign means a new EXP id.
_Avoid_: design draft, latest version

**Gate**:
The pre-registered metric + threshold + direction in the Frozen Spec. Code
recomputes pass/fail from it; the Implementer's echo is never the decision.
_Avoid_: success criteria

**Adversary Lens**:
One independent read-only review of a gate-positive result: `leakage`,
`overfit-power`, `regime-robustness`. A leakage kill is a hard veto; otherwise
survival needs at least 2 not-killed lenses.
_Avoid_: critic, reviewer

**Run Family**:
All gate-positive results in a Record Tree — the BH-FDR (q = 0.10) correction
set.
_Avoid_: batch

**Verdict**:
The terminal classification of an Experiment, decided by code from Gate +
Adversary + BH-FDR: `survived | killed | inconclusive`.
_Avoid_: outcome, status, result

**Mirror**:
A non-authoritative external reflection (MLFlow) of terminal results, written
last; failures never touch the records.
_Avoid_: tracker, experiment state

**Strategist / Implementer / Adversary**:
The three agent roles (`agents/loop-*.md`). Strategist selects or registers
Hypotheses (persistent thread); Implementer writes and runs the experiment
script (workspace-write); Adversary reviews positives (read-only).
_Avoid_: planner, coder, evaluator