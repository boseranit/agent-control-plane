<!--
Role: product requirements document for the research orchestrator reliability
and observability work.
Purpose: preserve the historical issues, desired behavior, and explicit scope
constraints that shaped the May 2026 orchestrator fixes.
Fit: complements the deterministic orchestration architecture note and the
research/orchestrator usage guide.
-->

# Research Orchestrator Reliability And Observability PRD

## Status

This PRD records the historical requirements behind the May 2026 research
orchestrator fixes. It is intentionally written as a requirements document, not
as proof that every item remains unimplemented. Current implementation details
live in:

- `research/orchestrator/README.md`
- `docs/architecture/deterministic-ai-orchestration-loop.md`
- `research/orchestrator/loop.py`
- `research/orchestrator/experiment_runner.py`
- `research/orchestrator/context.py`

## Summary

The research orchestrator must make each AI-assisted experiment inspectable,
comparable, and operationally reproducible. A user should be able to open MLflow
and the experiment worktree for a run such as `EXP-2026-05-26-1171` and answer:

- what the agents proposed, designed, selected, implemented, and ran
- whether the implementer changed files in the experiment worktree
- which commands executed, from which working directory, with which data root
- whether long prerequisite materializations such as cross-sectional sample
  backfills ran, failed, timed out, or were skipped
- what metrics, plots, tables, logs, and result notes were produced
- why the run was `completed_candidate`, `run_failed`, `completed_rejected`, or
  `no_op`
- what prior failures or completed prerequisites should guide the next cycle

The orchestrator should stay minimal. It should preserve per-experiment
worktrees for post-analysis, use deterministic Python for command execution, and
avoid turning agent outputs into a large rigid workflow engine.

## Background

The orchestrator coordinates research cycles under `research/`. Its core loop is
AI-assisted but deterministic around the edges:

- agents summarize context, propose research, design implementation, critique,
  select an experiment, implement in a worktree, summarize results, and update
  loop plans
- Python code creates run directories, ledgers, worktrees, command logs, and
  MLflow mirrors
- promoted runtime work still goes through `python -m pipeline --config ...`
  and must respect the repository artifact boundaries

Before the fixes that motivated this PRD, the user could see MLflow artifacts
made mostly of Markdown and JSON files, but could not reliably tell whether an
experiment actually did research work. Many runs were marked `no_op`, usage-limit
errors caused tight retry loops, command logs only appeared after subprocesses
exited, and worktree-relative paths could make shared data appear missing.

These failures made the loop hard to trust even when the individual agents were
reasonable. The product requirement is therefore not "make more agents". It is
"make the loop auditable enough that a researcher can inspect, compare, and
continue experiments without rediscovering the same blockers".

## Users

Primary user: the local researcher running repeated strategy-discovery cycles.

Needs:

- review experiment progress from MLflow without reading every run directory
- inspect strong candidates through their preserved worktrees
- understand whether blocked runs were truly blocked or only misconfigured
- avoid repeated proposals for prerequisites that already ran or are known
  blockers
- allow long operational materializations when they are necessary for research

Secondary user: future implementer or reviewer of the orchestrator.

Needs:

- understand why `no_op`, prerequisite stages, run directories, worktrees,
  command logs, and MLflow metrics exist
- avoid reintroducing hidden path assumptions or over-rigid contracts
- preserve the generic promoted runtime boundary

## Problem Statement

The old orchestrator could create many experiment folders while leaving the
researcher unable to answer basic experiment-audit questions:

1. MLflow was not a comparison surface.
   It mostly exposed raw Markdown and JSON artifacts. Metrics, command statuses,
   durations, and plots were not consistently logged in a way that supported
   side-by-side experiment comparison.

2. Run artifacts did not prove work happened.
   A run directory could contain context, proposal, design, critique, and
   selector files without showing whether the implementer edited code, ran the
   selected commands, produced metrics, or generated plots.

3. `no_op` was ambiguous.
   A high `no_op` count could mean sensible rejection by the selector, unresolved
   critique feedback, missing prerequisites, usage-limit failures, or an
   incomplete loop stage. The user needed explicit reasons, not just a terminal
   status.

4. Critique feedback could stop progress instead of causing revision.
   If the critic found fixable problems, the loop needed a revision or feedback
   implementation stage rather than simply ending the experiment.

