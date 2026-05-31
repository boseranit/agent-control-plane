# Shared artifact/state primitives

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Add shared JSON artifact/state primitives for deterministic artifact writes, JSONL ledgers, text writes, file hashing, and artifact hash manifests. Keep this package limited to deep reusable Control-Plane Workflow primitives.

## Acceptance criteria

- [ ] Shared artifact IO writes stable sorted JSON and append-only JSONL.
- [ ] Helpers reject malformed/non-object artifact payloads with clear errors.
- [ ] File hashing and hash-manifest helpers support locked artifact verification.
- [ ] Tests cover persisted output shape and error cases.

## Blocked by

None - can start immediately

