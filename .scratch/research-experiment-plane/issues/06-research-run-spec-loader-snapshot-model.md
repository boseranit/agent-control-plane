# Research Run Spec loader and snapshot model

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the single-file Research Run Spec loader, including Research Brief, run controls, budget profiles, selected budget lookup, worktree config, MLflow config, Codex config, implementation repair limit, and `stop_on_prerequisites_failed`.

## Acceptance criteria

- [ ] Loader accepts the PRD's minimal YAML shape and validates required fields.
- [ ] Selected Research Budget exposes data window and default command timeout.
- [ ] Snapshot-ready resolved spec data is deterministic.
- [ ] Tests cover defaults, invalid specs, selected budget lookup, and stop policy.

## Blocked by

- `.scratch/research-experiment-plane/issues/02-shared-artifact-state-primitives.md`

