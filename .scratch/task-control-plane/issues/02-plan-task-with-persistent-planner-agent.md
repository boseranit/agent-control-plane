# Plan a Task with a Persistent Planner Agent

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add the first real Codex role integration: the Controller can create or resume a persistent Planner Agent thread for the active Task, pass role behavior as developer instructions, call the SDK with an output schema, persist the thread ID, and record a planned output in the planning artifact.

This slice should use fake Codex clients in tests and avoid real network calls. The point is to make the role gateway and planning artifact contract work end-to-end.

## Acceptance criteria

- [ ] The workflow has a source-controlled Planner Agent prompt and planner output schema.
- [ ] Planner role behavior is supplied as SDK developer instructions when starting or resuming the thread.
- [ ] The Planner Agent runs with the Target Repository as its working directory.
- [ ] The Planner Agent defaults to `auto_review` approval mode and read-only sandbox.
- [ ] The Controller starts a Planner Agent thread when no planner thread ID exists for the active Task.
- [ ] The Controller resumes the Planner Agent thread when a planner thread ID already exists.
- [ ] The Controller persists the returned Planner Agent thread ID in Task State.
- [ ] The Controller calls the planner turn with SDK `output_schema`.
- [ ] The Controller records planner outputs in a planning artifact as an array of planner outputs.
- [ ] A planner output with `status: planned` and `plan_markdown` advances the Task State to the plan-ready phase.
- [ ] Minimal routing checks reject unparseable planner output and unknown planner statuses.
- [ ] Tests use a fake Codex client and fake thread to verify start, resume, developer instructions, working directory, role configuration, output schema usage, thread ID persistence, and planning artifact writes.

## Blocked by

- `.scratch/task-control-plane/issues/01-bootstrap-task-run-from-task-spec.md`

## Comments

### Implementation

- Commit: `a1253ce4af28d333525513277f3a8c250c5f5200`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
- Notes: Added the source-controlled Planner Agent prompt and planner output schema, plus a fake-tested Planner Agent gateway that starts or resumes the persistent planner thread, passes SDK developer instructions and `output_schema`, persists the planner thread ID, records planner outputs in `planning.json`, and advances to `plan_ready` or `planning_needs_answers`. Real Codex network calls remain untested by design.
