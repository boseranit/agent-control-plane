# Controller phase skeleton and no-op/blocked outcomes

Status: completed
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the minimal Research Experiment Controller loop and one bounded Research Experiment phase skeleton. Include outcome classification hooks for no selected plan, blocked conditions, invalid designs, run failures, and terminal completed outcomes.

## Acceptance criteria

- [x] One Research Run can iterate up to `max_experiments`.
- [x] One Research Experiment has at most one selected plan and one terminal Research Outcome.
- [x] `no_op` means no admissible experiment selected.
- [x] Selected-plan-without-deterministic-command is not classified as healthy `no_op`.
- [x] Tests cover loop bounds and terminal outcome routing.

## Blocked by

- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/09-deterministic-context-pack-prior-run-synthesis.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`

## Comments

- Implemented loop skeleton, per-experiment flow boundary, and no-op/blocked/run-failed outcome routing.
- Verified with `pixi run test`.
