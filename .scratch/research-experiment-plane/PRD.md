# Research Experiment Plane PRD

Status: ready-for-agent
Label: ready-for-agent

## Problem Statement

The user wants to migrate the useful research loop behavior from the Hyperliquid research orchestration work into this Agent Control Plane repo without forcing research work into the Task Control Plane lifecycle.

The existing Task Control Plane is built around a Task: one approved plan, implementation, review approval, and exactly one final commit. A Research Experiment has a different completion boundary. It can end as `no_op`, `blocked`, `prerequisites_failed`, `invalid`, `run_failed`, `completed_rejected`, `completed_inconclusive`, or `completed_candidate`. Its inspection boundary is the run directory, ledger, optional Experiment Worktree, Evaluator Workspace, and Research Run Mirror, not a final commit.

The user wants a sibling Control-Plane Workflow: the Research Experiment Plane. It should preserve the parts of the Hyperliquid loop that made experiments auditable: deterministic context packs, JSON artifacts, preserved worktrees, structured command records, data-root awareness, prerequisite execution, prior-run synthesis, usage-limit backoff, and Research Run Mirror output to MLflow. It should avoid the parts that would make the new controller rigid or heavy: phase-by-phase MLflow tracing, custom evaluator command APIs, broad validation frameworks, automatic promotion, final commits, and agent-owned workflow control.

Throughput is not a concern. Low setup burden, code flexibility, and ease of changing the workflow are more important. Hatchet is the chosen Durable Execution Shell because it can resume long-running work while leaving research semantics in ordinary Python controller code.

## Solution

Build a new Research Experiment Plane as a sibling Control-Plane Workflow. The workflow has its own Research Run Spec, Research Run, Research Experiment, agents, artifacts, outcomes, and completion boundary. It reuses shared control-plane primitives only where they are genuinely common with the Task Control Plane.

A Research Run starts from one Research Run Spec. The Research Run Spec is a single human-managed file that contains both the Research Brief and operational run controls. One Research Run may produce multiple bounded Research Experiments, controlled by `max_experiments`. Each Research Experiment has exactly one selected plan, one locked spec and design, one implementation/evaluation path, and one terminal Research Outcome.

Hatchet wraps the run through a provider-neutral Durable Execution Shell interface. Hatchet owns resume, sleep, event wait if ever needed later, step invocation, and generic run metadata for dashboard inspection through a local adapter only. Replacing Hatchet later should require local changes to the shell adapter and worker only. ADR 0001 records this boundary.

The Research Experiment Controller coordinates phases and owns research semantics: deciding which phase runs next, when integrations are called, which artifacts are authoritative, how materiality and outcomes are classified, and how boundaries are audited. It does not own MLflow or Hatchet implementation details and must not become a command runner, MLflow wrapper, or Hatchet workflow.

The Research Experiment Controller builds deterministic context, coordinates the Strategist, Critic, Implementer, and Evaluator agents, writes canonical Research Artifacts, runs prerequisite and verification commands through dedicated helpers, preserves worktrees, performs boundary audits, records ledger events, classifies outcomes, and requests Research Run Mirror output.

The Research Experiment Plane uses Pydantic only at artifact boundaries. Canonical JSON artifacts are validated contracts between controller and agents. Controller state, ledgers, Hatchet metadata, and internal routing data remain lightweight plain data with small validators where needed.

## User Stories

