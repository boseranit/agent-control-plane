# Resolve Planner Questions with Context Agent and Human Answers

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Extend planning so a Planner Agent can return structured questions, the Controller can route those questions to a persistent Context Agent, unresolved questions can be batched for human answers, and the Planner Agent can be called again with the latest answers until it returns a plan.

This slice should make the planning loop deterministic while preserving the user's preference for minimal prompt payloads and compact artifacts.

## Acceptance criteria

- [ ] The workflow has a source-controlled Context Agent prompt and context answers output schema.
- [ ] A planner output with `status: needs_answers` is recorded and causes the Controller to enter the question-answer loop.
- [ ] The Context Agent runs with the Target Repository as its working directory.
- [ ] The Context Agent defaults to `auto_review` approval mode and read-only sandbox.
- [ ] The Controller starts or resumes one persistent Context Agent thread for the Task.
- [ ] The Controller persists the Context Agent thread ID in Task State.
- [ ] The Controller sends planner questions, context artifact path, and planning artifact path to the Context Agent.
- [ ] Context Agent answers are recorded in the planning artifact.
- [ ] Context Agent output can mark questions as answered or unresolved, with a reason string.
- [ ] Unresolved questions are batched through an injectable human-answer provider.
- [ ] Human answers are recorded in the same planning artifact as Context Agent answers.
- [ ] The Controller sends the latest answers back to the same Planner Agent thread.
- [ ] The planning loop supports multiple question-answer rounds before `status: planned`.
- [ ] Tests cover fully answered questions, partially unresolved questions requiring human input, multiple planner follow-up rounds, answer recording, Context Agent thread persistence, and malformed routing output.

## Blocked by

- `.scratch/task-control-plane/issues/02-plan-task-with-persistent-planner-agent.md`

## Comments

### Implementation

- Commit: `3e2cab960f5722334b9552bb4956b17c525e8022`
- Tests run:
  - `pixi run -e dev ruff check .`
  - `pixi run -e dev pytest`
  - `git diff --check`
- Notes: Added the source-controlled Context Agent prompt and context answers schema, persistent Context Agent thread start/resume, answer-history recording in `planning.json`, injectable human answer handling for unresolved planner questions, and a multi-round planning loop that keeps using the same Planner Agent thread until it returns `planned`. Real Codex calls remain covered by fakes only.
