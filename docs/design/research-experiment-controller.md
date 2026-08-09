# Research Experiment Controller Design Spec

## Purpose

This document describes an equivalent architecture for the Research Experiment
Controller. It is intended for a software engineer recreating the workflow, not
copying the current implementation.

The controller runs a bounded research loop. One human-authored Research Run
Spec produces one Research Run. A Research Run produces zero or more Research
Experiments until it reaches its configured limit or a stop policy fires. Each
Research Experiment has one selected plan, one locked design, one
implementation/evaluation path, and one terminal Research Outcome.

The system is optimized for auditable handovers between agents and deterministic
artifacts. Thread memory can help continuity, but saved artifacts are always the
source of truth.

## Non-Goals

The controller does not promote candidates, merge work, create final commits, or
turn research outcomes into production changes. It does not trace every phase to
MLflow. It does not make MLflow authoritative. It does not run parallel selected
plans inside one experiment. It does not pause for human input mid-run in v1.

## Core Domain Objects

Research Run Spec:
Human-managed YAML input. It includes the research brief and operational
controls: run id, target repository, max experiment count, budget profiles,
selected budget, canonical input data root, experiment data root, worktree
behavior, MLflow mirror settings, agent model/effort, implementation repair
limit, required Research Program root, prior-experiment cap, and
stop-on-prerequisite-failure.

Research Program:
Durable home for one research line across many Research Runs. Every Research
Run Spec must configure `research_program_root`; it owns human steering docs,
run directories, preserved worktrees, and generated continuation memory.

Research Run:
One execution of a snapshotted Research Run Spec. It owns a run directory,
controller state, append-only ledger, and experiment subdirectories.

Research Experiment:
One bounded attempt to test one selected research plan. It owns its experiment
directory, selected plan, locked research spec/design, command logs, worktree or
read-only execution path, evaluator workspace, evaluation artifacts, summary,
and mirror output.

Default Hyperliquid research storage:

- research program: `/home/boser/agent-control-plane-runs/programs/<program-id>`
- controller run state: `<program-root>/runs/<run-id>`
- target repository: `/home/boser/HyperliquidMomentum`
- experiment worktrees: `<program-root>/worktrees/<run-id>/<experiment-id>`
- continuation memory: `<program-root>/memory`
- canonical read-only inputs: `/mnt/redbackup/data`
- generated experiment data:
  `/mnt/redbackup/experiment-data/<experiment-name>/<research-run-id>-<experiment-id>`
- default experiment name: the Research Run id when MLflow has no configured
  experiment name

The controller must reject `experiment_data_root` when it equals or sits under
`data_root`.

Research Outcome:
Terminal outcome enum for an experiment:

- `no_op`: no admissible experiment selected.
- `blocked`: external blocker or no deterministic commands.
- `prerequisites_failed`: data/prerequisite audit failed.
- `invalid`: controller or critic rejected the design.
- `run_failed`: execution, boundary, verification, or evaluation failure.
- `completed_rejected`: confirmatory evidence rejected the hypothesis.
- `completed_inconclusive`: confirmatory evidence was not decisive.
- `completed_candidate`: confirmatory gates passed and candidate merits human review.

Outcome diagnostics:
Every terminal summary also has `outcome_reason`, `failed_stage`, and
`failure_classification`. Keep these separate from the enum so the enum stays
small while diagnostics remain precise.

## Simplified Package Shape

Use these conceptual areas, not necessarily these exact files:

- Run controller: start, load, loop, stop policy, state transitions.
- Experiment flow: one bounded experiment sequence.
- Artifact models: strict schemas for canonical JSON artifacts.
- Agent gateway: role definitions, runtime config, thread lifetimes.
- Context builder: deterministic context pack and prior-run synthesis.
- Phase helpers: prerequisite audit, worktree management, verification, boundary
  audits, evaluator workspace.
- Mirror interface: provider-neutral research run mirror plus MLflow adapter.
- Shared primitives: JSON/JSONL IO, command runner, usage-limit backoff, generic
  agent runtime, git/hash boundary checks.
- CLI or shell entry points: start and resume a run.

