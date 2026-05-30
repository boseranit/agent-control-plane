Have a look at the orchestator logic in ~/HyperliquidMomentum/research. I want to migrate a version of the orchestrator logic into this repo in a way so that it integrates well with the current task orchestrator. this loop is more
  research oriented and has its own loop of specialized agents, and importantly, it also has logging in mlflow that I
  want to migrate over here.

  You should be aware of the requirements and old issues that are specified in ~/HyperliquidMoment/docs/architecture/research-orchestrator-prd.md. These gaps have mostly been fixed now, but they are
  good for guiding what the requirements are when you implement it here so make sure to read all of it first. 
  You can get multiple gpt-5.3-codex-spark xhigh subagents to summarise the code in the HyperliquidMomentum repo - do not read python files in that repo yourself.

Throughput is not a concern and my primary goals are low setup burden and maximum flexibility to tweak code, so I think  Hatchet is almost certainly the best choice for this specific project. Hatchet runs on an incredibly simple stack: a Go-based engine binary and a standard PostgreSQL database. Hatchet functions more like a DAG or a state-machine engine. You define your workflow steps as individual Python functions decorated with @hatchet.step(). State is passed explicitly via function arguments and JSON payloads. If you want to change step 5, add an audit check between steps 6 and 7, or modify your loop logic, you just change the Python code and restart your worker. Hatchet doesn't care about past determinism; it just executes the new graph definition for the next run.
https://github.com/hatchet-dev/hatchet


This is the actual workflow that I want to implement; you should note that it is different from the Hyperliquid research version in several ways but one key way being that the roles are collapsed based on conversation durability.

Agents

1. Research Strategist Agent
Persistent read-only thread, scoped to the loop. Owns context summary, hypothesis framing, proposal, pre-registration, experiment design, design revision, plan selection, final interpretation handoff, and plan update. It remembers prior rejected ideas, blockers, revisions, empirical outcomes, and allowed revisit conditions, but generated JSON artifacts remain the source of truth. It must distinguish pre-registered evidence from exploratory findings and may not revise success gates after seeing results.
2. Research Critic Agent
Fresh read-only thread per critique. Owns independent critique of research design, material revisions, implementation-plan alignment, and final empirical interpretation. It should not inherit Strategist, Implementer, or Evaluator conversation state, so it can catch leakage, weak baselines, scope creep, invalid success gates, post-hoc reasoning, and overclaiming.
3. Research Implementer Agent
Persistent workspace-write thread, scoped to the experiment worktree. Owns implementation and repair of source changes, tests, command definitions, and runtime errors. It should keep working through mechanical failures until commands pass, a bounded retry limit is hit, or the failure is classified as data/prerequisite/research invalid rather than implementation repair. It may repair execution, but may not change research semantics such as labels, universe, splits, metrics, baselines, success gates, feature lags, cost assumptions, or missing-data policy without routing back to the Strategist.
4. Research Evaluator Agent
New persistent evaluation thread, scoped to the cycle. It should be independent from Strategist and Implementer. It owns confirmatory evaluation, metric calculation, baseline/null comparisons, robustness checks, exploratory diagnostics, and empirical interpretation. It may iterate within the same cycle for diagnostics, ablations, and robustness checks, but official success/failure status must come only from the locked pre-registered evaluation plan. Source-code bugs are handed back to the Implementer.
sig-chatgptenterprise
Enterprise
Workflow
1. Context Build
Controller builds context_pack.md deterministically from params, loop spec, prior runs, failed runs, git state, available artifacts, data-root metadata, and research ledger history. No agent owns this step. Thread memory is allowed to help continuity, but artifacts, logs, schemas, and deterministic command records remain authoritative.
2. Strategic Planning


Strategist receives the context pack and writes context_summary.json, then proposal.json. The proposal should state the hypothesis, economic or statistical rationale, intended signal/feature family, expected mechanism, known risks, and what evidence would falsify the idea. It should use prior loop memory to avoid repeating known blocked paths, while recording every decision in artifacts. 3. Research Specification And Experiment Design
Strategist writes research spec.json and experiment_design.json. research_spec.json is the pre-registration artifact. It defines the hypothesis, target, prediction horizon, universe, label, feature availability assumptions, train/validation/test split, primary metric, secondary metrics, baselines, null tests, transaction-cost assumptions, success gates, failure gates, and inconclusive gates. experiment_design.json defines prerequisite commands, implementation verification commands, confirmatory evaluation commands, optional exploratory diagnostic commands, expected outputs, allowed write paths, timeouts, resource budgets, and failure routing.
4. Independent Design Critique
Controller starts a fresh Critic thread with the proposal, research spec, experiment design, context summary, failed-run context, and relevant artifact notes. Critic writes critique.json. It should check leakage risk, point-in-time validity, baseline strength, statistical validity, multiple-testing risk, scope control, feasibility, and whether the success gates are meaningful.
5. Design Revision And Selection
Strategist revises the research spec or experiment design when required, then writes selected plan.json. A second fresh Critic pass is required for material revisions involving target, label, universe, data source, feature family, split, primary metric, success gate, baseline set, transaction-cost model, holding period, rebalance frequency, or neutralization policy. Minor command or formatting fixes do not require another Critic pass.
6. Data And Prerequisite Audit
Controller runs prerequisite and data-audit commands from the experiment design using deterministic argy execution. These checks verify data availability, schema compatibility, artifact presence, time coverage, point-in-time assumptions, feature/label timestamp alignment, and obvious leakage risks. Results are written to data_audit.json and prerequisite logs. If the design assumes unavailable data or invalid artifacts, return to Strategist. If the failure is mechanical setup or command repair, route to Implementer after worktree setup. 7. Implementation
Controller prepares the loop-scoped worktree. Implementer receives selected plan, research spec, experiment design, critique, data audit, prerequisite result, allowed edit paths, and repo rules. It makes code and test changes, then writes implementation, json. The implementation must match the selected plan rather than improve or reinterpret it.