5. Operational prerequisites were not first-class.
   The first experiment could recommend a cross-sectional samples backfill that
   should take about an hour and should unblock future research. The old loop did
   not make it obvious whether the command ran, why it did not run, or how later
   agents should remember the result.

6. Command execution used misleading paths.
   Commands selected for an experiment ran with `cwd` set to the experiment
   worktree. Relative paths such as `data/features` or
   `research/experiments/...` could resolve inside `.worktrees/...`. Since the
   ignored data directory is not present in each worktree, agents could conclude
   that data was missing when the canonical shared data existed elsewhere.

7. Shared data-root assumptions were not visible to all agents.
   The orchestration loop needed one canonical data root, configured once, with
   all agents and deterministic commands aware that `data_root=/mnt/redbackup/data`
   and `HLM_DATA_ROOT=/mnt/redbackup/data` are the shared source of data truth.

8. Usage-limit errors caused tight retries.
   When Codex returned messages like "You've hit your usage limit ... try again
   at 11:14 AM", the orchestrator could keep trying every few seconds. The loop
   needed to parse the retry time, sleep until the suggested time, and record the
   wait.

9. Long commands were opaque.
   Subprocess stdout and stderr were captured only after command exit. Long
   backfills needed live log streaming to files that MLflow could expose.

10. Runtime budgets were conceptual, not enforced.
    `max_runtime_minutes` existed as configuration but subprocesses did not have
    per-command timeouts, total-cycle control, or explicit long-backfill
    overrides.

11. Loop memory was too weak.
    Agents repeatedly rediscovered the same missing data, blockers, and proposed
    backfills. The next cycle needed a synthesis of recent completed, failed,
    and no-op runs.

12. Worktree reuse could hide stale state.
    Reusing an existing worktree with old untracked or modified files could make
    a new experiment inherit stale implementation details.

## Goals

1. Make every experiment auditable from both MLflow and local files.

2. Preserve one worktree per selected experiment so strong candidates can be
   inspected directly after the run.

3. Ensure `no_op` is an explainable state with selector reasons, rejected
   candidates, and enough context to decide whether it is healthy.

4. Add a feedback path after critique so fixable design feedback can be
   incorporated before selection and implementation.

5. Treat operational materializations as first-class prerequisites that can run
   before the implementer and be remembered by future cycles.

6. Execute selected commands deterministically with structured `argv`, absolute
   run paths, a configured data root, live logs, durations, statuses, and
   timeouts.

7. Make MLflow useful for comparing experiments by logging flattened metrics,
   command metrics, statuses, and run artifacts consistently.

8. Add prior-run synthesis to the context pack so agents know repeated blockers,
   completed prerequisites, best metrics, and next admissible actions.

9. Keep the orchestration minimal, inspectable, and compatible with agent
   discretion.

## Non-Goals

- Do not archive, remove, or aggressively clean experiment worktrees. Worktrees
  are part of the post-analysis workflow.
- Do not require saving a git diff as the primary inspection artifact. The
  worktree itself should remain available.
- Do not make tmux logs part of the primary user experience. The intended review
  surfaces are MLflow, run directories, and worktrees.
- Do not harden JSON contracts so much that agents lose discretion. Use simple
  structured command declarations and light result conventions.
- Do not add broad new validations merely because they are possible.
- Do not automatically merge, promote, or rewrite production artifacts based on
  an experiment result.
- Do not put strategy-specific orchestration or artifact registries into
  `artifact_runtime`.
- Do not rely on notebooks as orchestrated execution surfaces.

## Key Concepts

### Experiment Run

A run is one cycle under:

```text
research/experiments/<loop-id>/runs/<experiment-id>/
```

It should contain the full chain of agent outputs, command results, logs, and
final summaries needed to reconstruct what happened.

### Experiment Worktree

Each selected experiment gets an isolated worktree under:

```text
.worktrees/<loop-id>/<experiment-id>/
```

The worktree is the inspection surface for implementation edits. It should be
preserved unless the user explicitly cleans it up.

### No-Op

`no_op` means the cycle completed without running selected experiment commands.
It is acceptable when no experiment is admissible, but concerning when repeated
without clear blocker synthesis or when caused by fixable critique feedback.