Important boundary rule: SDK-specific integration code must live behind narrow
interfaces. In particular, MLflow code belongs in a separate adapter module. The
controller should depend only on a mirror interface, so MLflow can be replaced by
another experiment-tracking surface later.

## Runtime Directory Contract

The run directory is the canonical inspection surface.

Simplified shape:

- `<research_program_root>/runs/<research_run_id>/`
- snapshotted Research Run Spec
- `state.json`
- append-only ledger
- `experiments/<experiment_id>/`
- per-experiment artifacts, logs, command metrics, evaluation workspace

Per-experiment artifacts:

- context pack and context summary
- continuation summary, when available
- proposal
- selected plan
- locked research spec
- optional feature specs
- experiment design
- critique artifacts
- data audit
- implementation result
- implementation repair records
- implementation diff summary
- lineage
- verification logs and command metrics
- evaluator manifest, scratch, and outputs
- confirmatory evaluation result
- exploratory diagnostics result
- analysis ledger
- empirical critique
- terminal summary
- plan update

The exact filenames are less important than these contracts:

- every handover artifact is saved before the next actor uses it
- locked artifacts are hashable and immutable after lock
- logs and metrics are inspectable after failure
- worktrees and evaluator workspaces are preserved
- summary is the terminal authority for the experiment outcome

## State Model

Controller state is plain JSON, not a heavy domain model. It should include:

- controller state version
- research run id
- run status: `running` or `completed`
- current phase: initialized, ready for experiment, running experiment, completed
- active experiment id, if any
- completed experiment count
- max experiment count
- absolute run directory path
- absolute spec snapshot path
- experiments map keyed by experiment id
- thread ids by role/workspace

Each terminal experiment record stores:

- id
- status: terminal
- experiment directory
- outcome
- outcome reason
- failed stage
- failure classification
- lineage path, worktree path/branch, and changed files when available

State transitions are conservative:

1. Starting a run creates initialized running state.
2. Starting an experiment sets active experiment id and running-experiment phase.
3. Finishing an experiment records terminal summary, clears active experiment id,
   increments experiment count, and sets ready-for-experiment.
4. Completing the run sets completed status and completed phase.
5. Usage-limit pauses clear active experiment id, restore ready-for-experiment,
   delete the incomplete experiment directory, and return retry metadata.

## Ledger Contract

The ledger is append-only JSONL. It is not authoritative state, but it is the
audit trail. Record events for:

- research run started
- phase changed
- core artifacts written
- usage-limit wait
- design critique
- material revision critique
- implementation attempt
- implementation repair attempt
- evaluation attempt
- empirical critique
- experiment completed
- mirror failure

Events should include research run id, experiment id when relevant, thread ids
when relevant, workspace paths when relevant, outcome and failure details for
terminal events.

## Replaceable Interfaces

Agent runtime:
The controller should use a generic runtime interface:

- open a thread from role config
- resume by thread id when required
- run a turn with optional structured output schema
- return final structured response

Role config should include role name, cwd, developer instructions, model,
reasoning effort, output schema, thread id, sandbox policy, and approval policy.
Strategist and Critic are read-only. Implementer and Evaluator are
workspace-write.

Command runner:
Commands are structured records, not shell strings. Use argv with `shell=false`,
cwd, env overlay, timeout, stdout log path, stderr log path, and structured
result. Command metrics aggregate command count, pass/fail counts, status counts,
durations, env overlay, exit codes, and log paths.

An optional budget `maximum_memory_bytes` is a hard aggregate ceiling for each
controller-owned command process tree and for the Codex app-server process tree,
including commands launched by agents. Linux systemd user scopes enforce the
ceiling with swap disabled. A requested boundary fails closed when unavailable;
agents do not monitor, approve, or retry commands based on sampled memory.
Memory exhaustion is a systemic controller failure: command metrics remain
durable and implementation repair does not rerun the command. Land the systemic
runner-failure policy first so this failure stops the invocation without
consuming scientific budget.

Worktree manager:
Creates or reuses one preserved experiment worktree per selected experiment.
Reject dirty existing worktrees. Do not clean up automatically.

