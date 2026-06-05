# Research Memory Contract

## Summary

Add one canonical program memory artifact: `memory/research_state.json`.

No new orchestration phases. No split `idea_frontier.json`, per-experiment learning files, blocker ledger, or implementation catalog. `continuation_summary.json` stays a rendered view for agents; `research_state.json` is source of truth.

Keep changes that improve research learning: strict typed plan updates, selected-reference validation, completed ideas in `do_not_repeat`, and lineage-owned reusable metadata.

Learning quality means each candidate idea stays a testable hypothesis with provenance to the Research Brief, prior evidence, or both. Memory should preserve why an idea is worth testing and what would falsify it, without becoming a second research brief.

Remove changes that add mutable or duplicate state, or hide missing learning: synthetic empty `plan_update.json`, `merged_experiments`, `active_brief`, and auto `lineage:*` reusable components.

## Public Contracts

- Replace loose `PlanUpdate` strings with strict typed cards:
    - `followups: list[FollowupCandidate]`
    - `learning_updates: list[LearningUpdate]`
    - `blockers: list[BlockerCard]`
    - `reusable_components: list[ReusableComponentCard]`
    - `superseded_idea_ids: list[str]`

- `FollowupCandidate` must carry enough structure to dedupe and rank, including evidence basis, falsifying evidence, priority rationale, and any seed component refs.

- `LearningUpdate` must preserve evidence, not just conclusions.

- `ReusableComponentCard` is strategist-owned but not filesystem-owned:
    - keep agent-owned fields: `component_key`, `summary`, `reusable_for`, `risk_notes`
    - remove agent-owned `worktree_path` and `changed_files`
    - controller fills `ReusableComponentRecord.worktree_path` and `changed_files` from `lineage.json`

- Extend `SelectedPlan`:
    - `selected_idea_ids: list[str]`
    - `fresh_selection_reason: str | None`
    - `seed_component_ids: list[str]`
    - If `selected=true` and no `selected_idea_ids`, require non-empty `fresh_selection_reason`.
    - Validate `selected_idea_ids` and `seed_component_ids` before writing `selected_plan.json`.

- Add `ResearchState` in new `research_state.py`:
    - `artifact_kind`
    - `schema_version`
    - `program_id`
    - `next_idea_number`
    - `idea_index`
    - `experiment_index`
    - `learning_updates`
    - `known_blockers`
    - `reusable_components`
    - `metric_observations`

- `idea_index` records store pending hypotheses from typed followups plus controller-owned source experiments and status.

- `experiment_index` records preserve enough tested-hypothesis context for later reasoning, including outcome, selected rationale, metric context, and lineage/worktree summary.

- Do not add these `ResearchState` fields:
    - `active_brief`; canonical brief stays in run spec/context
    - `merged_experiments`; `experiment_index` is idempotency source

- Strict policy:
    - no legacy string followup normalization
    - no dual-read compatibility
    - no compatibility shims for old artifacts or current unstaged schemas
    - malformed `research_state.json` fails loudly
    - malformed typed plan updates fail loudly

## Key Changes

- On Research Run start, create `memory/research_state.json` if missing; never rebuild from old artifacts.

- In experiment flow:
    - validate `selected_idea_ids` and `seed_component_ids` before writing `selected_plan.json`
    - delete `_write_empty_plan_update_if_missing` and its call
    - require a real `plan_update.json` from strategist/caller for completed empirical runs
    - completed supplied selection must not synthesize `plan_update.json`
    - agent-driven completed closeout still writes a real `plan_update.json`

- After terminal experiment state is recorded, merge that experiment into `research_state.json`.
    - This is a controller side effect, not a phase.
    - No new phase appears in `state.json` or the ledger.
    - Usage-limit retry does not merge incomplete experiments.

- In research state merge:
    - if `source_experiment` already exists in `experiment_index`, return state as idempotent no-op
    - for any `completed_*` summary, require direct reads of `selected_plan.json`, `research_spec.json`, `confirmatory_evaluation_result.json`, `lineage.json`, and `plan_update.json`
    - optional artifact reads stay only for non-completed terminal outcomes
    - merge typed reusable components only from `plan_update.reusable_components`
    - require lineage worktree and non-empty lineage changed files when reusable components are declared
    - delete auto `_merge_lineage_reusable_component`

- Before context rendering, load `research_state.json` and render existing continuation keys from it:
    - `prior_experiments` from `experiment_index`, keeping lineage/worktree visible there
    - `pending_followups` and `future_experiment_ideas` from `idea_index` records with `status == "pending"`
    - `do_not_repeat` from completed, blocked, and superseded ideas plus blocker records
    - `reusable_implementations` from strategist-curated reusable component records only
    - `metric_history` and `best_metric_runs` from metric observations

