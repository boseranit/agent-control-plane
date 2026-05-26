# Sleep Through Codex Usage Limits and Continue

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Wrap Codex role calls with usage-limit handling. When a Codex call fails with a usage-limit message that includes a suggested retry time, the Controller should parse that time, record the wait, sleep until the suggested time, and retry the same call automatically. It should not retry every few seconds.

The sleep behavior must be injectable in tests so tests do not wait for real time.

## Acceptance criteria

- [ ] All Planner Agent, Context Agent, Implementer Agent, and Reviewer Agent turns go through a shared usage-limit wrapper.
- [ ] Representative usage-limit messages with suggested retry times are parsed.
- [ ] Suggested retry times are interpreted relative to the local runtime context.
- [ ] Computed sleep durations are never negative.
- [ ] The Controller records usage-limit waits in Task State, command output, or another inspectable runtime log.
- [ ] The Controller sleeps until the suggested retry time rather than retrying every few seconds.
- [ ] After sleeping, the Controller retries the same Codex call and continues the workflow.
- [ ] Non-usage-limit errors propagate normally.
- [ ] The sleep and clock behavior are injectable in tests.
- [ ] Tests cover message parsing, sleep duration calculation, retry-after-sleep behavior, no busy retry loop, and non-usage error propagation.

## Blocked by

- `.scratch/task-control-plane/issues/02-plan-task-with-persistent-planner-agent.md`
