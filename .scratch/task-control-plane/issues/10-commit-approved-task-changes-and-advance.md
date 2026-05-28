# Commit Approved Task Changes and Advance Sequentially

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Finish the per-Task happy path. Once latest deterministic tests have passed and the Reviewer Agent returns `approved`, the Controller should commit all current non-ignored Target Repository changes with a Task ID/title commit message, record the commit SHA, mark the Task complete, and move to the next Task only after enforcing the new-task cleanliness rule.

This slice should make one Task equal one final commit.

## Acceptance criteria

- [ ] The Controller commits only after latest deterministic tests passed and the Reviewer Agent returned `approved`.
- [ ] The Controller does not run another test command after reviewer approval in v1.
- [ ] The Controller does not perform a post-review drift check in v1.
- [ ] The commit operation stages all current non-ignored Target Repository changes.
- [ ] The commit operation includes tracked modifications and untracked non-ignored files.
- [ ] Ignored files are not committed.
- [ ] The commit message begins with the Task ID and task title.
- [ ] The commit SHA is recorded in Task State.
- [ ] The Task is marked completed after commit.
- [ ] The Controller proceeds to the next Task only after the previous Task is completed.
- [ ] The Controller enforces Target Repository cleanliness before starting the next Task.
- [ ] The Controller does not create branches, worktrees, pushes, pull requests, or automatic reverts.
- [ ] Tests use temporary git repositories to verify commit-all behavior, ignored file behavior, commit message format, commit SHA recording, sequential Task advancement, and cleanliness enforcement.

## Blocked by

- `.scratch/task-control-plane/issues/08-review-passing-work-with-fresh-reviewer-agents.md`
- `.scratch/task-control-plane/issues/09-route-reviewer-rejection-verbatim-to-implementer.md`

## Comments

### Implementation

- Commit: `a5bb1d7f883547e8d37ea9658624de5160582887`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added `commit_active_task_and_advance(...)` for the final per-Task happy path. The controller now commits only from `commit_ready` after latest passing tests and reviewer approval, stages all non-ignored Target Repository changes, records the commit SHA, marks the Task completed, marks the run completed when no Tasks remain, and activates the next Task only after enforcing Target Repository cleanliness. Commit messages use `Task ID: title`. No post-review test rerun, drift check, branch/worktree creation, push, PR, or revert behavior was added.
