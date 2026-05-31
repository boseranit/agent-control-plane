# Shared usage-limit and generic agent runtime

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Extract reusable usage-limit backoff and a generic agent runtime so Task and Research workflows can share retry behavior, arbitrary role names, thread reuse, output schemas, and capability policy without sharing workflow semantics.

## Acceptance criteria

- [ ] Usage-limit parsing handles retry timestamps/relative waits and retries once.
- [ ] Task Control Plane keeps existing behavior through compatibility imports/wrappers.
- [ ] Generic agent runtime supports read-only and workspace-write roles by policy.
- [ ] Tests cover arbitrary role names, fresh/persistent thread behavior, and Task compatibility.

## Blocked by

None - can start immediately

