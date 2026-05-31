# Research Run state, ledger, start/resume

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement Research Run startup and resume foundations: run directory layout, resolved spec snapshot, plain JSON controller state, append-only ledger, Research Experiment records, and terminal result loading.

## Acceptance criteria

- [ ] Starting a Research Run copies the resolved spec into the run directory.
- [ ] State records run id, phase, active experiment, experiment count, and thread ids where relevant.
- [ ] Ledger records phase and artifact events as JSONL.
- [ ] Resume reads the run snapshot/state, not the mutable source spec.

## Blocked by

- `.scratch/research-experiment-plane/issues/02-shared-artifact-state-primitives.md`
- `.scratch/research-experiment-plane/issues/06-research-run-spec-loader-snapshot-model.md`
- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`

