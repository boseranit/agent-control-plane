# HyperliquidMomentum Controller Migration Observations

These notes came from removing the old `research/orchestrator`,
`research/prompts`, and `research/schemas` surfaces from
`/home/boser/HyperliquidMomentum` after the controller moved to
`/home/boser/agent-control-plane`.

## Observations

- The retained `research/loops/*.md` files are repo-specific research steering,
  not controller implementation. The agent-control-plane Research Run Spec may
  want an explicit field for a repo-local loop/spec path so these files can
  remain in the target repository while controller prompts, schemas, state, and
  mirrors stay in agent-control-plane.
- The old run history shows repeated schema failures where agents produced
  structured arrays or objects but legacy schemas expected strings. The current
  design's strict schemas should keep strict validation, but allow natural list
  or object shapes for fields such as planned files, implementation steps,
  risks, and evidence, then normalize them at the controller boundary.
- The old runner used `ORCHESTRATOR_RUN_DIR` and sometimes `HLM_DATA_ROOT`.
  The design spec uses `RESEARCH_RUN_DIR`, `RESEARCH_DATA_ROOT`,
  `RESEARCH_EXPERIMENT_DATA_ROOT`, `HLM_DATA_ROOT`, and `RESEARCH_REPO_ROOT`;
  migration docs or command manifests should make that rename explicit for
  legacy experiment scripts.
- The old HyperliquidMomentum MLflow setup was repo-local and service-specific.
  The design spec's provider-neutral mirror interface is the right replacement;
  avoid reintroducing target-repo systemd service templates or direct MLflow
  imports outside the mirror adapter.
- HyperliquidMomentum still has dirty registered Git worktrees under
  `.worktrees/peer-residuals`. The cleanup intentionally preserved them. This
  matches the design spec's rule that worktrees are preserved and dirty existing
  worktrees are rejected rather than silently cleaned.

## Recovery Follow-Up

- Recoverable legacy artifacts were copied into
  `runs/imported-hyperliquid-momentum-legacy/`. This operational archive is
  ignored by Git through the existing `runs/` ignore rule.
- The recovered MLflow database came from the deleted SQLite file still held
  open by the local MLflow process. It passed `PRAGMA integrity_check` and
  contains 93 runs.
- The original `research/experiments` directory was not recoverable in full.
  Six worktree-local `metrics.json` files survived under registered
  HyperliquidMomentum experiment worktrees and were copied into the archive.
- The `mlruns/` artifact directory was not recoverable from local disk. No copy
  was found under `/home/boser`, and no deleted artifact files were open in
  running processes. The recovered MLflow database still records artifact URIs
  pointing at the deleted HyperliquidMomentum `mlruns` paths.
- The migrated MLflow setup notes now live in
  `docs/usage/mlflow-hyperliquid.md`.