Boundary checker:
Provides git snapshots, allowed-path checks, locked artifact hash manifests, and
worktree unchanged assertions.

Research Run Mirror:
Provider-neutral interface accepting a request with run directory, tracking URI,
experiment name, research run id, experiment id, outcome, failed stage, failure
classification, and git SHA. The MLflow adapter implements this interface and is
the only place that imports or knows MLflow APIs.

## Agent Roles

Strategist:
Persistent read-only thread per Research Run. It uses context packs and prior
artifacts to propose the next bounded experiment, lock research spec/design,
select exactly one plan or no plan, close out completed experiments, and emit
future plan updates. It may use thread memory for continuity, but artifacts are
authoritative.

Critic:
Fresh read-only thread per critique pass. It independently reviews designs,
material revisions, leakage risk, baselines, gates, scope creep, and final
empirical interpretation. It must not inherit strategist, implementer, or
evaluator conversation state.

Implementer:
Workspace-write thread scoped to one experiment worktree. It changes source
files only within allowed write paths, declares implementation status, and
repairs mechanical verification failures. It must not change research semantics
such as target, labels, splits, success gates, metrics, feature lags, baselines,
or cost assumptions without a strategist revision and critic review.

Evaluator:
Workspace-write thread scoped to one evaluator workspace. It reads the evaluator
manifest, runs confirmatory evaluation and exploratory diagnostics, writes
analysis outputs, and returns structured evaluation artifacts. It must not edit
the implementation worktree or locked design artifacts.

## Artifact Schemas

Use strict schema validation at controller/agent boundaries. Do not over-model
controller internals.

Key artifact contracts:

Proposal:
hypothesis, rationale, signal family, expected mechanism, known risks,
falsification evidence.

Research spec:
hypothesis, target, prediction horizon, universe, label, feature availability
assumptions, split, primary metric, secondary metrics, baselines, null tests,
transaction cost assumptions, success gates, failure gates, inconclusive gates.

Feature specs:
feature id, inputs, transformation logic, lookback window, lag, normalization,
missing data policy, backfill range, point-in-time availability proof, expected
failure modes, optional name/family/source/timing fields.

Experiment design:
prerequisite commands, data audit commands, verification commands, confirmatory
commands, exploratory commands, expected outputs, allowed write paths, timeout,
resource budgets, failure routing.

Selected plan:
selected boolean, optional plan id, rationale, material revision categories.

Critique:
decision, fatal issues, required revisions, material revision categories, leakage
risks, baseline concerns, gate concerns.

Data audit:
passed boolean, optional outcome, outcome reason, failed stage, failure
classification, command results.

Implementation:
status, summary, changed files, declared commands, risks.

Implementation diff summary:
changed files, allowed path violations, evaluation logic changed flag, data
handling changed flag, high-risk flag, notes.

Lineage:
research run id, experiment id, experiment directory, worktree path/branch,
target repo head at start, worktree head after implementation, changed files,
implementation summary, reusable-for-followups flag.

Confirmatory evaluation result:
outcome, outcome reason, failed stage, failure classification, metrics, gate
results, pre-registered evidence.

Exploratory diagnostics:
findings, metrics, plots, future experiment ideas.

Summary:
outcome, outcome reason, failed stage, failure classification, human-readable
summary, confirmatory findings, exploratory findings.

Plan update:
followups, revisit conditions, blocked paths, reusable worktree flag,
recommended next experiment kind, implementation reuse notes.

## Deterministic Context Build

Before a strategist selects an agent-driven experiment, the controller writes a
context pack and machine-readable context summary into the experiment directory.
This is controller-owned, not agent-owned.

Context includes:

- Research Run Spec snapshot fields
- selected budget, default command timeout, and hard process-tree memory limit
- canonical input data root
- experiment data root
- artifact backfill policy: canonical data is read-only; optional experiment
  backfills write experiment-local runtime data
- experiment-local evaluation outputs declared by the Experiment Design
- target repository root
- git head, status text, changed files
- ledger history
- artifact inventory with hashes and sizes
- prior blockers
- repeated blockers
- prior failures
- completed outcomes
- completed prerequisites
- metric history from approved metric sources
- explicit repo loop context paths from the Research Run Spec
- continuation summary from prior program runs, plan updates, exploratory ideas,
  metrics, lineage, and reusable worktrees

