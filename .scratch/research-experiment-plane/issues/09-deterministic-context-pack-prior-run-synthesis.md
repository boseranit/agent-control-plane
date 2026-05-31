# Deterministic context pack and prior-run synthesis

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Build deterministic Research context output containing spec facts, budget, data root, git state, artifact inventory, ledger history, prior outcomes, repeated blockers, completed prerequisites, and useful metric history.

## Acceptance criteria

- [x] `context_pack.md` and `context_summary.json` are deterministic for the same inputs.
- [x] Prior-run synthesis distinguishes blockers, prerequisites, failures, and completed outcomes.
- [x] Context includes selected Research Budget, data root, repo root, and git SHA/status.
- [x] Tests cover context content and stable output.

## Blocked by

- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`

## Comments

- Added deterministic context pack and context summary generation.
- Verified with `pixi run test` (`172 passed`).