1. As a researcher, I want one Research Run Spec to include both research direction and run controls, so that I do not manage two files for one orchestration.
2. As a researcher, I want one Research Run Spec to run several bounded Research Experiments, so that a research direction can iterate without manual restarts.
3. As a researcher, I want each Research Experiment to have one selected plan, so that results are attributable to one locked design.
4. As a researcher, I want each Research Experiment to have one terminal Research Outcome, so that status is not split across redundant axes.
5. As a researcher, I want outcomes such as `completed_rejected` and `completed_inconclusive` to be first-class, so that negative and uncertain evidence is not hidden as failure.
6. As a researcher, I want data/prerequisite failures to use `prerequisites_failed`, so that systemic missing data is distinguished from implementation failure.
7. As a researcher, I want `stop_on_prerequisites_failed: true`, so that a Research Run stops when every later experiment would likely fail the same data audit.
8. As a researcher, I want outcome classification to be configurable, so that `no_op`, `blocked`, and related boundaries can be adjusted after observing real runs.
9. As a researcher, I want Research Budgets such as `smoke` and `research`, so that the same Research Run Spec can support short checks and longer backfills.
10. As a researcher, I want the selected budget to constrain pipeline and backfill command scope for the whole Research Run, so that command time windows are consistent.
11. As a researcher, I want the resolved Research Run Spec copied into the run directory, so that resume and audit use the same input snapshot.
12. As a researcher, I do not want extra budget validation on resume, so that the controller stays simple.
13. As a researcher, I want deterministic context packs, so that agents see the same run facts, prior results, data root, git state, and artifact surface.
14. As a researcher, I want prior-run synthesis in the context pack, so that agents remember repeated blockers, completed prerequisites, and useful metric history.
15. As a researcher, I want artifacts to be authoritative, so that thread memory helps continuity but never replaces saved evidence.
16. As a researcher, I want a persistent Strategist thread per Research Run, so that it remembers rejected ideas, blockers, revisions, and outcomes across experiments.
17. As a researcher, I want Critic threads to be fresh for each critique, so that critiques stay independent from Strategist, Implementer, and Evaluator state.
18. As a researcher, I want an Implementer thread scoped to an Experiment Worktree, so that repair context persists for implementation without bleeding across experiments.
19. As a researcher, I want an Evaluator thread scoped to an Evaluator Workspace, so that evaluation can create scripts and outputs without changing the implementation.
20. As a researcher, I want the Strategist to distinguish pre-registered evidence from exploratory findings, so that post-hoc positives do not become current-cycle wins.
21. As a researcher, I want the Strategist unable to revise success gates after seeing results, so that evaluation remains honest.
22. As a researcher, I want the Critic to check leakage, baselines, scope creep, invalid gates, post-hoc reasoning, and overclaiming, so that weak designs are caught early.
23. As a researcher, I want materiality to be controller-owned, so that a Strategist cannot bypass Critic review by framing a meaningful change as minor.
24. As a researcher, I want the Material Revision Policy to be configurable, so that the controller can decide which design changes require a fresh Critic pass.
25. As a researcher, I want data audits before implementation, so that missing data or invalid point-in-time assumptions stop bad experiments early.
26. As a researcher, I want prerequisite commands to run before implementation, so that required operational materializations are first-class.
27. As a researcher, I want prerequisite failures to record `failed_stage=data_audit`, so that the failure location is obvious.
28. As a researcher, I want prerequisite failure classifications such as `data_root_missing` and `feature_family_missing`, so that repeated setup issues are easy to diagnose.
29. As a researcher, I want one Experiment Worktree per selected Research Experiment, so that implementation changes remain inspectable after the run.
30. As a researcher, I want Experiment Worktrees preserved, so that candidates and failures can be inspected directly.
31. As a researcher, I want dirty existing Experiment Worktrees rejected, so that stale state cannot contaminate a new experiment.
32. As a researcher, I want implementation edits constrained by allowed edit paths, so that the Implementer cannot silently change unrelated code.
33. As a researcher, I want a deterministic implementation boundary audit, so that out-of-scope file changes fail before evaluation.
34. As a researcher, I want implementation verification to repair mechanical defects up to a configured limit, so that simple failures can be fixed in the same experiment.
35. As a researcher, I do not want v1 evaluation defects routed back to the Implementer in the same experiment, so that the controller stays minimal.
36. As a researcher, I want evaluation source/runtime defects classified as `run_failed`, so that failed evaluations are preserved without mid-run replanning.
37. As a researcher, I want the Evaluator to use an isolated writable workspace, so that it can write scripts, plots, tables, and results without modifying the worktree.
38. As a researcher, I want the Evaluator to receive a manifest with paths instead of copied input files, so that input management stays simple.
39. As a researcher, I want the Evaluator to run shell from the Evaluator Workspace, so that it can perform rich analysis without a custom command API.
40. As a researcher, I want no custom structured evaluation tool, so that the controller does not grow a mini API.
41. As a researcher, I want the controller to hash-check locked artifacts after evaluation, so that the Evaluator cannot alter the selected plan, spec, design, or gates.
42. As a researcher, I want the controller to compare worktree state before and after evaluation, so that evaluator writes outside its workspace are caught.
43. As a researcher, I want an Evaluation Boundary Audit failure to become `run_failed`, so that boundary violations are visible.
44. As a researcher, I want confirmatory evaluation to determine the official outcome, so that exploratory diagnostics cannot upgrade the current experiment.
45. As a researcher, I want exploratory diagnostics recorded separately, so that interesting findings can motivate future pre-registered experiments.
46. As a researcher, I want command execution to use argv and `shell=False`, so that command records are deterministic and safe to replay.
47. As a researcher, I want command logs to stream live to files, so that long backfills and evaluations are inspectable while they run.
48. As a researcher, I want command metrics recorded, so that the Research Run Mirror can display durations, pass/fail counts, exit codes, and timeouts.
49. As a researcher, I want command timeouts derived from the selected Research Budget by default, so that smoke and research runs behave differently without extra config.
50. As a researcher, I want data root and repo root passed into command environments, so that worktree-relative data paths do not cause false missing-data conclusions.
51. As a researcher, I want the run directory and ledger to be canonical, so that MLflow failure or absence cannot corrupt controller state.
52. As a researcher, I want MLflow to mirror end-of-experiment results best-effort through the Research Run Mirror, so that it remains a mirror surface, not control flow or trace authority.
53. As a researcher, I want MLflow to log only end-of-experiment params, tags, metrics, and artifacts, so that it stays useful without tracing every phase.
54. As a researcher, I want MLflow failures appended to the ledger and ignored by control flow, so that research runs continue when the mirror fails.
55. As a researcher, I want MLflow artifacts mirrored recursively, so that plots and tables under evaluation outputs are visible.
56. As a researcher, I want usage-limit errors to sleep until the suggested retry time, so that temporary service limits do not cause tight retry loops.
57. As a researcher, I want no Hatchet human event wait in v1, so that the research run proceeds without pausing for interactive approval.
58. As a researcher, I want agents to continue with explicit assumptions when human context is missing, so that automation remains uninterrupted.
59. As a maintainer, I want Hatchet metadata to stay generic, so that Hatchet dashboards are useful without embedding research semantics in decorators.
60. As a maintainer, I want Python controller code to own research semantics, so that Hatchet can be replaced later.
61. As a maintainer, I want Hatchet and MLflow each behind narrow local interfaces with SDK imports isolated to adapter modules, so that replacement stays local.
62. As a maintainer, I want shared control-plane modules only for genuinely common deep/testable primitives, so that workflow packages stay thin without premature abstraction.
63. As a maintainer, I want shared JSON artifact IO, so that workflows write stable canonical artifacts consistently.
64. As a maintainer, I want shared usage-limit backoff, so that Task and Research workflows handle Codex limits consistently.
65. As a maintainer, I want a shared structured command runner, so that streaming logs, timeouts, argv validation, and process-group termination are tested once.
66. As a maintainer, I want a shared generic agent runtime, so that workflow packages define roles without duplicating thread/tool plumbing.
67. As a maintainer, I want shared boundary audit helpers where sensible, so that allowed-path checks, worktree diff checks, and artifact hash checks are consistent.
68. As a maintainer, I want workflow-specific code to stay in the Research package until a second real consumer appears, so shared modules do not become shallow wrappers.
69. As a maintainer, I want Task-specific commit/review logic to remain inside the Task Control Plane, so that research outcomes are not forced into Task phases.
70. As a maintainer, I want Research-specific artifacts and outcomes inside the Research Experiment Controller, so that Task Control Plane remains unchanged.
71. As a maintainer, I want Pydantic used only at canonical artifact boundaries, so that the workflow does not become Pydantic-heavy.
72. As a maintainer, I want controller ledgers to stay plain and append-only, so that run history remains easy to inspect and recover.
73. As a maintainer, I want tests to focus on external behavior, so that refactors of controller internals remain possible.
74. As a maintainer, I want the Hyperliquid implementation treated as prior art, so that the new workflow imports behavior without copying old rigidity.
75. As a maintainer, I want the historical Hyperliquid pitfalls covered, so that no-op ambiguity, missing data-root context, opaque long commands, and shallow Research Run Mirror output do not return.
76. As a maintainer, I want v1 to include the full role chain, so that the end-to-end workflow shape is visible early.
77. As a maintainer, I want v1 to exclude parallel experiments, so that the single-experiment path is reliable first.
78. As a maintainer, I want v1 to exclude evaluator-to-implementer repair, so that evaluation failures are audit artifacts rather than another nested loop.
79. As a maintainer, I want v1 to exclude phase-by-phase MLflow logging and tracing, so that observability stays end-of-experiment and simple.
80. As a maintainer, I want v1 to exclude automatic promotion or final commits, so that research candidates remain inspectable until a human chooses what to do.
81. As a maintainer, I want material feature specs recorded when agents generate material signals, so that point-in-time validity and feature assumptions are explicit.
82. As a maintainer, I want selected commands, data-audit commands, and prerequisite commands recorded with argv, cwd, env, timeout, exit code, and duration, so that runs are reproducible.
83. As a maintainer, I want outcome reason, failed stage, and failure classification separate from outcome, so that the enum stays small but diagnostics remain useful.
84. As a maintainer, I want a recursive artifact manifest or hashes for locked artifacts, so that evaluation boundary audits are deterministic.
85. As a maintainer, I want controller metadata exposed to Hatchet as generic run metadata only, so that dashboards show run id, phase, version, and status without owning state.
86. As a maintainer, I want the run directory to include all core artifacts, so that a future agent can resume investigation from files without thread memory.
87. As a maintainer, I want Critic empirical critique after evaluation, so that final interpretation is independently checked.
88. As a maintainer, I want Strategist closeout after empirical critique, so that summary and plan update distinguish confirmatory evidence from exploratory promise.
89. As a maintainer, I want no selected plan to be different from blocked prerequisites, so that healthy no-ops and systemic blockers do not look the same.
90. As a maintainer, I want `prerequisites_failed` to stop the Research Run by default, so that repeated doomed experiments are avoided.
91. As a maintainer, I want the Research Run Stop Policy to stay minimal, so that v1 does not introduce a generic policy engine.
92. As a maintainer, I want the Research Run Spec to stay small, so that the user can tweak workflow behavior directly.
93. As a maintainer, I want all package boundaries to preserve future reversibility, so that the durable executor or Research Run Mirror adapter can be swapped later.
94. As a maintainer, I want the PRD to avoid treating Hyperliquid names as canonical here, so that Agent Control Plane domain terms remain consistent.
95. As a maintainer, I want the word Controller used instead of Orchestrator, so that the domain language stays aligned with the glossary.
96. As a maintainer, I want the Research Experiment Controller built as a new workflow, so that Task Control Plane behavior is not destabilized.