The context builder excludes active non-terminal experiments from prior
synthesis, unless they already have a terminal summary.

## Material Revision Policy

Materiality is controller-owned. Agents may declare a revision material, but they
cannot decide a revision is non-material.

Default material categories:

- target
- label
- universe
- data source
- feature family
- split
- primary metric
- success gate
- baseline set
- transaction cost model
- holding period
- rebalance frequency
- neutralization policy

When a proposed revision changes any material category, or the selected plan
declares material categories, run a fresh Critic pass before continuing. If the
Critic blocks the revision, the experiment ends as invalid.

Do not scan all prior terminal experiments automatically for material revision
in the normal agent-driven path. Material review should compare an explicit
before/after payload when a revision flow supplies one.

## Experiment Loop Pseudocode

High-level run loop:

```text
start_research_run(spec_path):
  load and validate spec
  create run directory
  snapshot resolved spec
  create state and ledger

run_research_loop(research_run_id):
  load run and spec snapshot
  while true:
    state = read state
    if state is completed:
      return completed result
    if state is not running:
      fail controller
    if experiment_count >= max_experiments:
      mark run completed
      return completed result

    result = run_one_experiment()

    if result is usage_limit_wait:
      return retry metadata

    if result is not experiment_completed:
      return result

    if stop_policy(result.outcome, spec):
      mark run completed
      return completed result
```

One experiment:

```text
run_one_experiment():
  require current phase initialized or ready_for_experiment
  allocate next experiment id
  create experiment directory
  set active experiment id and phase

  try:
    result = run_experiment_flow(request)
  except usage_limit:
    clear active experiment
    delete incomplete experiment directory
    ledger usage_limit_wait
    return retry metadata
  except exception:
    write run_failed summary

  if runner did not produce experiment_completed:
    write run_failed summary

  read summary
  record terminal experiment in state
  set ready_for_experiment
  ledger experiment_completed
  return experiment_completed result
```

## Experiment Flow Pseudocode

```text
run_experiment_flow(request):
  if explicit selection supplied:
    use it
  else if no agent runtime:
    create no-op selection
  else:
    write context pack
    strategist returns proposal, research spec, design, selected plan
    pipeline enables design critique, implementation, empirical closeout

  write selected plan, design, research spec, feature specs if present

  summary = validate selection
  if no summary:
    summary = material revision review if required
  if no summary and design critique enabled:
    critic reviews locked design
    if blocked: summary = invalid
  if no summary:
    enforce worktree policy
  if no summary:
    run data/prerequisite audit
    if audit failed: summary = prerequisites_failed
  if no summary:
    create worktree if configured
    run implementation or write skipped implementation
    audit implementation boundary
  if no summary:
    run verification commands with repair callback if needed
    re-audit implementation boundary after repairs
    if verification failed and boundary passed: summary = run_failed
  if no summary:
    create evaluator workspace and manifest
    evaluator writes evaluation artifacts
    audit evaluator boundary even after evaluator defects
    if audit failed or evaluator failed: summary = run_failed
  if empirical closeout enabled and outcome is completed_*:
    critic reviews empirical artifacts
    strategist writes closeout summary and plan update
    preserve official outcome fields from confirmatory result

  write terminal summary once
  mirror experiment if enabled
  return experiment_completed
```

## Selection and Design Validation

If `selected=false`, end as `no_op`.

If a selected plan has no valid experiment design, end as `invalid`.

If a selected plan has neither verification commands nor confirmatory commands,
end as `blocked` with failure classification `no_deterministic_commands`.
Exploratory commands do not satisfy this requirement and do not trigger evaluator
execution without confirmatory commands.

If worktree creation is disabled but the design requires editable source changes
or verification in a worktree, end as `invalid`.

Design Critic decisions that block:

- fatal
- reject/rejected
- revise/requires revision/revision required
- any fatal issues
- any required revisions

## Data and Prerequisite Audit

Run data/prerequisite audit before implementation. This catches missing data and
invalid setup before spending effort on source changes.