### Prerequisite Command

A prerequisite command is an operational materialization needed before the
implementer can do meaningful work. Examples include promoted runtime backfills
that produce missing cross-sectional samples or feature groups.

Prerequisites are not research conclusions by themselves. They unblock later
experiments and should be recorded as loop memory.

### Canonical Data Root

All orchestration agents and commands must treat the configured data root as the
shared artifact location. The default is:

```text
/mnt/redbackup/data
```

Commands should receive:

```text
HLM_DATA_ROOT=/mnt/redbackup/data
ORCHESTRATOR_RUN_DIR=<current run directory>
ORCHESTRATOR_REPO_ROOT=<main checkout>
```

Worktree-relative `data/...` paths are noncanonical.

## Functional Requirements

### 1. Experiment Auditability

Every run must allow post-hoc answers to these questions:

- Which loop spec, budget, data root, git SHA, and run ID were used?
- Which context did each agent receive?
- What did proposal, production design, critique, selector, implementer, result
  summarizer, and plan updater produce?
- Did the selector choose an experiment?
- Did a worktree get created or reused?
- Which commands ran, with which `argv`, `cwd`, timeout, exit code, and duration?
- Which stdout and stderr logs belong to prerequisites and selected commands?
- Which metrics and artifacts were produced?
- If the run did not produce metrics, was that visible in the result summary?
- If the run failed or no-op'd, what was the specific blocker?

The run directory is the authoritative local audit trail. MLflow is the primary
comparison and browsing surface.

### 2. MLflow Comparison Surface

MLflow should mirror enough structured information to compare experiments
without opening local files first.

Required MLflow parameters:

- `cycle_id`
- `loop_id`
- `loop_spec_path`
- `budget`

Required MLflow tags when available:

- cycle status
- experiment status
- experiment outcome
- error type for failed cycles

Required MLflow metrics:

- flattened numeric leaves from `metrics.json`
- flattened numeric metric payloads in `experiment_result.json`
- command count
- command failure count
- command duration seconds
- command exit code
- command pass flag
- command timeout seconds when configured

Required MLflow artifacts:

- `cycle.json`
- `context_pack.md`
- context files created for agent dependencies
- `proposal.json`
- `production_design.json`
- `critique.json`
- revised design output when present
- `selected_plan.json`
- `implementation.json`
- `prerequisite_result.json` when present
- `experiment_result.json`
- `summary.json`
- `plan_update.json`
- `codex-events.jsonl`
- stdout and stderr logs
- `metrics.json`, `command_metrics.json`, and optional result reports, plots, or
  tables when produced in the run directory

MLflow tracing is optional. The requirement is useful experiment comparison, not
full tracing infrastructure.

### 3. Output Contract

The orchestrator should use a simple output convention:

- deterministic runner always writes `experiment_result.json`
- command metrics are written to `command_metrics.json`
- experiment code should write `metrics.json` into `$ORCHESTRATOR_RUN_DIR`
- experiment code may write `result.md`, plots, and tables under
  `$ORCHESTRATOR_RUN_DIR`
- selected commands should not write primary outputs to arbitrary relative paths

The original desired direction was to fail cycles when selected commands exited
zero but produced no metrics or result artifact. The scoped requirement is
lighter: lack of metrics or result artifacts must be visible to summarizer,
MLflow, and the user. A stricter fail-fast gate can be added later if repeated
empty successes remain a real problem.

The runner must not treat "process exited 0" as sufficient evidence of research
success when the metrics or result notes say the experiment was blocked,
rejected, or incomplete. The result summarizer should be able to mark such runs
as rejected or inconclusive.

### 4. No-Op Semantics

A no-op cycle is valid only when the selector chooses no experiment or when no
deterministic commands are available to run.

Requirements:

- record `selected: []` in `selected_plan.json`
- record rejected candidates and reasons when known
- finish the cycle consistently so MLflow and the ledger show it
- include no-op counts and reasons in prior-run synthesis
- distinguish healthy no-op from repeated blocked no-op

Repeated no-ops are concerning when they share the same blocker, when the critic
keeps asking for fixable changes, or when an operational prerequisite is needed
but never run.

### 5. Critique Feedback Loop

If the experiment critic provides required revisions or recommends `revise`, the
loop should revise the production design before selection.

