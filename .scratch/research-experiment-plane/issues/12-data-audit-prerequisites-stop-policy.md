# Data audit and prerequisites stop policy

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement data-root checks, data audit command execution, prerequisite command execution, prerequisite failure classification, and Research Run Stop Policy for `stop_on_prerequisites_failed`.

## Acceptance criteria

- [x] Data/prereq failures produce `outcome=prerequisites_failed` and `failed_stage=data_audit`.
- [x] Failure classifications include the PRD-approved data/prereq values.
- [x] Prerequisite commands run through the shared structured command runner.
- [x] `stop_on_prerequisites_failed: true` stops the Research Run; false permits continuing.

## Blocked by

- `.scratch/research-experiment-plane/issues/04-shared-structured-command-runner.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`

## Comments

- Implemented data/prerequisite audit runner, failure classification, artifacts, and stop-policy tests.
- Verified with `pixi run test`.