## Implementation Decisions

- Build a new Control-Plane Workflow: Research Experiment Plane.
- The workflow-specific package is a new Research Experiment Controller package.
- Add a shared control-plane package only for genuinely common primitives.
- First shared primitives should be JSON artifact IO, Codex usage-limit backoff, structured command runner, generic agent runtime, and boundary audit helpers.
- Shared modules must be deep and testable. Workflow-specific code stays in the Research package unless a second real consumer appears.
- Keep Task-specific planning, approval, review, commit, and Task lifecycle behavior inside the Task Control Plane.
- Keep research-specific outcomes, artifacts, worktrees, evaluator workspace, and Research Run Mirror behavior inside the Research Experiment Controller.
- Do not implement research as a mode of the Task Control Plane.
- A Task ends with one final commit; a Research Experiment ends with a Research Outcome and inspectable artifacts.
- A Research Run Spec is the single human-managed input document. It includes both Research Brief and run controls.
- Do not require a separate Research Brief file.
- A Research Run is one execution of a Research Run Spec.
- A Research Run may produce multiple Research Experiments, bounded by `max_experiments`.
- A Research Experiment has exactly one selected plan, one locked spec and design, one implementation/evaluation path, and one terminal Research Outcome.
- Each Research Experiment selects at most one plan. Multiple candidates may be proposed, but one plan is selected or the experiment records a no-op-style outcome.
- The Research Run repeats the experiment loop to produce multiple experiments. It does not run multiple selected plans inside one Research Experiment.
- Copy the resolved Research Run Spec into the Research Run directory. Resume reads the snapshot.
- Do not add special budget immutability validation beyond snapshotting.
- Use this minimal Research Run Spec shape:

```yaml
version: 1
research_run_id: peer-residual-v1
target_repository: /path/to/repo
max_experiments: 5

research_brief: |
  ...

budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
  research:
    month_start: "2020-01"
    month_end: "2026-01"
    max_runtime_minutes: 240

data_root: /mnt/redbackup/data

worktree:
  create: true
  root: .worktrees

mlflow:
  enabled: true
  tracking_uri: file:/path/to/mlruns
  experiment_name: peer-residual-v1

codex:
  model: gpt-5.3-codex
  effort: xhigh

implementation:
  max_repairs: 3

stop_on_prerequisites_failed: true
```

- Research Budgets are named execution profiles in the Research Run Spec.
- A Research Budget controls data window and runtime scope for pipeline and backfill execution for the whole Research Run.
- A Research Budget is not an experiment success gate.
- The selected budget's `max_runtime_minutes` is the default command timeout.
- The selected budget should be included in context packs and command environments where needed.
- Use a single Research Outcome enum:
  - `no_op`
  - `blocked`
  - `prerequisites_failed`
  - `invalid`
  - `run_failed`
  - `completed_rejected`
  - `completed_inconclusive`
  - `completed_candidate`
- Do not keep a separate evidence-status axis.
- Add non-status diagnostic fields:
  - `outcome_reason`
  - `failed_stage`
  - `failure_classification`
