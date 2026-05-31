# Research agents and prompt boundaries

Status: completed
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add Strategist, Critic, Implementer, and Evaluator agent definitions, prompts, thread lifetime helpers, and permission boundaries. Agents continue with explicit assumptions when human context is missing.

## Acceptance criteria

- [x] Strategist thread persists per Research Run.
- [x] Critic thread is fresh per critique pass.
- [x] Implementer thread persists per Experiment Worktree with workspace-write access.
- [x] Evaluator thread persists per Evaluator Workspace with workspace-write access.
- [x] Prompts encode artifact authority, materiality limits, and no human wait in v1.

## Blocked by

- `.scratch/research-experiment-plane/issues/03-shared-usage-limit-agent-runtime.md`
- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/09-deterministic-context-pack-prior-run-synthesis.md`

## Comments

- Implemented research agent configs, prompt boundaries, and thread lifetime helpers.
- Verified with `pixi run test`.
