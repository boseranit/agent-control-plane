# Material revision and feature spec artifacts

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement controller-owned Material Revision Policy and feature spec artifacts for material generated signals. Material revisions require fresh Critic review; agents may declare materiality but cannot declare a revision non-material.

## Acceptance criteria

- [x] Policy covers the PRD default material fields.
- [x] Agent-declared material revisions trigger fresh Critic review.
- [x] Controller-detected material changes trigger fresh Critic review.
- [x] Feature specs record transformation, data timing, lag, backfill range, missing-data policy, and failure modes.
- [x] Tests cover material/non-material examples and feature spec validation.

## Blocked by

- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`
- `.scratch/research-experiment-plane/issues/14-evaluator-workspace-boundary-audit.md`
