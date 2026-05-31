# Material revision and feature spec artifacts

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement controller-owned Material Revision Policy and feature spec artifacts for material generated signals. Material revisions require fresh Critic review; agents may declare materiality but cannot declare a revision non-material.

## Acceptance criteria

- [ ] Policy covers the PRD default material fields.
- [ ] Agent-declared material revisions trigger fresh Critic review.
- [ ] Controller-detected material changes trigger fresh Critic review.
- [ ] Feature specs record transformation, data timing, lag, backfill range, missing-data policy, and failure modes.
- [ ] Tests cover material/non-material examples and feature spec validation.

## Blocked by

- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`
- `.scratch/research-experiment-plane/issues/14-evaluator-workspace-boundary-audit.md`

