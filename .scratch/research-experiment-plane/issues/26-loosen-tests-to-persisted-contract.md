# Loosen tests to persisted contract

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Refactor tests that pin private flow shape so they assert the Research Experiment Controller's persisted behavior instead.

The review found tests that assert exact fake-runtime call order, prompt substrings, private shell helpers, specific session DB wiring, and cleanup behavior. These tests make simplification harder without protecting the product contract.

Target behavior: tests should assert run directories, canonical artifacts, terminal outcomes, ledger records, worktree/evaluator boundaries, mirror best-effort behavior, and public CLI/shell behavior. They should avoid exact helper ordering unless ordering is a product contract.

Motivation: the PRD says tests should focus on external behavior so refactors remain possible. The current test suite protects too much implementation detail, especially around agent prompts and durable shell internals.

## Acceptance criteria

- [x] End-to-end tests still verify full Research Run artifact chain and terminal Research Outcome.
- [x] Material revision tests assert material critique artifact, summary outcome, and ledger categories instead of prompt substrings.
- [x] Durable shell tests assert public shell behavior and generic metadata, not private runner wiring.
- [x] Mirror tests compare required params/tags/metrics/artifacts without unnecessary ordering assumptions.
- [x] Worktree tests keep create/preserve/dirty-reuse guards and drop automatic cleanup expectations.

## Blocked by

- `.scratch/research-experiment-plane/issues/21-collapse-experiment-flow-single-pipeline.md`
- `.scratch/research-experiment-plane/issues/23-remove-usage-limit-worktree-cleanup.md`
- `.scratch/research-experiment-plane/issues/24-decide-material-revision-scope.md`
- `.scratch/research-experiment-plane/issues/25-trim-nonessential-hardening.md`

## Comments

### Implementation

- Loosened materiality, shell, mirror, and repair tests toward persisted artifacts/events.
