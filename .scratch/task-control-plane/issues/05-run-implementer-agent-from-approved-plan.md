# Run an Implementer Agent Turn from an Approved Plan

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add the implementation phase. The Controller should create or resume a persistent Implementer Agent thread for the active Task, pass role behavior as developer instructions, send only the Task, task context path, and Approved Plan path, and write the latest implementation result artifact.

This slice stops after a single Implementer Agent turn. Test execution and review come later.

## Acceptance criteria

- [ ] The workflow has a source-controlled Implementer Agent prompt and implementer result output schema.
- [ ] The Implementer Agent runs with the Target Repository as its working directory.
- [ ] The Implementer Agent defaults to `auto_review` approval mode and workspace-write sandbox.
- [ ] The Controller starts an Implementer Agent thread when no implementer thread ID exists for the active Task.
- [ ] The Controller resumes the Implementer Agent thread when an implementer thread ID already exists.
- [ ] The Controller persists the returned Implementer Agent thread ID in Task State.
- [ ] The Controller calls the implementer turn with SDK `output_schema`.
- [ ] The implementer turn input includes the Task, task context path, and Approved Plan path.
- [ ] The implementer turn input does not include raw planner drafts by default.
- [ ] The Controller writes the latest implementer result to the Task implementation artifact, overwriting prior snapshots.
- [ ] Task State advances from approved-plan to implementation-complete or ready-for-tests according to the state model.
- [ ] Tests verify role configuration, developer instructions, thread start/resume, output schema usage, input construction, artifact write behavior, and thread ID persistence.

## Blocked by

- `.scratch/task-control-plane/issues/04-approve-plans-through-approved-plan-markdown.md`

## Comments

### Implementation

- Commit: `f1cd6ad6d93da5b1499e8071aa846ee7a039cb3f`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added the source-controlled Implementer Agent prompt and result schema, persistent implementer thread start/resume with workspace-write sandbox and `auto_review`, SDK `output_schema` use, implementer thread ID persistence, approved-plan-only turn input, latest implementation result overwrite, and `ready_for_tests` state transition. Deterministic tests, retries, review, and commit behavior remain out of scope for later issues.
