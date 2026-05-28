# Execute Test Commands with Streaming Task Command Logs

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add deterministic test execution after each Implementer Agent turn. The Controller should run all of the Task Spec's named argv test commands in the Target Repository, stream all output into a single Task command log, record command status for every command, and report an aggregate pass/fail result.

This slice should not involve the Reviewer Agent yet. It should make the command log and test result reliable enough for later review and retry slices.

## Acceptance criteria

- [ ] The Controller runs each named argv test command in the Target Repository.
- [ ] Shell strings are not executed as test commands.
- [ ] All command output is appended to a single Task command log with clear command boundaries.
- [ ] Command output streams while the process runs rather than only after process exit.
- [ ] The command log records command names, argv, start/end information, stdout/stderr output, and exit codes.
- [ ] The command runner returns an aggregate pass/fail result.
- [ ] The Controller records latest test status in Task State.
- [ ] A failing command marks the aggregate test result failed.
- [ ] All declared test commands run even after an earlier command fails.
- [ ] The aggregate test result includes every command result and is suitable to pass directly back to the Implementer Agent on failure.
- [ ] Tests use small subprocesses and temporary Target Repositories to verify command ordering, streaming log writes, passing commands, failing commands, all-commands-run behavior, aggregate failure reporting, and Task State status updates.

## Blocked by

- `.scratch/task-control-plane/issues/05-run-implementer-agent-from-approved-plan.md`

## Comments

### Implementation

- Commit: `e6fe9c62641dc74a4e60e1492db868f7d22d7a43`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added `run_active_task_tests(...)` with argv-only subprocess execution in the Target Repository, append-only streaming command logs, per-command boundaries and exit codes, aggregate pass/fail including every command result, all-commands-run behavior after failures, and Task State `latest_test_status` recording. Reviewer routing and failed-test repair remain out of scope for later issues.