- Default no-op boundary: `no_op` means no admissible experiment was selected.
- Default blocked boundary: `blocked` means a missing external condition prevents progress but is not necessarily a global prerequisite failure.
- Default selected-but-no-deterministic-command behavior should not be a healthy `no_op`; classify according to the configurable Outcome Classification Policy.
- Keep outcome classification easy to tweak.
- Add `prerequisites_failed` for data/prerequisite audit failures likely to affect later experiments.
- When data/prereq audit fails, mark the current Research Experiment `prerequisites_failed`.
- Stop the whole Research Run by default when `stop_on_prerequisites_failed: true`.
- Data/prereq failure uses `failed_stage=data_audit`.
- Data/prereq failure classifications include:
  - `data_root_missing`
  - `feature_family_missing`
  - `schema_mismatch`
  - `artifact_missing`
  - `point_in_time_invalid`
  - `prerequisite_command_failed`
- Use Hatchet as a Durable Execution Shell adapter only.
- Durable shell callers depend on a provider-neutral local interface, not Hatchet SDK types.
- Hatchet owns only generic run metadata plus usage-limit sleep/retry around the Python controller loop.
- V1 does not resume inside a running Research Experiment phase.
- Python controller code owns phases, artifacts, materiality, outcomes, commands, worktrees, evaluator boundaries, ledgers, and when Research Run Mirror output is requested.
- MLflow SDK details live only behind the Research Run Mirror interface.
- Hatchet task/decorator metadata should stay generic. Avoid research-specific decorator metadata such as materiality gates.
- Useful Hatchet metadata may include generic run metadata such as run id, controller state version, current phase, and status.
- ADR 0001 records the Durable Execution Shell boundary.
- V1 includes:
  - context build
  - Strategist summary, proposal, spec, design, and selected plan
  - fresh Critic design critique
  - second Critic pass only when controller-detected material revision occurs
  - data/prerequisite audit
  - Implementer and implementation verification repair loop
  - implementation diff audit
  - Evaluator Workspace and Evaluation Boundary Audit
  - fresh Critic empirical critique
  - Strategist closeout
  - ledger and Research Run Mirror
- V1 excludes:
  - evaluator-to-implementer repair loop
  - phase-by-phase MLflow
  - MLflow tracing
  - parallel selected experiments
  - generic stop-policy lists
  - custom evaluator command APIs
  - automatic promotion
  - final commit
- No Hatchet human event wait in v1.
- Human input enters through the Research Run Spec.
- If agents lack human context, they continue with explicit assumptions and artifact notes instead of pausing.
- Agent thread lifetimes:
  - Research Strategist Agent: persistent read-only thread per Research Run.
  - Research Critic Agent: fresh read-only thread per critique pass.
  - Research Implementer Agent: persistent workspace-write thread per Research Experiment worktree.
  - Research Evaluator Agent: persistent workspace-write thread per Research Experiment evaluator workspace.
