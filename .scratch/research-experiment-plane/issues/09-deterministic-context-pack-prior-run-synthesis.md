# Deterministic context pack and prior-run synthesis

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Build deterministic Research context output containing spec facts, budget, data root, git state, artifact inventory, ledger history, prior outcomes, repeated blockers, completed prerequisites, and useful metric history.

## Acceptance criteria

- [ ] `context_pack.md` and `context_summary.json` are deterministic for the same inputs.
- [ ] Prior-run synthesis distinguishes blockers, prerequisites, failures, and completed outcomes.
- [ ] Context includes selected Research Budget, data root, repo root, and git SHA/status.
- [ ] Tests cover context content and stable output.

## Blocked by

- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`

