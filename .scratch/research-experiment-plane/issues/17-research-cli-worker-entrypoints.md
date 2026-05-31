# Research CLI and worker entrypoints

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add Research Experiment Controller CLI and module entrypoints for starting/resuming Research Runs, bridging the Durable Shell, and starting the Research Hatchet worker.

## Acceptance criteria

- [x] CLI can start a Research Run from a Research Run Spec.
- [x] CLI can resume an existing Research Run by id/runtime root.
- [x] Worker entrypoint starts the Research Durable Shell adapter.
- [x] `pixi.toml` includes a `research-experiment-worker` task.
- [x] Tests cover CLI parsing and start/resume delegation.

## Completion notes

- Added Research CLI and module entrypoint.
- Added `research-experiment-worker` pixi task.
- Added CLI parsing, start, resume delegation, and import-boundary tests.
- Verified with `pixi run test` (`259 passed`).

## Blocked by

- `.scratch/research-experiment-plane/issues/06-research-run-spec-loader-snapshot-model.md`
- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/16-durable-shell-hatchet-adapter.md`