Inputs:

- canonical input data root
- prerequisite commands
- data audit commands
- target repository cwd
- experiment directory
- experiment data directory
- timeout

Command environment:

- `RESEARCH_DATA_ROOT`
- `RESEARCH_EXPERIMENT_DATA_ROOT`
- `HLM_DATA_ROOT`
- `RESEARCH_RUN_DIR`
- `RESEARCH_REPO_ROOT`

If data root is missing, end as `prerequisites_failed` with
`data_root_missing`.

Allowed data-audit failure classifications:

- `data_root_missing`
- `feature_family_missing`
- `schema_mismatch`
- `artifact_missing`
- `point_in_time_invalid`
- `prerequisite_command_failed`

Successful audit writes a passing data-audit artifact and command metrics.
Failed audit writes failed data-audit artifact, command metrics, logs, and a
terminal summary.

Default run stop policy:
If an experiment outcome is `prerequisites_failed` and the spec has
`stop_on_prerequisites_failed=true`, complete the whole Research Run.

Runtime artifact backfills are not a mandatory audit step. Use prerequisite
commands only for baseline materialization that does not depend on experiment
worktree edits. If an experiment creates or modifies artifact code/config and
needs materialized data from it, declare that backfill as a verification command
so it runs from the experiment worktree after implementation.
Selected experiments that need generated runtime artifacts should make their
verification path materialize the declared experiment-local evaluation outputs.
Intermediate generated runtime data belongs under
`$RESEARCH_EXPERIMENT_DATA_ROOT/runtime-data`.

## Worktree and Implementation

By default, create one preserved worktree per selected experiment. Branch naming
and directory layout are derived from the Research Program root:
`<research_program_root>/worktrees/<research_run_id>/<experiment_id>`.

If the expected worktree already exists:

- inspect git status including untracked files
- if clean, reuse it
- if dirty, fail worktree preparation

Implementation flow:

1. Open or resume implementer thread for that worktree.
2. Run implementer with workspace-write permission.
3. Write implementation artifact.
4. Snapshot changed files.
5. Compare changed files against design allowed write paths.
6. Write implementation diff summary.
7. If any changed file is outside allowed paths, end as `run_failed` with
   failed stage `implementation_boundary_audit`.

Allowed paths must be repository-relative. Reject absolute paths and paths
containing `..`.

If no worktree is needed, write skipped implementation and empty diff summary.

## Verification and Repair

Verification commands run in the experiment worktree. They use structured argv,
the research command environment, per-attempt logs, and command metrics.

If all verification commands pass, continue.

If verification fails and repair attempts remain:

1. Reuse the implementer thread for that worktree.
2. Provide failed result records and stderr log paths.
3. Ask for execution repairs only.
4. Write implementation repair artifact when returned.
5. Retry verification.

When repairs are exhausted, return `run_failed` with failed stage `verification`.

After verification and repair, run the implementation boundary audit again.
Boundary failure takes precedence over verification failure, because out-of-scope
source changes invalidate the experiment before result interpretation.

## Evaluation Workspace

Evaluation is isolated from implementation.

Workspace shape:

- `evaluation/`
- `manifest`
- `eval_scratch/`
- `eval_outputs/`

Do not copy locked inputs into an `eval_inputs` directory. Use manifest paths.

Manifest contents:

- experiment directory
- worktree path or target repository path
- canonical input data root
- experiment data root
- experiment-local runtime artifacts, when present, before canonical data
- git SHA
- canonical artifact paths
- locked artifact hashes
- confirmatory command declarations
- exploratory command declarations
- eval scratch path
- eval outputs path

Before evaluator runs:

- capture worktree git snapshot
- hash locked artifacts

Evaluator flow:

1. Open or resume evaluator thread for the evaluator workspace.
2. Run evaluator with workspace-write permission, cwd at evaluator workspace.
3. Evaluator writes `confirmatory_evaluation_result.json`,
   `exploratory_diagnostics_result.json`, and `analysis_ledger.json` in the
   evaluator workspace.
4. Run boundary audit.
5. Controller validates and promotes those artifacts.

Boundary audit:

