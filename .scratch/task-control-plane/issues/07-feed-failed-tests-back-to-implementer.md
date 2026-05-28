# Feed Failed Tests Back to the Same Implementer Agent

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Close the failed-test loop. When deterministic tests fail after an Implementer Agent turn, the Controller should increment the shared iteration count, skip the Reviewer Agent, and send the command log path plus Approved Plan path back to the same persistent Implementer Agent thread.

If the shared iteration cap is reached, the Controller should mark the Task failed, stop the Task Run, and leave the Target Repository dirty for inspection.

## Acceptance criteria

- [ ] A failed test result does not create a Reviewer Agent thread.
- [ ] A failed test result increments the Task iteration count.
- [ ] The Controller sends failed-test feedback to the same Implementer Agent thread.
- [ ] Failed-test feedback includes the command log path and Approved Plan path.
- [ ] The Implementer Agent's latest result artifact is overwritten after the repair turn.
- [ ] The same iteration counter is used for failed-test repair cycles and later reviewer-rejection cycles.
- [ ] Reaching `max_iterations` marks the Task failed.
- [ ] Reaching `max_iterations` stops the Task Run before any later Task starts.
- [ ] Reaching `max_iterations` does not revert Target Repository changes.
- [ ] Tests verify failed tests bypass review, same-thread implementer retry, iteration counting, max iteration failure, dirty-state preservation, and no later Task execution.

## Blocked by

- `.scratch/task-control-plane/issues/06-execute-test-commands-with-streaming-command-log.md`

## Comments

### Implementation

- Commit: `75ee576332ffbd34f327b26dc16f6e84c672e434`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added `run_active_task_failed_test_repair(...)` for failed deterministic test repair. The controller increments the shared Task iteration counter, bypasses review, sends the command log path and Approved Plan path back to the same Implementer Agent thread, overwrites the latest implementation result, and marks the Task Run failed at the iteration cap without reverting dirty Target Repository changes. Reviewer behavior remains out of scope for issue 08.
