# End-to-end fake runtime and boundary alignment

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add end-to-end fake-runtime coverage and perform the final package boundary alignment check against the PRD, implementation plan, glossary, and ADR 0001. Fix only direct boundary violations found by the check.

## Acceptance criteria

- [ ] Fake runtime test drives a full Research Run through terminal Research Outcome.
- [ ] Full test suite passes.
- [ ] Research code does not import Hatchet or MLflow outside adapter modules.
- [ ] Shared package contains only deep reusable primitives.
- [ ] Task Control Plane lifecycle and final-commit semantics remain unchanged.
- [ ] Parent issue acceptance criteria are traceable to the smaller issues.

## Blocked by

- `.scratch/research-experiment-plane/issues/02-shared-artifact-state-primitives.md`
- `.scratch/research-experiment-plane/issues/03-shared-usage-limit-agent-runtime.md`
- `.scratch/research-experiment-plane/issues/04-shared-structured-command-runner.md`
- `.scratch/research-experiment-plane/issues/05-shared-boundary-audit-helpers.md`
- `.scratch/research-experiment-plane/issues/06-research-run-spec-loader-snapshot-model.md`
- `.scratch/research-experiment-plane/issues/07-research-artifact-models-outcome-enum.md`
- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/09-deterministic-context-pack-prior-run-synthesis.md`
- `.scratch/research-experiment-plane/issues/10-research-agents-prompt-boundaries.md`
- `.scratch/research-experiment-plane/issues/11-controller-phase-skeleton-no-op-blocked-outcomes.md`
- `.scratch/research-experiment-plane/issues/12-data-audit-prerequisites-stop-policy.md`
- `.scratch/research-experiment-plane/issues/13-experiment-worktree-implementation-repair-path.md`
- `.scratch/research-experiment-plane/issues/14-evaluator-workspace-boundary-audit.md`
- `.scratch/research-experiment-plane/issues/15-research-run-mirror-mlflow-adapter-wiring.md`
- `.scratch/research-experiment-plane/issues/16-durable-shell-hatchet-adapter.md`
- `.scratch/research-experiment-plane/issues/17-research-cli-worker-entrypoints.md`
- `.scratch/research-experiment-plane/issues/18-material-revision-feature-spec-artifacts.md`

