# Durable Shell and Hatchet adapter

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the provider-neutral Durable Execution Shell contract plus Hatchet workflow/worker adapter. Hatchet owns resume, sleeps, steps, and generic metadata only; Python controller code owns Research semantics.

## Acceptance criteria

- [ ] Durable shell contract has no Hatchet imports.
- [ ] Hatchet adapter exposes generic run metadata only: run id, phase, state version, status.
- [ ] No Hatchet human event wait exists in v1.
- [ ] Usage-limit waits sleep durably through the shell.
- [ ] Tests mirror Task Hatchet tests without asserting Research semantics in decorator metadata.

## Blocked by

- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`