- Thread IDs are recorded in controller state and ledger. Artifacts remain authoritative.
- Research Strategist Agent owns context summary, hypothesis framing, proposal, pre-registration, experiment design, design revision, plan selection, final interpretation handoff, and plan update.
- Research Strategist Agent may use thread memory for continuity, but generated artifacts are source of truth.
- Research Strategist Agent must distinguish pre-registered evidence from exploratory findings.
- Research Strategist Agent must not revise success gates after seeing results.
- Research Critic Agent owns independent critique of design, material revisions, implementation-plan alignment, and final empirical interpretation.
- Research Critic Agent must not inherit Strategist, Implementer, or Evaluator conversation state.
- Research Implementer Agent owns implementation and repair of source changes, tests, command definitions, and runtime errors.
- Research Implementer Agent may repair execution but must not change labels, universe, splits, metrics, baselines, success gates, feature lags, cost assumptions, or missing-data policy without Strategist revision and Critic review.
- Research Evaluator Agent owns confirmatory evaluation, metric calculation, baseline/null comparisons, robustness checks, exploratory diagnostics, and empirical interpretation.
- Research Evaluator Agent may explore within the cycle, but official outcome comes only from locked confirmatory plan and boundary-audited artifacts.
- Material Revision Policy is controller-owned.
- Agents may declare that a revision is material.
- Agents must not be trusted to decide that a revision is non-material.
- Default material revision fields include target, label, universe, data source, feature family, split, primary metric, success gate, baseline set, transaction-cost model, holding period, rebalance frequency, and neutralization policy.
- If a material revision is detected, run a fresh Critic pass.
- Minor command or formatting fixes do not require another Critic pass by default.
- Pydantic is used only for canonical Research Artifacts crossing controller/agent boundaries.
- Controller internals, ledger records, and Hatchet metadata are not Pydantic-heavy.
- Minimum canonical artifacts:
  - `context_pack.md`
  - `context_summary.json`
  - `proposal.json`
  - `research_spec.json`
  - `experiment_design.json`
  - `critique.json`
  - `selected_plan.json`
  - `data_audit.json`
  - `implementation.json`
  - `implementation_repair_*.json`
  - `implementation_diff_summary.json`
  - `confirmatory_evaluation_result.json`
  - `exploratory_diagnostics_result.json`
  - `analysis_ledger.json`
  - `empirical_critique.json`
  - `summary.json`
  - `plan_update.json`
- For agent-generated transformations or signals, add `feature_spec.json` or equivalent feature registry entry per material feature.
- Feature specs should record inputs, transformation logic, lookback window, lag, normalization, missing-data policy, backfill range, availability-at-decision-time proof, and expected failure modes.
- Context Build is controller-owned and deterministic. No agent owns this step.
- Context Build includes Research Run Spec, prior runs, failed runs, git state, available artifacts, data-root metadata, and ledger history.
- Data and prerequisite audit commands run before worktree setup when possible.
- Prerequisite commands are controller-run structured argv commands.
- Experiment Worktree policy:
  - create one worktree per selected Research Experiment by default
  - preserve worktrees after terminal outcome
  - reject dirty existing worktrees
  - no automatic cleanup
  - `create: false` only for dry-run, read-only, or no-edit experiments
- Implementer cwd is the Experiment Worktree.
- Implementer gets workspace-write access.
- Allowed edit paths come from `experiment_design.json`.
- Implementer prompt treats allowed edit paths as binding.
- Controller audits changed files against allowed edit paths before verification and evaluation.
- Out-of-scope implementation changes fail with `outcome=run_failed` and `failed_stage=implementation_boundary_audit` unless a future Strategist revision and fresh Critic pass authorize the change.
- Implementation verification repair loop is in v1.
- Implementation verification loop runs up to `implementation.max_repairs`.
- Implementation verification repairs use the same Implementer thread.
- Implementation verification repairs may fix execution only, not research semantics.
- Evaluator-to-Implementer repair loop is out of scope for v1.
- If evaluation fails due to source/runtime defect in v1, classify as:
  - `outcome=run_failed`
  - `failed_stage=evaluation`
  - `failure_classification=source_runtime_defect` or `evaluation_runtime_defect`
