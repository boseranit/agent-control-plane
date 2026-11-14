# MLflow Hyperliquid UI

This guide preserves the local MLflow setup that used to live in
HyperliquidMomentum, adapted for agent-control-plane.

MLflow is a review mirror only. For Research Experiment Controller runs, the run
directory, state, ledger, and artifacts remain authoritative.

## Legacy Store

The recovered HyperliquidMomentum SQLite store is here:

```text
runs/imported-hyperliquid-momentum-legacy/mlflow/mlflow.db
```

The archive also has `README.md` and `MANIFEST.sha256`. The whole `runs/`
directory is intentionally ignored by git.

The old `mlruns/` artifact directory was not recoverable. The service still uses
this ACP path as the artifact root for restored or future artifacts:

```text
runs/imported-hyperliquid-momentum-legacy/mlruns
```

The recovered database has the old experiment metadata and run metrics, but some
artifact links may still point at deleted HyperliquidMomentum paths.

SQLite may create sidecar files while the UI is running:

```text
mlflow.db-shm
mlflow.db-wal
```

These stay under ignored `runs/` storage with the main database.

## Run UI Directly

From `/home/boser/agent-control-plane`:

```bash
ACP=/home/boser/agent-control-plane
pixi run -e dev mlflow ui \
  --backend-store-uri sqlite:///$ACP/runs/imported-hyperliquid-momentum-legacy/mlflow/mlflow.db \
  --default-artifact-root file://$ACP/runs/imported-hyperliquid-momentum-legacy/mlruns \
  --host 0.0.0.0 \
  --port 5000 \
  --allowed-hosts localhost,127.0.0.1,192.168.1.104:5000,192.168.* \
  --cors-allowed-origins http://localhost:5000,http://127.0.0.1:5000,http://192.168.1.104:5000
```

Open:

```text
http://localhost:5000
http://192.168.1.104:5000
```

For the imported runs, select the `hyperliquid-follow-orchestrator` experiment.
Runs are named like `EXP-2026-05-24-001`.

Useful tabs:

- `Parameters`: cycle, loop, budget, and config fields.
- `Metrics`: flattened experiment metrics and command metrics.
- `Artifacts`: mirrored run files when artifact files exist.
- `Metadata`: run timing and status.

## User Service

The tracked service template is:

```text
systemd/user/mlflow-hyperliquid.service
```

Install or refresh it:

```bash
mkdir -p /home/boser/.config/systemd/user
cp /home/boser/agent-control-plane/systemd/user/mlflow-hyperliquid.service \
  /home/boser/.config/systemd/user/mlflow-hyperliquid.service
systemctl --user daemon-reload
systemctl --user enable --now mlflow-hyperliquid.service
```

Check it:

```bash
systemctl --user status mlflow-hyperliquid.service
journalctl --user -u mlflow-hyperliquid.service -f
```

Validate the tracked unit after edits:

```bash
systemd-analyze verify --user systemd/user/mlflow-hyperliquid.service
```

## Firewall And Linger

If `ufw` is enabled, allow only the LAN subnet:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 5000 proto tcp
sudo ufw status
```

To keep the user service running after logout:

```bash
sudo loginctl enable-linger boser
```

The MLflow UI has no authentication in this setup. Keep it on a trusted LAN and
do not expose port `5000` to the internet.

## Filestore Migration

If a file-backed `mlruns/` store is recovered later, stop the service and migrate
it into the ACP SQLite store:

```bash
ACP=/home/boser/agent-control-plane
systemctl --user stop mlflow-hyperliquid.service
pixi run -e dev mlflow migrate-filestore \
  --source /path/to/recovered/mlruns \
  --target sqlite:///$ACP/runs/imported-hyperliquid-momentum-legacy/mlflow/mlflow.db \
  --progress
systemctl --user start mlflow-hyperliquid.service
```

## New Controller Runs

For new Research Experiment Controller runs, configure MLflow through the
controller's mirror settings. Keep MLflow-specific setup behind the mirror
adapter; do not make controller state depend on the MLflow store.

Use the external controller archive for new HLM research:

```text
/home/boser/agent-control-plane-runs/programs/<program-id>/runs/<research-run-id>
```

The legacy HyperliquidMomentum config shape was:

```yaml
mlflow:
  tracking_uri: sqlite:///mlflow.db
  experiment_name: hyperliquid-follow-orchestrator
```

In ACP, prefer a tracking URI rooted under the controller runtime archive or the
specific Research Run directory, for example:

```yaml
mlflow:
  tracking_uri: sqlite:////home/boser/agent-control-plane-runs/programs/<program-id>/runs/<research-run-id>/mlflow/mlflow.db
  experiment_name: <research-run-id>
```

Pair that with specs using:

```yaml
research_program_root: /home/boser/agent-control-plane-runs/programs/<program-id>
target_repository: /home/boser/HyperliquidMomentum
data_root: /mnt/redbackup/data
experiment_data_root: /mnt/redbackup/experiment-data
worktree:
  create: true
```

With `research_program_root`, controller runs live under `runs/`, preserved
worktrees under `worktrees/`, and continuation memory under `memory/`. Start at
the archive `INDEX.md`, then follow the program, generated run-catalog, and
per-run indexes to inspect terminal Experiments.

The mirror adapter should log experiment params, tags, numeric metrics, and run
directory files, but failures in MLflow mirroring must not change the official
experiment outcome.
