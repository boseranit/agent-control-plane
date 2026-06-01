# Consolidate low-risk flow cleanups

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

After the behavioral simplifications land, do a deletion-first cleanup pass over low-risk duplicate helpers and derived registries.

Candidates from review: duplicated completed-outcome registries, one-use prompt builders, unused helper arguments, shallow default runner wrappers, repeated command coercion, duplicated material alias maps, and fixed artifact-name maps that can be expressed directly.

This issue should not change Research Experiment behavior. It is cleanup after the shape is simpler.

Motivation: doing this before the main flow collapse risks churn. Doing it after removes leftover clutter while tests already guard the persisted contract.

## Acceptance criteria

- [x] Duplicate completed-outcome registries are consolidated to one source of truth.
- [x] One-use helpers are inlined only where the caller becomes clearer.
- [x] Repeated command declaration coercion is normalized without reducing dict/model convenience in tests or callers.
- [x] Unused parameters and shallow wrappers are removed.
- [x] No behavior, artifact shape, or ledger event changes.

## Blocked by

- `.scratch/research-experiment-plane/issues/26-loosen-tests-to-persisted-contract.md`

## Comments

### Implementation

- Consolidated completed outcomes and command declaration coercion; removed unused worktree cleanup helper.