- Preserve artifacts, logs, worktree, and evaluator workspace after evaluation failure.
- Evaluator Workspace shape:

```text
evaluation/
  manifest.json
  eval_scratch/
  eval_outputs/
```

- Do not create an `eval_inputs` subtree.
- Before evaluator starts, controller writes `evaluation/manifest.json`.
- The manifest includes paths to run dir, canonical artifacts, worktree, data root, locked confirmatory commands, locked artifact hashes, and git SHA.
- Start Evaluator with cwd set to the Evaluator Workspace and workspace-write access.
- Evaluator can create scripts under `eval_scratch`.
- Evaluator can write plots, tables, and results under `eval_outputs`.
- Evaluator can run shell from the Evaluator Workspace.
- Evaluator can read canonical artifacts through manifest paths.
- Evaluator can read repo, worktree, and data paths from the manifest.
- Evaluator must not edit the Experiment Worktree.
- Evaluator must not change selected plan, spec, design, locked gates, or locked confirmatory commands.
- Evaluator must not promote exploratory diagnostics into confirmatory outcome.
- Evaluation Boundary Audit checks worktree git diff/status after evaluation.
- Evaluation Boundary Audit hash-checks locked artifacts named in the manifest after evaluation.
- Evaluation Boundary Audit failure becomes `outcome=run_failed` and `failed_stage=evaluation_boundary_audit`.
- Do not add a custom structured evaluation tool in v1.
- The shared command runner contract:
  - argv only
  - `shell=False`
  - cwd required
  - env overlay optional
  - live stdout/stderr streaming
  - timeout support
  - process-group termination on timeout
  - structured command result
  - configurable combined or per-command logs
- Task Control Plane may keep combined command logs.
- Research Experiment Controller uses separate logs as useful for prerequisites, verification, and evaluation.
- Command environments include run dir, data root, and repo root.
- Data root defaults to the Research Run Spec value.
- Worktree-relative data paths are noncanonical.
- Research Run Mirror boundary:
  - run dir and ledger are canonical
  - MLflow is a best-effort mirror only at experiment end
  - controller constructs a Research Run Mirror request only
  - MLflow SDK imports stay inside the mirror adapter module
  - no tracing
  - no phase-by-phase logging
  - if MLflow fails, append ledger event and continue
- MLflow params/tags:
  - `research_run_id`
  - `experiment_id`
  - `outcome`
  - `failed_stage`
  - `failure_classification`
  - `git_sha`
- MLflow metrics sources:
  - numeric leaves from `command_metrics.json`
  - numeric leaves from `metrics.json`
  - numeric leaves from final evaluation result
- MLflow logs all run-directory artifacts recursively with one helper.
- Ledger records every phase, thread id, artifact hash, command attempt, repair attempt, evaluation attempt, Critic pass, final outcome, failed stage, and failure classification.
- Reproducibility depends on saved artifacts, logs, schemas, data versions, git state, structured argv, environment details, random seeds, and deterministic execution records.

## Testing Decisions

