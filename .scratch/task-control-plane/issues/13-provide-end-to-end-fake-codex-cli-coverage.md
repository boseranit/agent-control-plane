# Provide End-to-End Fake-Codex CLI Coverage

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Add end-to-end regression coverage for the Task Control Plane using fake Codex threads and temporary Target Repositories. The goal is to prove the full CLI-level workflow can run without network access: Task Spec loading, Task Run creation, planning, optional question answering, approval, implementation, deterministic tests, review approval/rejection, commits, failure handling, and resume.

This issue should not add new product behavior. It should harden the already-built workflow with integration-style tests that exercise the real Controller surfaces.

## Acceptance criteria

- [ ] A fake Codex client can drive the CLI-level workflow without real network calls.
- [ ] A happy-path test starts a Task Run, plans, auto-approves, implements, passes tests, receives reviewer approval, commits Target Repository changes, and records completion.
- [ ] A planner-question test exercises Planner Agent `needs_answers`, Context Agent answers, human unresolved answers, planner follow-up, and plan approval.
- [ ] A failed-test test verifies failed tests bypass review and return to the same Implementer Agent.
- [ ] A reviewer-rejection test verifies fresh reviewer rejection, verbatim feedback to the Implementer Agent, test rerun, later approval, and commit.
- [ ] A multi-task test verifies the Controller commits one Task before starting the next Task.
- [ ] A resume test verifies a stopped Task Run continues from saved Task State without rerunning completed phases.
- [ ] A max-iterations test verifies failure stops the run and leaves the Target Repository dirty.
- [ ] A usage-limit test verifies the injectable sleeper path at the Controller level.
- [ ] Tests assert important artifact files are created and compact rather than asserting private implementation details.
- [ ] Tests do not require MLflow, real Codex, real editors, real usage-limit sleeps, or network access.
- [ ] The project test command passes through Pixi.

## Blocked by

- `.scratch/task-control-plane/issues/01-bootstrap-task-run-from-task-spec.md`
- `.scratch/task-control-plane/issues/02-plan-task-with-persistent-planner-agent.md`
- `.scratch/task-control-plane/issues/03-resolve-planner-questions-with-context-agent.md`
- `.scratch/task-control-plane/issues/04-approve-plans-through-approved-plan-markdown.md`
- `.scratch/task-control-plane/issues/05-run-implementer-agent-from-approved-plan.md`
- `.scratch/task-control-plane/issues/06-execute-test-commands-with-streaming-command-log.md`
- `.scratch/task-control-plane/issues/07-feed-failed-tests-back-to-implementer.md`
- `.scratch/task-control-plane/issues/08-review-passing-work-with-fresh-reviewer-agents.md`
- `.scratch/task-control-plane/issues/09-route-reviewer-rejection-verbatim-to-implementer.md`
- `.scratch/task-control-plane/issues/10-commit-approved-task-changes-and-advance.md`
- `.scratch/task-control-plane/issues/11-resume-task-run-from-task-state.md`
- `.scratch/task-control-plane/issues/12-sleep-through-codex-usage-limits.md`