Requirements:

- preserve the original critique
- run a design revision stage that sees proposal, original design, critique, and
  context
- make the revised production design the one consumed by selector and
  prerequisite execution
- avoid treating fixable critique feedback as an automatic no-op

This revision stage is intentionally narrow. It updates the design; it does not
create a full multi-iteration autonomous project manager.

### 6. Prerequisite Execution

The production design may declare prerequisite commands that must run before the
implementer. Runtime backfills that materialize required artifacts are the
canonical example.

Requirements:

- production design can emit typed command objects for prerequisites
- commands use `argv`, not shell strings
- controller runs prerequisites from the main checkout, not the experiment
  worktree
- prerequisite stdout and stderr stream to dedicated log files
- prerequisite result is written before implementer starts
- prerequisite result is included in implementer context
- prerequisite commands can declare command-specific timeouts for long backfills
- failed prerequisites skip implementation but still produce a summarized cycle
- passed prerequisites are captured in prior-run synthesis

The selector should not be the only authority on whether an operational backfill
is allowed. If a backfill is required to make research possible, the production
design should declare it as a prerequisite or revise the approach so the
research remains admissible.

### 7. Cross-Sectional Samples Backfill Case

The historical motivating case was a recommended cross-sectional samples
backfill. The user expected it could take about an hour and could be necessary
for future experiments.

Requirements:

- if the loop identifies missing cross-sectional sample artifacts as a blocker,
  the design should be able to declare a promoted runtime backfill prerequisite
- the orchestrator should run it with an explicit long timeout or budget override
- logs should stream live while the backfill runs
- completion should be recorded as loop memory, for example "cross-sectional
  samples backfill completed"
- future agents should see the completed prerequisite and stop rediscovering it
  as an unresolved blocker
- if it did not run, the run artifacts should explain why: not selected, rejected
  by deterministic guard, command failed, timed out, usage-limited before the
  stage, or missing command declaration

### 8. Command Runner

The deterministic runner is responsible for executing commands selected by the
orchestration loop.

Requirements:

- accept structured command objects with `argv`
- reject shell strings for selected commands
- execute commands with `shell=False`
- set `ORCHESTRATOR_RUN_DIR`
- set `HLM_DATA_ROOT`
- set `ORCHESTRATOR_REPO_ROOT`
- stream stdout and stderr to files while the process runs
- write command headers showing command and `cwd`
- record exit code, duration, timeout, status, stdout path, and stderr path
- terminate the process group on timeout
- write command metrics for MLflow
- preserve simple command declarations so agents can still exercise discretion

The runner should remain deterministic Python. Agents may recommend commands,
but they should not be responsible for manual process supervision.

### 9. Post-Implementation Result Analysis

The loop needs a stage after implementation that turns command execution into
research evidence.

Requirements:

- run commands recommended by the selected plan or implementer through the
  deterministic runner
- collect command statuses, stdout/stderr paths, metrics, artifacts, and
  timings
- analyze whether a zero-exit command actually produced useful research
  evidence
- write notes that explain the experiment result in research terms
- distinguish code/runtime failures from rejected hypotheses and missing
  prerequisites
- expose enough information for the plan updater to choose the next action

The historical request allowed for an additional agent that could fix code and
rerun commands when necessary. The minimal scope is more conservative: record
the failure clearly and let the next cycle use prior-run synthesis, unless a
future repair stage is explicitly added. Avoid unbounded fix-rerun loops.

### 10. Working Directory And Data Root Rules

Prerequisite commands run from the main repository checkout.

Selected experiment commands may run from the experiment worktree, but all data
access must use the configured data root, not worktree-local `data/...`.

Requirements:

- context pack states canonical data root and `HLM_DATA_ROOT`
- runner injects `HLM_DATA_ROOT`
- runner injects `ORCHESTRATOR_REPO_ROOT`
- agents are told that worktree-relative data paths are noncanonical
- artifact surface checks resolve logical `data/...` paths under the configured
  data root

This prevents false missing-data conclusions when ignored data is absent from
`.worktrees/...`.

### 11. Live Command Logging

Long-running commands must be inspectable before they exit.

Requirements:

- stdout and stderr stream to run-directory log files during command execution
- prerequisite logs use separate files from selected command logs
- MLflow mirrors those log files as artifacts after the cycle is mirrored
- command timeout messages are appended to stderr

The primary live progress surface while the controller runs can remain CLI
stderr. The persistent review surface is the run directory and MLflow.

### 12. Runtime Budgets And Timeouts

Budgets should be explicit operational constraints, not only planning hints.

Requirements:

- budget `max_runtime_minutes` provides a default command timeout
- individual command objects may override with `timeout_seconds` or
  `timeout_minutes`
- long prerequisite backfills can declare longer timeouts intentionally
- timeout status is captured in command results and MLflow metrics
- timed-out commands fail the run or prerequisite stage clearly

Total-cycle timeout can be added later if command-level timeouts are not enough.

### 13. Usage-Limit Backoff

The Codex invocation layer must handle usage-limit messages with suggested retry
times.

Requirements:

- detect usage-limit errors that include "try again at <time>"
- compute the local retry delay
- sleep until that time rather than retrying every few seconds
- record a `usage_limit` event in `codex-events.jsonl`
- retry at most once per agent turn before surfacing the error

This makes repeated loop execution compatible with temporary service limits
without creating noisy failed run directories.

### 14. Prior-Run Synthesis

Before proposing new work, the context pack should summarize recent loop
history.

Requirements:

- read multiple recent completed, no-op, and failed runs for the same loop
- summarize recent cycle status counts
- summarize repeated blockers
- summarize completed prerequisites
- summarize metric-bearing runs and useful metric keys
- include failed-run summaries
- feed the synthesis into context summary, proposal, design, and selection

The synthesis should be bounded and compact. It is memory for the loop, not an
unbounded transcript archive.

### 15. Worktree Policy

The orchestrator should continue to create one worktree per selected experiment.

Requirements:

- worktree path is loop-scoped and experiment-scoped
- branch names are loop-qualified
- worktrees are preserved for post-analysis
- if a worktree already exists, only reuse it when `git status --porcelain` is
  clean
- if the existing worktree is dirty, fail the cycle rather than silently reusing
  stale state

This is the minimal fix for stale worktree reuse. No automatic archive or
cleanup flow is required.

### 16. Agent Visibility

The implementer must see prerequisite results before editing code.

The result summarizer must see:

- selected plan
- implementation output
- prerequisite result
- deterministic command result
- command logs by path
- metrics and artifact lists

The plan updater must see:

- proposal
- final summary
- experiment result
- prior-run context through the original context pack

This preserves the simple stage structure while letting each agent make better
decisions.

## UX Requirements

### MLflow Review

The researcher should be able to open one MLflow experiment and:

- sort or filter runs by status
- compare key metrics across experiments
- identify failed/no-op/completed cycles
- open command logs as artifacts
- find the run directory and worktree identifiers
- distinguish a research result from an operational prerequisite

### Local Review

The researcher should be able to inspect:

- `research/experiments/<loop-id>/runs/<experiment-id>/`
- `.worktrees/<loop-id>/<experiment-id>/`

These two surfaces should be enough to reconstruct the experiment without tmux
logs or hidden state.

## Success Metrics

The orchestrator work is successful when:

- a named run such as `EXP-2026-05-26-1171` can be audited from MLflow and local
  files
- a high no-op count can be explained by explicit selector and blocker reasons
- repeated no-ops decline when caused by missing prerequisite memory
- operational backfills appear as prerequisite commands with logs, durations,
  statuses, and later memory
- MLflow metrics include experiment metrics and command metrics
- long commands show live-growing log files
- usage-limit messages cause scheduled waits rather than tight retries
- false "missing data" conclusions from worktree-relative paths disappear
- stale dirty worktrees are not silently reused

## Acceptance Criteria

1. A completed cycle writes the expected run files, command logs, and
   `experiment_result.json`.

2. A no-op cycle writes `selected_plan.json`, records no selected experiment,
   gives rejected reasons when available, mirrors to MLflow, and appears in
   prior-run synthesis.

3. A production design with a prerequisite runtime backfill runs that command
   from the main checkout before implementer execution.

4. The implementer context includes `prerequisite_result.json` and its stdout
   and stderr log paths.

