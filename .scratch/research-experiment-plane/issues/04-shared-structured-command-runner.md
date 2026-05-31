# Shared structured command runner

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add a shared argv-only command runner with `shell=False`, required cwd, env overlays, live stdout/stderr logs, timeouts, process-group termination, structured results, and command metrics.

## Acceptance criteria

- [ ] Shell strings are rejected; argv command records are deterministic.
- [ ] Logs stream while commands run and persist after completion/failure.
- [ ] Timeout handling terminates the process group and records timeout metrics.
- [ ] Tests cover cwd, env overlay, exit codes, logs, metrics, and timeout behavior.

## Blocked by

None - can start immediately