8. Verification and repair loop 
Controller runs implementation verification commands. On failure, logs and experiment_result.json go back to the same implementer thread. Implementer writes a repair artifact, changes code
or command declarations within allowed scope, and the Controller reruns Verification. Repeat until pass, bounded retry exhaustion, timeout, or non- implementation blocker. Verification repair may not weaken tests, remove hard cases, narrow datasets, or alter research semantics without Strategist revision. 9. Implementation Diff Audit
After verification passes, Controller creates implementation_diff_summary.json. A fresh Critic pass may be run for high-risk or material changes. The audit checks whether the implementation matches the selected plan, whether evaluation logic changed, whether filtering or data handling changed, and whether any target leakage, hard-coded period, hard-coded symbol, or unplanned threshold was introduced.
10. Locked Confirmatory Evaluation
Evaluator receives all prior artifacts, command logs, implementation diff, and verification results. It runs or requests only the locked confirmatory evaluation commands defined in the selected plan. It computes metrics, compares baselines and nulls, checks success gates, and writes
confirmatory evaluation_result.json. This artifact determines the official empirical status: success, failure, inconclusive, invalid, or blocked. 11. Exploratory Diagnostics
Evaluator may run additional diagnostics, robustness checks, ablations, null tests, regime checks, or sensitivity analyses within the same cycle. These are recorded in exploratory_diagnostics_result.json and analysis_ledger.json. Exploratory findings may justify future experiments, but may not upgrade the official result of the current cycle.
12. Evaluator Failure Routing
If evaluation commands fail due to source/runtime defects, send the failure package back to the Implementer thread, then resume the same Evaluator thread after repair. If results are poor but commands are valid, record empirical failure. If the result is directionally interesting but unstable, underpowered, or dependent on fragile assumptions, record inconclusive. If data is missing or the design cannot answer the research question, hand back to Strategist as blocked, invalid, or requiring a revised future experiment.
13. Independent Empirical Critique
Controller starts a fresh Critic thread with the selected plan, implementation diff, verification logs, confirmatory result, exploratory diagnostics, analysis ledger, and evaluator report. Critic writes empirical_critique.json. It should check whether interpretation matches evidence, whether success gates were preserved, whether post-hoc findings were promoted improperly, whether baselines and costs were sufficient, whether multiple-testing risk was addressed, and whether the recommended status is justified.
14. Strategic Closeout
Strategist receives the evaluator report and empirical critique, then writes summary.json and plan_update.json. It should distinguish prerequisite failure, implementation failure, evaluation invalidity, empirical failure, inconclusive evidence, confirmatory success, and exploratory-only promise. Follow-ups must be justified by completed evidence and should clearly state whether they come from confirmatory results or exploratory diagnostics.
15, Ledger And MLflow
Controller records every phase, thread id, artifact hash, command attempt, repair attempt, evaluation attempt, Critic pass, final status, and failure classification. MLflow records metrics and artifacts, but the Controller ledger remains the canonical event log. Reproducibility depends on saved artifacts, logs, schemas, data versions, git state, command argy, environment details, random seeds, and deterministic execution records.


Core Artifact Set
Minimum recommended artifacts:
context_pack.md
context summary.json
proposal.json
research spec.json
experiment_design.json
critique.json
selected plan.json
data_audit.json
implementation.json
implementation_repair_*.json
implementation_diff_summary.json
confirmatory_evaluation_result.json
exploratory_diagnostics_result.json
analysis ledger.json empirical critique.json summary.json
plan_update.json

For agent-generated transformations or signals, add one feature_spec.json or equivalent feature registry entry per material feature. Each feature should record inputs, transformation logic, lookback window, lag, normalization, missing-data policy. backfill range, availability-at-decision-time proof, and expected failure modes.

