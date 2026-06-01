# Shared artifact/state primitives

Status: completed
Label: done

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add shared JSON artifact/state primitives for deterministic artifact writes, JSONL ledgers, text writes, file hashing, and artifact hash manifests. Keep this package limited to deep reusable Control-Plane Workflow primitives.

## Acceptance criteria

- [x] Shared artifact IO writes stable sorted JSON and append-only JSONL.
- [x] Helpers reject malformed/non-object artifact payloads with clear errors.
- [x] File hashing and hash-manifest helpers support locked artifact verification.
- [x] Tests cover persisted output shape and error cases.

## Blocked by

None - can start immediately

## Comments

- Implemented in `agent_control_plane/control_plane/json_artifacts.py`.
- Verified with `pixi run test` (`88 passed`).
