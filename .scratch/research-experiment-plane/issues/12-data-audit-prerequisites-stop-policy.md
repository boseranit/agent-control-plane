# Data audit and prerequisites stop policy

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement data-root checks, data audit command execution, prerequisite command execution, prerequisite failure classification, and Research Run Stop Policy for `stop_on_prerequisites_failed`.

## Acceptance criteria

- [ ] Data/prereq failures produce `outcome=prerequisites_failed` and `failed_stage=data_audit`.
- [ ] Failure classifications include the PRD-approved data/prereq values.
- [ ] Prerequisite commands run through the shared structured command runner.
- [ ] `stop_on_prerequisites_failed: true` stops the Research Run; false permits continuing.

## Blocked by

- `.scratch/research-experiment-plane/issues/04-shared-structured-command-runner.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`

