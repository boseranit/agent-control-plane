# Shared boundary audit helpers

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add shared boundary audit primitives for git status snapshots, changed-file checks, path allowlist checks, and locked artifact hash checks. Keep Research-specific outcome mapping outside the shared package.

## Acceptance criteria

- [x] Helpers can compare worktree state before/after a phase.
- [x] Helpers report changed paths outside allowed edit paths.
- [x] Helpers verify locked artifact hashes from a manifest.
- [x] Tests cover pass/fail cases without embedding Research semantics.

## Blocked by

None - can start immediately

## Comments

- Added shared boundary audit helpers.
- Verified with `pixi run test` (`121 passed`).
