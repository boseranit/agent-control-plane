# Bootstrap a Task Run from a Task Spec

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Build the first runnable slice of the Task Control Plane: a user can invoke the CLI with an explicit Task Spec path and get a new Task Run with a snapshotted spec, Controller-owned state, compact first-task context, and clean Target Repository enforcement.

This slice should establish the core runtime shape without real Codex calls. It should make the Task Spec, Task Run, Task State, Target Repository cleanliness check, runtime root, and first task artifact layout real enough that later agent slices can plug into it.

## Acceptance criteria

- [ ] The CLI exposes a `run` command that requires an explicit Task Spec path.
- [ ] The Task Spec loader accepts a Target Repository, optional run description/context, run-level Codex model and effort, optional plan approval setting, maximum iteration setting, named argv test commands, and an ordered Task list.
- [ ] Each Task must have an explicit unique Task ID, title, prompt, and optional task context.
- [ ] Sensible defaults are applied, including plan approval enabled by default and `max_iterations` defaulting to 10.
- [ ] Unsupported v1 fields such as environment variables, target branch metadata, service tier, dependency graphs, and shell-string test commands are rejected or clearly ignored according to the implementation's documented policy.
- [ ] Starting a Task Run snapshots the Task Spec into the run directory as the immutable run input.
- [ ] Starting a Task Run writes Controller-owned Task State with run ID, active task information, phase, and initial per-task state.
- [ ] Runtime artifacts are written under top-level `runs/`, and `runs/` is ignored by git.
- [ ] The first task gets a compact task context artifact containing minimal controller-known facts and absolute artifact paths.
- [ ] The Target Repository must be clean before starting the first Task.
- [ ] No Codex agent thread is started in this slice.
- [ ] Tests cover valid Task Spec loading, defaulting, duplicate Task IDs, invalid command shapes, Task Run creation, spec snapshotting, state creation, context artifact creation, and dirty Target Repository refusal.

## Blocked by

None - can start immediately
