# Experiment Worktree and implementation repair path

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement preserved Experiment Worktree creation/reuse validation and the bounded Implementation Repair Loop for verification failures. Repairs use the same Implementer thread and may repair execution only, not research semantics.

## Acceptance criteria

- [x] One selected Research Experiment gets one preserved Experiment Worktree by default.
- [x] Dirty existing Experiment Worktrees are rejected.
- [x] `worktree.create: false` is allowed only for no-edit/read-only paths.
- [x] Verification retries up to `implementation.max_repairs`.
- [x] Tests cover worktree creation, dirty reuse rejection, pass/repair/exhaustion behavior.

## Blocked by

- `.scratch/research-experiment-plane/issues/04-shared-structured-command-runner.md`
- `.scratch/research-experiment-plane/issues/05-shared-boundary-audit-helpers.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`

## Comments

- Implemented preserved worktrees, verification repair retries, same-Implementer repair callback, and repair ledger events.
- Verified with `pixi run test`.
