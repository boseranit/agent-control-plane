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
