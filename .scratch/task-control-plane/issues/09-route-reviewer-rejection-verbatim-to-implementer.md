# Route Reviewer Rejection Verbatim to the Implementer

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Close the reviewer-rejection loop. When the Reviewer Agent rejects a Task, the Controller should append the full reviewer output to the review log and pass that reviewer JSON verbatim to the same persistent Implementer Agent thread. The Controller must not add a feedback-conversion agent or semantically rewrite reviewer feedback.

The loop should then return to deterministic test execution before any later review attempt.

## Acceptance criteria

- [ ] A review output with `status: rejected` is appended to the review log.
- [ ] Rejection increments or participates in the same shared Task iteration count used by failed-test repairs.
- [ ] The full reviewer JSON is sent verbatim to the same Implementer Agent thread.
- [ ] Blocking issues, requested changes, and non-blocking issues are all included in the verbatim feedback payload.
- [ ] No separate feedback-conversion Codex role is introduced.
- [ ] The Controller does not summarize or reinterpret reviewer feedback before sending it to the Implementer Agent.
- [ ] The Implementer Agent's latest result artifact is overwritten after the rejection repair turn.
- [ ] After rejection repair, the Controller returns to deterministic test execution before creating another Reviewer Agent.
- [ ] Reaching `max_iterations` during reviewer-rejection loops marks the Task failed, stops the Task Run, and leaves the Target Repository dirty.
- [ ] Tests verify verbatim payload preservation, same-thread implementer retry, review log append behavior, loop routing back to tests, and max iteration handling.

## Blocked by

- `.scratch/task-control-plane/issues/08-review-passing-work-with-fresh-reviewer-agents.md`

## Comments

### Implementation

- Commit: `7fbe40413b1cedfce254733965f592187e766fae`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added `run_active_task_review_rejection_repair(...)` for reviewer-rejection repair. Rejected reviewer JSON is appended to the review log and stored/sent to the same Implementer Agent thread verbatim, including blocking issues, requested changes, and non-blocking issues. The repair increments the shared iteration counter, overwrites the latest implementation result, clears stale test status so tests must run again before review, and fails the Task Run at the iteration cap without reverting dirty Target Repository changes.
