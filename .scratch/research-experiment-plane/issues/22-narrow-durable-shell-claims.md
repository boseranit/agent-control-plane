# Narrow Durable Shell claims

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Align Research durable behavior with what the code actually supports and with the current low-durability priority.

The review found a mismatch: the Durable Execution Shell exists and can sleep/retry on usage limits, but the controller runs a whole Research Experiment as one call after setting phase to `running_experiment`. Resume does not actually restart from internal experiment phases. That is acceptable if stated plainly; it is not acceptable if tests or docs imply full mid-experiment durability.

Target behavior: keep Hatchet as an optional thin shell for generic metadata and usage-limit sleeps, but stop treating it as a full phase-resume engine. Do not add a phase state machine in this issue.

Motivation: durability is not a high priority. More phase persistence would add code and state without solving the main local-review workflow. Simpler honest semantics are better.

## Acceptance criteria

- [x] Docs/tests describe the shell as thin: generic metadata plus usage-limit sleep/retry, not full mid-experiment resume.
- [x] Controller behavior remains ordinary Python-owned Research semantics.
- [x] Hatchet adapter remains isolated from Research semantics and imports.
- [x] No new durable state machine, event wait, or phase-by-phase persistence is added.
- [x] Tests cover the actual durable contract without pinning private shell internals.

## Blocked by

- `.scratch/research-experiment-plane/issues/20-preserve-research-workflow-boundary.md`

## Comments

### Implementation

- ADR/PRD now describe Hatchet as generic metadata plus usage-limit sleep/retry, not mid-experiment resume.