- Exclude `research_state.json` from generic `memory_context`; expose it through explicit continuation fields instead.

- Strategist prompt changes:
    - prefer highest-priority pending `idea_index` records
    - cite `selected_idea_ids`
    - use `fresh_selection_reason` only when not selecting from memory
    - fresh selections must explain why pending followups are blocked, exhausted, or lower value
    - emit typed followups with enough detail to dedupe, prioritize, and falsify

- Controller still does not auto-select experiments. Strategist chooses; controller validates, stores, dedupes, and statuses memory.

## Merge Rules

- Idempotency:
    - if `source_experiment` is already in `experiment_index`, merge is no-op
    - `experiment_index` is the only idempotency source

- Selected idea status:
    - `completed_*` outcome -> selected ideas become completed
    - `prerequisites_failed`, `blocked`, `invalid` -> selected ideas become blocked
    - `run_failed` -> selected ideas remain pending with operational blocker notes
    - `no_op` -> no idea status changes

- New followups:
    - valid dedupe miss -> create pending idea in `idea_index`
    - valid dedupe hit -> append source experiment if absent, do not duplicate
    - preserve evidence basis and falsifying evidence from completed evidence or exploratory diagnostics
    - priority must be `0.0 <= priority <= 1.0`
    - sort pending ideas by priority descending, then idea id

- Learning:
    - merge typed `learning_updates` from `PlanUpdate`
    - merge typed blockers into `known_blockers`
    - apply `superseded_idea_ids` to matching idea records
    - preserve source experiment ids for all learned claims
    - invalid references fail loudly for completed merges

- Metrics:
    - record numeric leaves from `confirmatory_evaluation_result.metrics`
    - ignore booleans and non-numeric values
    - derive best runs from metric observations; do not store separate best-run state

- Reuse:
    - index typed reusable components from `PlanUpdate`
    - controller attaches worktree path and changed files from `lineage.json`
    - lineage-only completed experiments do not create reusable components
    - seed worktree suggestions must come from existing reusable component paths or selected idea suggestions

## Test Plan

- Schema tests:
    - typed `PlanUpdate` cards validate
    - old string followups fail
    - followups require evidence basis and falsifying evidence
    - reusable component card omits worktree/files
    - `SelectedPlan` requires `fresh_selection_reason` when no idea IDs selected
    - invalid selected idea/component refs fail before `selected_plan.json` is written

- Research state contract:
    - empty state creation
    - created state has `idea_index`
    - created state has no `active_brief`
    - created state has no `merged_experiments`
    - malformed old string plan updates fail
    - malformed `research_state.json` fails
    - completed merge fails if any required completed artifact is missing
    - completed merge accepts real empty `plan_update.json`
    - duplicate merge is no-op via `experiment_index`

- Merge behavior:
    - idempotent merge
    - followup dedupe
    - selected idea status transitions
    - blocker indexing
    - reusable component indexing
    - reusable component merge fills worktree/files from lineage
    - metric observations and best-run rendering

- Flow behavior:
    - terminal experiment updates research state
    - usage-limit retry does not merge incomplete experiment
    - completed supplied selection does not synthesize `plan_update.json`
    - agent-driven completed closeout writes real `plan_update.json`
    - no new phase appears in `state.json` or ledger

- Context tests:
    - `continuation_summary.json` rendered from `research_state.json`
    - current continuation keys preserved
    - `research_state.json` excluded from generic `memory_context`
    - completed ideas appear in `do_not_repeat`
    - pending followups render from `idea_index`
    - prior experiment lineage/worktree remains visible through `prior_experiments`
    - lineage-only completed experiment does not appear in `reusable_implementations`
    - `reusable_implementations` contains only strategist-curated reusable components

- Prompt tests:
    - Strategist prompt requires pending memory use or fresh-selection justification
    - fresh-selection justification accounts for pending followups
    - Strategist prompt requires typed followups and dedupe keys
    - Strategist prompt requires selected idea citations when selecting from memory

## Assumptions

- Single canonical artifact is preferred: `memory/research_state.json`.
- No backward compatibility for old string `plan_update.json`, current unstaged schema, or old research artifacts.
- No compatibility shims, no legacy normalization, no multi-artifact memory split.
- `research_brief` remains canonical in run spec/context, not program memory.
- Controller owns memory/status/dedupe/reference validation.
- Strategist owns research judgment.
- Tests should enforce critical contract behavior, not implementation shape beyond public JSON contracts.
