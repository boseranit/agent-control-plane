# Execute Test Commands with Streaming Task Command Logs

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add deterministic test execution after each Implementer Agent turn. The Controller should run the Task Spec's named argv test commands in the Target Repository, stream all output into a single Task command log, record command status, and report whether the test gate passed.

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
- [ ] The behavior after the first failing command is explicit and tested, whether the implementation stops immediately or continues through remaining commands.
- [ ] Tests use small subprocesses and temporary Target Repositories to verify command ordering, streaming log writes, passing commands, failing commands, and Task State status updates.

## Blocked by

- `.scratch/task-control-plane/issues/05-run-implementer-agent-from-approved-plan.md`
