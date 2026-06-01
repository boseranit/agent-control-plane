# Decide material revision scope

Status: done
Label: ready-for-human
Type: HITL

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Decide and then simplify how the Research Experiment Controller detects material revisions across experiments.

The review found material revision policy is required, but the current direction risks too much controller inference: scanning prior Research Experiments, reading prior material artifacts, and triggering a fresh Critic pass before the normal design critique. That may be correct for strict research discipline, but it also adds a second hidden source of workflow control and more file-history coupling.

Decision needed: should v1 detect material revision only from the current selected plan and current artifacts, or should it compare against prior Research Experiments automatically?

Recommended minimal default: keep controller-owned materiality rules, keep agent-declared material categories, and keep explicit current-vs-prior comparison only when the comparison is directly supplied by the current flow. Do not make the controller search historical experiments for implicit prior specs in v1.

Motivation: materiality is research semantics, so it should not be deleted casually. But hidden cross-experiment scanning increases complexity and can create surprising Critic passes.

## Acceptance criteria

- [x] Human decision recorded in this issue comments or a small doc note.
- [x] Implementation matches chosen scope.
- [x] Material revisions still require fresh Critic review when the chosen scope detects them.
- [x] Non-material command/formatting changes still avoid extra Critic review.
- [x] Tests assert persisted artifacts, summary, and ledger categories, not fake-runtime prompt substrings.

## Blocked by

- `.scratch/research-experiment-plane/issues/21-collapse-experiment-flow-single-pipeline.md`

## Comments

### Human decision

- V1 material revision detection is current-flow only. No implicit historical scan.
- Compare prior/current artifacts only when current pipeline explicitly supplies both.
- Agent-declared material categories always trigger fresh Critic.
- New experiment vs previous experiment needs only normal design critique.

### Implementation

- Removed automatic prior-experiment scan; explicit prior/current pairs still trigger controller materiality.
