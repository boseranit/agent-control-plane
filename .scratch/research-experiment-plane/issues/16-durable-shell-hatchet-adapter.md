# Durable Shell and Hatchet adapter

Status: completed
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the provider-neutral Durable Execution Shell contract plus Hatchet workflow/worker adapter. Hatchet owns resume, sleeps, steps, and generic metadata only; Python controller code owns Research semantics.

## Acceptance criteria

- [x] Durable shell contract has no Hatchet imports.
- [x] Hatchet adapter exposes generic run metadata only: run id, phase, state version, status.
- [x] No Hatchet human event wait exists in v1.
- [x] Usage-limit waits sleep durably through the shell.
- [x] Tests mirror Task Hatchet tests without asserting Research semantics in decorator metadata.

## Completion notes

- Added provider-neutral Durable Shell plus Hatchet adapter/worker.
- Added durable usage-limit retry handling for real Research agent turns.
- Kept worktree cleanup behind the worktree helper.
- Verified with `pixi run test` (`251 passed`).

## Blocked by

- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`
