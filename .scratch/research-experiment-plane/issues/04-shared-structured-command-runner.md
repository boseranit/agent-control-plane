# Shared structured command runner

Status: completed
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add a shared argv-only command runner with `shell=False`, required cwd, env overlays, live stdout/stderr logs, timeouts, process-group termination, structured results, and command metrics.

## Acceptance criteria

- [x] Shell strings are rejected; argv command records are deterministic.
- [x] Logs stream while commands run and persist after completion/failure.
- [x] Timeout handling terminates the process group and records timeout metrics.
- [x] Tests cover cwd, env overlay, exit codes, logs, metrics, and timeout behavior.

## Blocked by

None - can start immediately

## Comments

- Added shared structured command runner.
- Verified with `pixi run test` (`109 passed`).
