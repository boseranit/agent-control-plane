# eda/ tree - on-disk schema

Two locations, so heavy artifacts never bloat the repo:

- **records tree** (`edaDir`, default `eda/<slug>`) - small human-diffable text,
  committed to git.
- **artifact root** (`dataRoot`, default `<edaDir>/artifacts`) - heavy binaries,
  usually git-ignored or pointed at a scratch/NFS root.

## Records tree (git-committed)

```
eda/<slug>/
├── PRD.md                                  # idea, data pointers, baseline, success gate
├── INDEX.md                                # manifest: hypotheses ↔ experiments ↔ verdicts table
├── hypotheses/
│   └── H01-<title>.md                      # markdown + frontmatter (schema below)
├── experiments/
│   ├── EXP-0007-spec.json                  # frozen, pre-registered input spec
│   └── EXP-0007-run.py                     # self-contained experiment script
├── results/
│   └── EXP-0007-result.json                # metrics + verdict metadata (schema below)
└── notebook/
    └── <slug>.ipynb                        # final notebook
...
```

IDs are zero-padded and monotonic: `H01...`, `EXP-0001...`. Spec, script, result,
and artifacts for one experiment all key on the same `EXP-NNNN`.

## Artifact root (NOT git) - `<dataRoot>/`

```
models/    EXP-0007_coeffs.json          # model params as JSON - NEVER pickle
oos/       EXP-0007_oos_pred.<ext>       # out-of-sample predictions (parquet/feather/sds/npz)
nulls/     EXP-0007_shuffle_null.<ext>    # permutation-null draws
plots/     EXP-0007_<name>.png
...
```

Keyed per-experiment so re-runs are idempotent.

## Hypothesis record - `hypotheses/H01-<title>.md`

Frontmatter:

```yaml
---
id: H01
slug: short-title
status: ready-to-run     # ready-to-run | needs-data | survived | killed | inconclusive
experiments: [EXP-0007]  # backrefs, filled as experiments are created
---
```

Body sections: `## Thesis` (mechanism, one paragraph - the edge you claim) ·
`## Signal` (exact construction/formula) · `## Target / universe / horizon` ·
`## Gate` (numeric pass metric + threshold + direction, set before running) ·
`## Leakage guard` · `## Decision` (survived | inconclusive | killed + the
driving metric).

## Experiment result - `results/EXP-0007-result.json`

Field list:

- `exp_id`, `hypothesis_id`, `spec_path`
- `status` - `ran_ok | error`; `verdict` - `survived | inconclusive | killed`
- `gate_metric`, `gate_value`, `gate_threshold`, `gate_direction` (`above|below`)
- `metrics` - `{ic, ic_t, sharpe, n_units, ci_low, ci_high, shuffle_null_p}`
  (`n_units` = independent observations, not rows)
- `family_size`, `bh_adjusted_p` - family-wise FDR fields, filled at selection
- `provenance` - `{seed, data_range, git_sha}` (reproducibility: variants must
  share eval rows + seed with their foil)
- `artifacts` - `{model, oos, nulls, plots}` (artifact-root paths)
- `adversary` - `[{lens, killed, reason}]` from the verify stage
- `leakage_checks` - `[string]`
- `notes`

## Persistence protocol

- On experiment start, freeze `experiments/EXP-NNNN-spec.json` **before** any
  compute. Never mutate a frozen spec - a redesign gets a new `EXP` id.
- On finish, write `results/EXP-NNNN-result.json`. These per-`EXP` files are the
  source of truth; parallel implementers write distinct paths, so no lock or
  shared append is needed and a crash never truncates prior state.
- `INDEX.md` is assembled once at the end by the single owner (no concurrent
  writers). Add an append-only `runs/ledger.jsonl` only if step-level replay is
  wanted - the per-`EXP` files already give recovery.
- At run end, promote one durable finding to the harness memory if available.