Key Design Rules
1. Artifacts are authoritative; thread memory is only a convenience layer. 2. The Implementer may repair execution, but may not improve the research result.
3. The Evaluator may explore, but only the locked confirmatory plan determines official success or failure.
4. Exploratory positives become future pre-registered cycles, not current-cycle wins.
5, Success, failure, and inconclusive outcomes should all be first-class results. 6. Any material change to label, universe, split, metric, baseline, cost model, feature timing, or success gate requires Strategist revision and fresh Critic review.
7. Every signal must prove point-in-time validity before empirical claims are
trusted.

This is a simplified sketch to illustrate how your workflow translates to Hatchet. The full implementation would include all error handling, retry limits, and artifact production.

```python
from hatchet import Hatchet, DurableContext, EmptyModel
from pydantic import BaseModel
# Import your agent runner functions
from agents import run_strategist, run_critic, run_implementer, run_evaluator

hatchet = Hatchet()

# Define Pydantic models for your artifacts
class ContextSummary(BaseModel): ...
class Proposal(BaseModel): ...
class ResearchSpec(BaseModel): ...
# ... define all other artifact models

@hatchet.durable_task(name="research_cycle")
async def research_cycle(input: EmptyModel, ctx: DurableContext) -> dict:
    # 1. Context Build (Controller logic, could be a separate task or part of this)
    context_pack = build_context_pack()  # Your deterministic function
    await ctx.log("Context pack built")
    
    # 2. Strategic Planning
    context_summary, proposal = await run_strategist(context_pack)
    # 3. Research Specification And Experiment Design
    research_spec, experiment_design = await run_strategist(context_summary, proposal)
    
    # 4. Independent Design Critique (Fresh thread per critique)
    critique = await run_critic(proposal, research_spec, experiment_design, context_summary)
    
    # 5. Design Revision And Selection (Logic to handle material revisions)
    if needs_revision(critique):
        research_spec, experiment_design = await run_strategist(research_spec, experiment_design, critique)
        critique = await run_critic(research_spec, experiment_design)  # Second Critic pass
    selected_plan = select_plan(research_spec, experiment_design, critique)
    
    # 6. Data And Prerequisite Audit
    data_audit, prereq_ok = await run_data_audit(selected_plan)
    if not prereq_ok:
        return {"status": "blocked", "reason": "Data audit failed"}
    
    # 7. Implementation
    implementation_result = await run_implementer(selected_plan, data_audit)
    
    # 8. Verification and repair loop
    verification_ok = False
    retries = 0
    while not verification_ok and retries < MAX_RETRIES:
        verification_ok, verification_logs = await run_verification(implementation_result)
        if not verification_ok:
            implementation_result = await run_implementer(implementation_result, verification_logs)
            retries += 1
    
    if not verification_ok:
        return {"status": "implementation_failure", "retries": retries}
    
    # 9. Implementation Diff Audit (Fresh Critic pass if high-risk)
    diff_audit = await run_diff_audit(implementation_result, verification_logs)
    if diff_audit.high_risk:
        critique = await run_critic(diff_audit)  # Fresh Critic for diff
    
    # 10. Locked Confirmatory Evaluation
    confirmatory_result = await run_evaluator(selected_plan, implementation_result, diff_audit)
    
    # 11. Exploratory Diagnostics
    exploratory_results = await run_evaluator(confirmatory_result, exploratory=True)
    
    # 13. Independent Empirical Critique
    empirical_critique = await run_critic(confirmatory_result, exploratory_results)
    
    # 14. Strategic Closeout
    summary, plan_update = await run_strategist(confirmatory_result, empirical_critique)
    
    # 15. Ledger And MLflow (Controller logs to MLflow and PostgreSQL here)
    log_to_ledger(ctx, all_artifacts)
    log_to_mlflow(summary, confirmatory_result)
    
    return {"status": confirmatory_result.status, "summary": summary}
```


this should land as a new sibling Control-Plane Workflow rather than as a mode of the existing Task Control Plane.

Add a Research Experiment Plane with its own work unit and controller, reusing shared helpers
  where sensible. The imported loop preserves experiment worktrees, records no_op/candidate/failed outcomes, runs
  prerequisites, and mirrors to MLflow; that does not fit the existing Task lifecycle, which ends in review approval and
  exactly one final commit.

A Task ends with one final commit after plan/implementation/review. A Research Experiment can
  end as no_op, run_failed, completed_rejected, or completed_candidate, and its inspection boundary is the run artifacts
  plus optional worktree, not a final commit.

create a new package for the Research Experiment Controller, and extract only genuinely shared
  primitives out of the current Task controller as we need them. Concretely:

  - New workflow package: agent_control_plane/research_experiment_controller/
  - Shared package: agent_control_plane/control_plane/
  - First shared modules: JSON artifact IO, Codex usage-limit backoff, structured command runner, maybe MLflow mirror
  - Keep Task-specific planning/approval/review/commit logic inside task_control_plane

  This avoids forcing research outcomes into Task phases while still reusing the parts that are actually common.
  - Research Brief for the human-authored research direction
