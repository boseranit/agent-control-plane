# Shared usage-limit and generic agent runtime

Status: completed
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Extract reusable usage-limit backoff and a generic agent runtime so Task and Research workflows can share retry behavior, arbitrary role names, thread reuse, output schemas, and capability policy without sharing workflow semantics.

## Acceptance criteria

- [x] Usage-limit parsing handles retry timestamps/relative waits and retries once.
- [x] Task Control Plane keeps existing behavior through compatibility imports/wrappers.
- [x] Generic agent runtime supports read-only and workspace-write roles by policy.
- [x] Tests cover arbitrary role names, fresh/persistent thread behavior, and Task compatibility.

## Blocked by

None - can start immediately

## Comments

- Added shared usage-limit backoff and generic agent runtime.
- Verified with `pixi run test` (`100 passed`).