- Tests should verify external behavior and persisted artifacts, not private implementation structure.
- The Research Run Spec loader should be tested for required fields, defaults, budget profiles, selected budget lookup, `stop_on_prerequisites_failed`, and snapshot behavior.
- Research Run startup should be tested for resolved spec copy, initial controller state, ledger initialization, and deterministic run directory layout.
- Hatchet wrapper tests should cover the public thin-shell contract: delegate to the controller loop, sleep/retry on usage-limit status, and expose generic metadata.
- Hatchet tests should not assert research semantics inside decorator metadata.
- Generic agent runtime tests should cover arbitrary role names, read-only role capability, workspace-write role capability, persistent thread id reuse, fresh-thread creation, and workflow-supplied prompts.
- Artifact IO tests should cover stable JSON writing, Pydantic validation at artifact boundaries, hash calculation, and clear errors for malformed canonical artifacts.
- Context build tests should cover inclusion of Research Run Spec, budget, data root, git state, prior outcomes, failed runs, completed prerequisites, repeated blockers, and artifact availability.
- Material Revision Policy tests should cover controller-detected material changes requiring Critic pass, agent-declared material revisions, and non-material command/formatting fixes.
- Outcome Classification Policy tests should cover `no_op`, `blocked`, `prerequisites_failed`, `invalid`, `run_failed`, `completed_rejected`, `completed_inconclusive`, and `completed_candidate`.
- Data/prerequisite audit tests should cover `data_root_missing`, `feature_family_missing`, `schema_mismatch`, `artifact_missing`, `point_in_time_invalid`, and `prerequisite_command_failed`.
- Research Run Stop Policy tests should cover stopping the Research Run when `stop_on_prerequisites_failed` is true and continuing when false.
- Command runner tests should cover argv validation, shell-string rejection, cwd, env overlay, live stdout/stderr streaming, command metrics, timeout handling, and process-group termination.
- Worktree tests should cover creation, preservation, dirty reuse rejection, and no cleanup.
- Implementation boundary audit tests should cover allowed edit paths, out-of-scope file changes, and failure classification.
- Implementation verification loop tests should cover pass, fail then repair, max repair exhaustion, and prohibition on semantic weakening.
- Evaluator Workspace tests should cover manifest writing, workspace-write cwd, absence of `eval_inputs`, expected scratch/output directories, and shell execution scoped to evaluation cwd.
- Evaluation Boundary Audit tests should cover unchanged worktree pass, changed worktree failure, locked artifact hash pass, locked artifact hash failure, and correct `failed_stage`.
- Evaluator failure classification tests should cover source/runtime defect and evaluation runtime defect without same-experiment Implementer reroute.
- Research Run Mirror tests should cover best-effort behavior, params/tags, allowed metrics sources, recursive artifact logging, and ledger event on mirror failure.
- Ledger tests should cover phase events, thread ids, artifact hashes, command attempts, repair attempts, evaluation attempts, Critic passes, final outcome, failed stage, and failure classification.
- Thread lifetime tests should cover Strategist persistence per Research Run, Critic freshness per critique, Implementer persistence per Research Experiment, and Evaluator persistence per Research Experiment.
- No-human-wait tests should cover missing human context leading to explicit assumptions rather than Hatchet event wait.
- Prior art for tests exists in Task Control Plane controller tests, Task Hatchet workflow tests, Task agent runtime tests, and Hyperliquid orchestrator tests for command execution, context synthesis, ledger events, usage-limit backoff, worktree reuse, prerequisites, and Research Run Mirror behavior.

## Out of Scope

- Do not implement code as part of this PRD-writing task.
- Do not make Research Experiment Plane a mode of Task Control Plane.
- Do not force Research Experiments to produce final commits.
- Do not auto-merge, promote, or rewrite production artifacts based on a Research Outcome.
- Do not implement parallel selected plans inside one Research Experiment.
- Do not implement parallel Research Experiments in v1.
- Do not implement evaluator-to-implementer repair loop in v1.
- Do not implement phase-by-phase MLflow logging.
- Do not implement MLflow tracing.
- Do not make MLflow part of controller correctness.
- Do not add a custom structured command API for Evaluator.
- Do not add Hatchet human event waits in v1.
- Do not add a generic stop-policy list in v1.
- Do not add strict budget validation on resume.
- Do not automatically clean or archive Experiment Worktrees.
- Do not rely on notebooks as orchestrated execution surfaces.
- Do not add broad validations merely because they are possible.
- Do not put strategy-specific orchestration or feature registries into shared runtime packages.
- Do not extract shallow wrappers into the shared package. Shared modules should be deep and testable.

## Further Notes

- Hyperliquid prior art showed useful behavior: run directories, ledgers, prior-run synthesis, preserved worktrees, data-root injection, live command logs, command metrics, usage-limit backoff, prerequisite execution, and Research Run Mirror output.
- Hyperliquid gaps to avoid here: shallow MLflow artifact mirroring, no run-level artifact hashing beyond declared artifacts, and ambiguous no-op causes.
- The Research Run Mirror should mirror all run-directory artifacts recursively at experiment end.
- The new workflow should preserve artifact hashes for locked artifacts and ledger records where useful.
- `no_op` and `blocked` boundaries may evolve after observing real runs; keep outcome classification simple but configurable.
- The glossary in `CONTEXT.md` was updated during design. Use those terms in implementation and issues.
- ADR 0001 captures the Durable Execution Shell boundary and should be respected by implementation.