5. Selected commands run with `ORCHESTRATOR_RUN_DIR`, `HLM_DATA_ROOT`, and
   `ORCHESTRATOR_REPO_ROOT` set.

6. Command stdout and stderr are visible in log files while the command is still
   running.

7. Command duration, exit code, pass flag, failure count, and timeout values are
   logged to MLflow as metrics.

8. Numeric experiment metrics from `metrics.json` are flattened into MLflow
   metrics.

9. A usage-limit error with a suggested retry time creates a
   `codex-events.jsonl` entry and waits until the suggested time before retrying.

10. Existing dirty worktrees are rejected instead of reused.

11. The context pack includes the canonical data root and artifact surface
    presence checks resolved under that root.

12. Prior-run synthesis includes recent statuses, repeated blockers, completed
    prerequisites, and metric hints.

## Implementation Constraints

- Prefer small, local changes to `research/orchestrator/*`.
- Keep `artifact_runtime` generic.
- Preserve the promoted runtime entrypoint for actual artifact backfills.
- Keep schemas permissive enough for agent discretion.
- Keep the single-experiment path reliable before adding parallel workers.
- Do not introduce a separate orchestration database while JSON files, JSONL
  ledger, MLflow, and worktrees are sufficient.
- Avoid hidden warmup ticks or noncanonical data paths.

## Deferred Work

- strict failure when commands exit zero but produce no metrics or result report
- total-cycle timeout beyond per-command timeout
- richer MLflow plot/table conventions beyond copying run-directory artifacts
- parallel selected experiments
- automatic cleanup or archival of stale worktrees
- full MLflow tracing
- automated promotion of successful candidates

## Critical User Decisions To Confirm

The following decisions are intentionally called out for user confirmation.
They are product choices, not mechanical implementation details.

1. Empty successful commands.
   Recommended default: keep the current minimal behavior where missing metrics
   or result artifacts are surfaced clearly but do not automatically fail the
   cycle.

   Decision needed: should a selected experiment that exits zero but writes no
   `metrics.json`, `result.md`, plot, or table become `completed_candidate`,
   `completed_rejected`, `completed_inconclusive`, or `run_failed`?

2. Durable prerequisite memory.
   Recommended default: use bounded prior-run synthesis before adding another
   state file.

   Decision needed: should completed operational prerequisites such as
   "cross-sectional samples backfill completed" be stored only in prior-run
   synthesis, or also in a durable loop memory file that agents read every
   cycle?

3. Repair-and-rerun scope.
   Recommended default: avoid an automatic fix-rerun loop for now; summarize
   failures and let the next cycle decide.

   Decision needed: should the post-run stage ever allow an agent to patch code
   and rerun failed commands inside the same cycle, or should all repairs happen
   in the next cycle?

4. Plot and table convention.
   Recommended default: keep copying all run-directory files to MLflow while
   encouraging experiment code to write outputs under `$ORCHESTRATOR_RUN_DIR`.

   Decision needed: should the orchestrator require a standard
   `$ORCHESTRATOR_RUN_DIR/artifacts/` directory for plots and tables, or keep the
   looser run-directory convention?

5. Long prerequisite budgets.
   Recommended default: allow command-level `timeout_minutes` for long
   prerequisites without creating new budget classes.

   Decision needed: should long operational backfills use explicit per-command
   overrides, or should the orchestrator define named budget classes for
   prerequisite materializations?

6. Command allowlist strictness.
   Recommended default: keep the allowlist narrow for pre-implementation
   runtime backfills and keep selected experiment commands simple `argv` objects.

   Decision needed: should prerequisite execution remain limited to promoted
   runtime backfills, or should the design be allowed to declare other
   operational materialization commands?

7. Canonical data-root configurability.
   Recommended default: keep `/mnt/redbackup/data` as the configured default in
   `research/params.yaml`, expose it through `HLM_DATA_ROOT`, and avoid
   worktree-local data paths.

   Decision needed: should any loop be allowed to override the data root, or
   should orchestration treat one shared data root as a hard repository-level
   invariant?

## Additional Open Questions

1. Which experiment metrics should be considered first-class for each loop
   family, rather than merely flattened generically?

2. Should future MLflow work add traces, or are flattened metrics, tags, logs,
   artifacts, and preserved worktrees enough for the intended review workflow?
