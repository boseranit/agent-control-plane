# Controller phase skeleton and no-op/blocked outcomes

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the minimal Research Experiment Controller loop and one bounded Research Experiment phase skeleton. Include outcome classification hooks for no selected plan, blocked conditions, invalid designs, run failures, and terminal completed outcomes.

## Acceptance criteria

- [ ] One Research Run can iterate up to `max_experiments`.
- [ ] One Research Experiment has at most one selected plan and one terminal Research Outcome.
- [ ] `no_op` means no admissible experiment selected.
- [ ] Selected-plan-without-deterministic-command is not classified as healthy `no_op`.
- [ ] Tests cover loop bounds and terminal outcome routing.

## Blocked by

- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/09-deterministic-context-pack-prior-run-synthesis.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`

