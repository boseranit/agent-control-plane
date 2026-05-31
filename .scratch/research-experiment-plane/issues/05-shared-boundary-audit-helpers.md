# Shared boundary audit helpers

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add shared boundary audit primitives for git status snapshots, changed-file checks, path allowlist checks, and locked artifact hash checks. Keep Research-specific outcome mapping outside the shared package.

## Acceptance criteria

- [ ] Helpers can compare worktree state before/after a phase.
- [ ] Helpers report changed paths outside allowed edit paths.
- [ ] Helpers verify locked artifact hashes from a manifest.
- [ ] Tests cover pass/fail cases without embedding Research semantics.

## Blocked by

None - can start immediately

