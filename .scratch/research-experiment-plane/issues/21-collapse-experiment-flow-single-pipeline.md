# Collapse experiment flow to one pipeline

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Replace the current split per-experiment implementation with one linear Research Experiment pipeline.

The review found two parallel paths: a manual/test selection path and an agent-driven path. Both perform the same lifecycle work: write selected artifacts, apply selection gates, handle material revision review, run data/prerequisite audit, prepare worktree, run implementation/verification, evaluate, write summary, and request mirror output. This duplicates behavior and makes every later change twice as risky.

Target shape: one pipeline owns the Research Experiment lifecycle. It should accept a provider for the selected plan/design/artifacts. The provider may be agent-driven or test-supplied, but after selection exists, all behavior goes through the same code path.

Motivation: this is the highest-leverage simplification. It deletes branching structure instead of polishing it, reduces line count, and makes status/artifact ordering easier to reason about.

## Acceptance criteria

- [x] Agent-driven and test-supplied Research Experiments use the same lifecycle path after selection exists.
- [x] Selection failure, material revision review, data audit, worktree policy, verification, evaluation, summary, and mirror behavior have one implementation each.
- [x] Existing persisted contract remains: selected plan, data audit, implementation/diff, evaluation artifacts, summary, ledger events, and terminal state still match current behavior.
- [x] Full agent-driven fake-runtime path still reaches a terminal Research Outcome.
- [x] Per-experiment flow file is materially smaller and easier to scan; no new generic workflow framework is introduced.

## Blocked by

- `.scratch/research-experiment-plane/issues/20-preserve-research-workflow-boundary.md`

## Comments

### Implementation

- Collapsed agent-driven and supplied-selection execution into one selected-experiment pipeline.
