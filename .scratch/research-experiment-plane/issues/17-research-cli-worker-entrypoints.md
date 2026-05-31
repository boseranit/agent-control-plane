# Research CLI and worker entrypoints

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add Research Experiment Controller CLI and module entrypoints for starting/resuming Research Runs, bridging the Durable Shell, and starting the Research Hatchet worker.

## Acceptance criteria

- [ ] CLI can start a Research Run from a Research Run Spec.
- [ ] CLI can resume an existing Research Run by id/runtime root.
- [ ] Worker entrypoint starts the Research Durable Shell adapter.
- [ ] `pixi.toml` includes a `research-experiment-worker` task.
- [ ] Tests cover CLI parsing and start/resume delegation.

## Blocked by

- `.scratch/research-experiment-plane/issues/06-research-run-spec-loader-snapshot-model.md`
- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/16-durable-shell-hatchet-adapter.md`

