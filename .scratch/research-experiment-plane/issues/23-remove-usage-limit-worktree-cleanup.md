# Remove usage-limit worktree cleanup

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Delete automatic in-progress Experiment Worktree cleanup when a usage-limit wait interrupts a Research Experiment.

The review found cleanup-on-usage-limit is a durability/idempotency guard. It conflicts with the Research Experiment Plane policy that Experiment Worktrees are preserved and not automatically cleaned. The useful contract is dirty existing worktree rejection before reuse, not cleanup after an interrupted attempt.

Target behavior: if usage-limit wait occurs, controller may reset run state for retry, but it should not remove a created worktree or delete branch/worktree state as a hidden side effect. Later retry should rely on existing dirty-worktree protection and human inspection if needed.

Motivation: hidden cleanup can destroy the very inspection surface the workflow is designed to preserve. Given low durability priority, prefer explicit human review over automatic repair of low-probability retry state.

## Acceptance criteria

- [x] Usage-limit wait no longer removes Experiment Worktree directories or branches.
- [x] Dirty existing Experiment Worktree rejection remains intact.
- [x] Usage-limit shell retry still sleeps and can resume the Research Run where supported.
- [x] Tests no longer assert automatic cleanup of dirty in-progress worktrees.
- [x] Documentation or test names make clear interrupted worktrees are preserved for review.

## Blocked by

- `.scratch/research-experiment-plane/issues/22-narrow-durable-shell-claims.md`

## Comments

### Implementation

- Removed usage-limit worktree/branch cleanup; dirty interrupted worktrees are preserved and rejected on retry.
