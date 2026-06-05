  ## Summary
 
    Add one canonical program memory artifact: memory/research_state.json.
 
    No new orchestration phases. No split idea_frontier.json, per-experiment learning files, blocker ledger, or implementation catalog. continuation_summary.json stays a rendered
  view for
    agents; research_state.json becomes source of truth.
 
    ## Public Contracts
 
    - Replace loose PlanUpdate strings with strict typed cards:
        - followups: list[FollowupCandidate]
        - learning_updates: list[LearningUpdate]
        - blockers: list[BlockerCard]
        - reusable_components: list[ReusableComponentCard]
        - superseded_idea_ids: list[str]
 
    - Extend SelectedPlan:
        - selected_idea_ids: list[str]
        - fresh_selection_reason: str | None
        - If selected=true and no selected_idea_ids, require non-empty fresh_selection_reason.
 
    - Add ResearchState in new research_state.py:
        - artifact_kind, schema_version, program_id, active_brief
        - next_idea_number, frontier, experiment_index
        - learning_updates, known_blockers, reusable_components, metric_observations
        - merged_experiments for idempotency
 
    - Strict policy:
        - no legacy string followup normalization
        - no dual-read compatibility
        - malformed research_state.json or typed plan updates fail loudly
 
    ## Key Changes
 
    - On Research Run start, create memory/research_state.json if missing; never rebuild from old artifacts.
    - After terminal experiment state is recorded, merge that experiment into research_state.json; this is a controller side effect, not a phase.
    - Before context rendering, load research_state.json and render existing continuation keys from it:
        - prior_experiments from experiment_index
        - pending_followups / future_experiment_ideas from pending frontier ideas
        - do_not_repeat from completed, blocked, superseded, and blocker records
        - reusable_implementations from reusable component records
        - metric_history / best_metric_runs from metric observations
 
    - Exclude research_state.json from generic memory_context; expose it through explicit continuation fields instead.
    - Strategist prompt changes:
        - prefer highest-priority pending frontier ideas
        - cite selected_idea_ids
        - use fresh_selection_reason only when not selecting from frontier
        - emit typed followups with mechanism, axis, specific change, falsifying evidence, priority reason, and dedupe key
 
    - Controller still does not auto-select experiments. Strategist chooses; controller validates, stores, dedupes, and statuses memory.

    ## Merge Rules
 
    - Idempotency:
        - if source_experiment is in merged_experiments, merge is no-op
 
    - Selected idea status:
        - completed_* outcome -> selected ideas become completed
        - prerequisites_failed, blocked, invalid -> selected ideas become blocked
        - run_failed -> selected ideas remain pending with operational blocker notes
        - no_op -> no idea status changes
 
    - New followups:
        - valid dedupe miss -> create pending frontier idea
        - valid dedupe hit -> append source experiment if absent, do not duplicate
        - priority must be 0.0 <= priority <= 1.0; sort pending ideas by priority desc, then idea id
 
    - Metrics:
        - record numeric leaves from confirmatory_evaluation_result.metrics
        - ignore booleans and non-numeric values
        - best runs derived, not stored separately
 
    - Reuse:
        - index typed reusable components from PlanUpdate
        - also index lineage worktree when completed outcome has changed files
        - seed worktree suggestions must be existing reusable worktree paths or selected idea suggestions
 
    ## Test Plan
 
    - Schema tests:
        - typed PlanUpdate cards validate
        - old string followups fail
        - SelectedPlan requires fresh_selection_reason when no idea IDs selected
 
    - Research state tests:
        - empty state creation
        - idempotent merge
        - followup dedupe
        - selected idea status transitions
        - blocker and reusable component indexing
        - metric observations and best-run rendering
 
    - Context tests:
        - continuation_summary.json rendered from research_state.json
        - current continuation keys preserved
        - research_state.json excluded from generic memory_context
 
    - Controller tests:
        - terminal experiment updates research state
        - usage-limit retry does not merge incomplete experiment
        - no new phase appears in state.json or ledger
 
    - Prompt tests:
        - Strategist prompt requires frontier use or fresh-selection justification
        - prompt requires typed followups and dedupe keys
 
    ## Assumptions
 
    - Single canonical artifact is preferred: memory/research_state.json.
    - Backward compatibility for old string plan_update.json does not matter.
    - No compatibility shims, no legacy normalization, no multi-artifact memory split.
    - Controller owns memory/status/dedupe; Strategist owns research judgment.
 
