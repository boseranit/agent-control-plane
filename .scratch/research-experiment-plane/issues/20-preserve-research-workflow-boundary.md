# Preserve Research workflow boundary while simplifying

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Tighten the implementation and tests so future simplification keeps the Research Experiment Controller as a sibling Control-Plane Workflow, not a Task Control Plane mode.

The review found the workflow boundary is required: a Research Experiment has a terminal Research Outcome and inspectable artifacts, while a Task has an approved plan, review approval, and final commit. This boundary should remain explicit while simplification work removes duplicate or durability-heavy internals.

Motivation: the easiest bad simplification is to force Research through Task semantics. That would save local code but lose the product contract: no final commit, first-class negative/inconclusive outcomes, preserved Experiment Worktree, Evaluator Workspace, and Research Run Mirror output.

This issue should make that boundary easy for later agents to preserve while patching larger issues.

## Acceptance criteria

- [x] Existing docs or comments clearly state Research remains a sibling Control-Plane Workflow with its own completion boundary.
- [x] Tests keep one narrow guard proving Research does not produce Task final-commit behavior.
- [x] No Task Control Plane lifecycle, approval, review, or commit semantics are introduced into Research.
- [x] Follow-on simplification issues can reference this issue as the boundary contract.

## Blocked by

None - can start immediately

## Comments

### Implementation

- Added package boundary note and e2e guard that Research leaves target repo HEAD unchanged.
