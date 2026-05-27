# Resume a Task Run from Controller-Owned Task State

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add the explicit resume path. The `resume` CLI should load an existing Task Run by run ID, read the snapshotted Task Spec and Controller-owned Task State, resume any persistent Planner, Context, or Implementer Agent threads by saved thread ID, allow dirty Target Repository state only for the active Task, and continue from the recorded phase.

Resume must not accept a replacement Task Spec path.

## Acceptance criteria

- [ ] The CLI exposes a `resume` command that requires a Task Run ID.
- [ ] `resume` loads the snapshotted Task Spec from the Task Run.
- [ ] `resume` loads Controller-owned Task State from the Task Run.
- [ ] `resume` does not accept or require a new Task Spec path.
- [ ] `resume` restores the active Task and current phase from Task State.
- [ ] `resume` allows dirty Target Repository state only when resuming the active Task.
- [ ] `resume` still requires cleanliness before starting any new Task.
- [ ] Persistent Planner Agent, Context Agent, and Implementer Agent threads are resumed from saved thread IDs when needed.
- [ ] Fresh Reviewer Agent behavior remains fresh after resume.
- [ ] Completed Tasks are not rerun.
- [ ] A Task Run can resume from at least planning, approved-plan, implementation, failed-test retry, review-rejection retry, and next-task phases.
- [ ] Tests use fake Codex clients and temporary Target Repositories to verify phase-specific resume behavior, thread resumption, dirty active Task handling, and no replacement Task Spec.

## Blocked by

- `.scratch/task-control-plane/issues/01-bootstrap-task-run-from-task-spec.md`
- `.scratch/task-control-plane/issues/02-plan-task-with-persistent-planner-agent.md`
- `.scratch/task-control-plane/issues/05-run-implementer-agent-from-approved-plan.md`
- `.scratch/task-control-plane/issues/10-commit-approved-task-changes-and-advance.md`

## Comments

### Implementation

- Commit: `38706fc2a90d287be3abd39dbd2012e73a21e45f`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added `resume_task_run(...)` and CLI `resume RUN_ID`. Resume loads the snapshotted Task Spec and Controller-owned Task State, routes from saved phases through existing controller steps, resumes saved Planner/Context/Implementer thread IDs when needed, keeps Reviewer Agent threads fresh, skips completed Tasks, permits dirty active implementation state while still enforcing cleanliness before starting the next Task, and rejects replacement Task Spec arguments at the CLI. Usage-limit handling remains out of scope for issue 12.
