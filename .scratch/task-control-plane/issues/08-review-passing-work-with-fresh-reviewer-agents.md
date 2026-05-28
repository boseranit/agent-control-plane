# Review Passing Work with Fresh Reviewer Agents

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add the review phase for passing test results. When deterministic tests pass, the Controller should create a fresh Reviewer Agent thread for that review attempt, pass artifact paths rather than embedded diffs/logs, write the review output to an append-only review log, and treat `status: approved` as commit-ready.

This slice establishes the independent review boundary and reviewer output semantics.

## Acceptance criteria

- [ ] The workflow has a source-controlled Reviewer Agent prompt and reviewer output schema.
- [ ] The Reviewer Agent runs with the Target Repository as its working directory.
- [ ] The Reviewer Agent defaults to `deny_all` approval mode and read-only sandbox.
- [ ] The Controller creates a fresh Reviewer Agent thread for each review attempt.
- [ ] Reviewer Agent thread IDs are not reused as persistent Task role threads.
- [ ] The reviewer turn input includes the Task, task context path, Approved Plan path, command log path, and review log path.
- [ ] The reviewer turn input does not embed a precomputed diff packet by default.
- [ ] The reviewer prompt states that `approved` means the Controller will commit all current Target Repository changes for the Task.
- [ ] The reviewer prompt states that non-blocking issues do not prevent commit.
- [ ] The Controller calls the reviewer turn with SDK `output_schema`.
- [ ] The Controller appends each review output to the Task review log.
- [ ] A review output with `status: approved` advances the Task to commit-ready.
- [ ] A review output with non-blocking issues and `status: approved` still advances the Task to commit-ready.
- [ ] Tests verify fresh reviewer thread creation, role configuration, input construction, output schema usage, review log append behavior, approved routing, and non-blocking issue semantics.

## Blocked by

- `.scratch/task-control-plane/issues/06-execute-test-commands-with-streaming-command-log.md`

## Comments

### Implementation

- Commit: `1a1c84ddb90aa53c746ef37896254ade7ecde226`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added the Reviewer Agent prompt and schema, fresh reviewer thread creation with `deny_all` and read-only sandbox, reviewer turn input with artifact paths and no embedded diff, SDK `output_schema` usage, JSONL review log appends, passing-test guard, and `commit_ready` routing for approved reviews including advisory non-blocking issues. The schema/prompt also include `requested_changes` for the upcoming rejection loop.
