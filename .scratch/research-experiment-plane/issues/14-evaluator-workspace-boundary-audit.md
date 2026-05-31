# Evaluator Workspace and Evaluation Boundary Audit

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement Evaluator Workspace creation, manifest writing, evaluator cwd behavior, confirmatory/exploratory result capture, and Evaluation Boundary Audit for worktree changes and locked artifact hashes.

## Acceptance criteria

- [ ] Evaluator Workspace contains `manifest.json`, `eval_scratch/`, and `eval_outputs/`; no `eval_inputs/`.
- [ ] Manifest records canonical artifact paths, locked hashes, worktree, data root, commands, and git SHA.
- [ ] Evaluation Boundary Audit fails on worktree mutation or locked artifact hash changes.
- [ ] Boundary failure produces `outcome=run_failed` and `failed_stage=evaluation_boundary_audit`.
- [ ] Evaluation runtime/source defects are preserved as `run_failed` without implementer reroute.

## Blocked by

- `.scratch/research-experiment-plane/issues/04-shared-structured-command-runner.md`
- `.scratch/research-experiment-plane/issues/05-shared-boundary-audit-helpers.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`
- `.scratch/research-experiment-plane/issues/13-experiment-worktree-implementation-repair-path.md`

