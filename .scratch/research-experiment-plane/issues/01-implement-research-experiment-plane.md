# Implement Research Experiment Plane

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane PRD: `.scratch/research-experiment-plane/PRD.md`

## What to build

Implement the Research Experiment Plane described in the PRD. Treat the PRD, root glossary, and ADR 0001 as the source of truth.

This is a large feature. If assigned as smaller AFK work, split this issue into tracer-bullet slices before coding.

## Acceptance criteria

- [ ] Research Run Spec supports the agreed single-file shape, including Research Brief, budgets, worktree config, MLflow config, Codex config, implementation repair limit, and `stop_on_prerequisites_failed`.
- [ ] Research Run snapshot, run directory, ledger, and resume behavior are implemented.
- [ ] Hatchet integration remains a minimal Durable Execution Shell with generic metadata only.
- [ ] Shared control-plane primitives are extracted only where genuinely reusable.
- [ ] One Research Run can execute up to `max_experiments`, with each Research Experiment having one selected plan and one terminal Research Outcome.
- [ ] Research agents follow agreed thread lifetimes and permission boundaries.
- [ ] Canonical Research Artifacts are validated at boundaries with thin Pydantic models.
- [ ] Material revisions use controller-owned Material Revision Policy and fresh Critic review when required.
- [ ] Data/prerequisite audit can produce `prerequisites_failed` and stop the Research Run when configured.
- [ ] Experiment Worktrees are created, preserved, and dirty reuse is rejected.
- [ ] Implementation verification repair loop respects `implementation.max_repairs`.
- [ ] Evaluator Workspace uses manifest paths, `eval_scratch`, and `eval_outputs`; no `eval_inputs` subtree.
- [ ] Evaluation Boundary Audit checks worktree changes and locked artifact hashes.
- [ ] MLflow mirror is best-effort at terminal experiment end, recursive over run artifacts, and never controls workflow success.
- [ ] Tests cover the external behavior called out in the PRD.

## Blocked by

None.

## Comments
