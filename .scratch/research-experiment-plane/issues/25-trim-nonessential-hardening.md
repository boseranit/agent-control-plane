# Trim nonessential hardening

Status: done
Label: ready-for-agent
Type: AFK

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Remove or narrow guards that mainly defend low-probability malformed state rather than the core Research Experiment workflow.

The review found several areas where code protects against edge cases beyond the PRD's minimal posture: unsupported spec-key rejection, duplicated Evaluator Workspace manifest aliases, manifest tamper/path-mode hardening, and broad tests around private defensive branches. These add cognitive load and make the workflow feel more rigid than required.

Target behavior: keep the important boundaries: valid Research Run Spec basics, canonical artifact validation at agent/controller boundaries, Evaluator Workspace with manifest paths, locked artifact hashes, and worktree mutation audit. Remove compatibility aliases and extra defensive branches that are not needed for normal local operation.

Motivation: the PRD explicitly says avoid broad validations merely because possible. The user expects to inspect failures and adapt the workflow, not guard every low-probability case upfront.

## Acceptance criteria

- [x] Evaluator manifest keeps only fields needed by the Evaluator and boundary audit.
- [x] Boundary audit still fails on Experiment Worktree mutation and locked artifact hash changes.
- [x] Research Run Spec loader keeps required fields/defaults but drops nonessential unsupported-key policing unless needed for a current contract.
- [x] Tests focus on normal contract and important boundary failures, not tampered-manifest compatibility modes.
- [x] No weakening of core artifact-boundary Pydantic validation.

## Blocked by

- `.scratch/research-experiment-plane/issues/21-collapse-experiment-flow-single-pipeline.md`

## Comments

### Implementation

- Trimmed evaluator manifest aliases/tamper tests and removed unsupported spec-key policing.