- locked artifact hashes must still match
- worktree git state must be unchanged
- ignored files are included in mutation detection

Run the boundary audit even if evaluator result files are malformed or evaluator
code crashes after mutating inputs. If audit fails, terminal outcome is
`run_failed` with failed stage `evaluation_boundary_audit`.

Confirmatory evaluation determines the official outcome. Exploratory diagnostics
are attached diagnostics; they can create future experiment ideas but cannot
upgrade the current experiment.

## Empirical Closeout

For completed outcomes only:

1. Run a fresh Critic empirical review over confirmatory and exploratory
   artifacts.
2. Reopen the persistent Strategist thread.
3. Strategist writes closeout summary text and plan update.
4. Controller preserves official outcome, outcome reason, failed stage, failure
   classification, and findings from the confirmatory/evaluation-derived
   summary.

This prevents a closeout narrative from changing the official result after
looking at exploratory findings.

## MLflow Mirror

MLflow is a mirror surface, not controller state. The run directory, state,
ledger, and artifacts remain authoritative.

Design the mirror as a replaceable interface:

- controller or experiment flow constructs a provider-neutral mirror request
- mirror wrapper catches exceptions
- on failure, append a ledger event and continue
- MLflow-specific adapter handles all MLflow imports and calls

MLflow adapter behavior:

- set tracking URI if configured
- set experiment name if configured
- start one MLflow run named by experiment id
- log params: research run id, experiment id
- set tags: outcome, failed stage, failure classification, git SHA
- flatten numeric metrics from approved files only:
  - command metrics
  - generic metrics
  - confirmatory evaluation result
- ignore booleans as metrics
- ignore non-finite values
- log all files under the experiment directory recursively as artifacts

No phase-by-phase MLflow logging. No MLflow tracing. MLflow failure must not
change experiment outcome.

## Usage-Limit Handling

Agent turns may raise usage/rate/quota limit errors. Shared usage-limit logic
should:

- detect known usage-limit messages
- parse retry time from relative or absolute hints
- retry once immediately after sleeping when possible
- if still limited, raise a usage-limit wait event

At experiment boundary:

- clear active experiment id
- reset phase to ready-for-experiment
- remove the incomplete experiment directory
- append usage-limit wait event to ledger
- return sleep seconds to caller

A caller can sleep and resume the controller loop.

## CLI Behavior

Minimum user-facing commands:

- start a Research Run from a Research Run Spec
- resume an existing Research Run

Start command:

- validates and snapshots spec
- creates state and ledger
- prints run id, run directory, spec snapshot path, and state path

Hyperliquid research runs should use:

```bash
research-experiment-controller run spec.yaml
```

`spec.yaml` must include `research_program_root`; run state lives under
`<research_program_root>/runs`.

Resume command:

- loads existing run
- invokes the controller loop through an agent runtime
- prints final status

CLI should not import MLflow. Keep integration setup behind the mirror adapter.

## Recreate Checklist

An equivalent implementation is complete when it can:

1. Start a run from a YAML spec and snapshot the resolved spec.
2. Maintain state and ledger across repeated experiments.
3. Build deterministic context packs from state, ledger, artifacts, git, budget,
   and prior outcomes.
4. Run strategist, critic, implementer, and evaluator with correct thread
   lifetimes and permissions.
5. Persist every handover artifact before the next phase reads it.
6. Validate canonical artifacts at agent/controller boundaries.
7. Classify no-op, invalid, blocked, prerequisites failed, run failed, and
   completed outcomes correctly.
8. Stop the run by default on prerequisites failed.
9. Run data audit before implementation.
10. Create and preserve clean experiment worktrees.
11. Audit implementation changes against allowed write paths.
12. Run verification with bounded implementer repair attempts.
13. Isolate evaluation into a dedicated workspace and audit locked inputs and
    worktree state afterward.
14. Preserve confirmatory outcome through empirical closeout.
15. Mirror experiment-end results to MLflow through an isolated adapter.
16. Continue when MLflow mirroring fails.
17. Handle usage-limit waits without corrupting state.
18. Expose enough artifacts, logs, metrics, and ledger events for another
    engineer or agent to inspect a completed or failed experiment.
