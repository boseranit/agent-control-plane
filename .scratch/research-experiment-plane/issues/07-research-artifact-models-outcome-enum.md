# Research Artifact models and outcome enum

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add Pydantic models for canonical Research Artifacts and the single Research Outcome enum. Keep controller state and ledgers plain JSON/JSONL; use Pydantic only at artifact boundaries.

## Acceptance criteria

- [x] Research Outcome enum contains only the PRD-approved values.
- [x] Core artifacts validate selected plan, spec/design, critique, audit, evaluation, summary, and plan update payloads.
- [x] Diagnostic fields support `outcome_reason`, `failed_stage`, and `failure_classification`.
- [x] Tests cover valid artifacts, invalid artifacts, and enum serialization.

## Blocked by

- `.scratch/research-experiment-plane/issues/02-shared-artifact-state-primitives.md`

## Comments

- Added canonical Research Artifact models and Research Outcome enum.
- Verified with `pixi run test` (`155 passed`).
