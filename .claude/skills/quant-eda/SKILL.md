---
name: quant-eda
description: >-
  Autonomous, project-agnostic multi-agent exploratory data analysis for a
  quantitative signal: brainstorm hypotheses, pre-register controlled
  experiments, run them in parallel, adversarially attack the survivors with
  family-wise FDR control, and synthesize a Jupyter notebook. Use when someone
  has a strategy idea plus preliminary data/model and wants rigorous EDA to
  find a statistically significant signal; use when the deliverable is a
  research notebook; use when the request mentions hypothesis generation,
  experiment design, or a statistics adversary.
---

# Autonomous quant EDA

Turn a strategy idea + preliminary data/model into a **statistically defensible
notebook**. A `Workflow` engine fans work across four roles; **you own the
notebook and the final judgment**. Nothing is hardcoded to one project - all
project specifics arrive as `args` (Project config below).

Governing idea - **pre-register then attack**: every experiment names its one
changed variable, its null/foil control, and its numeric success gate *before*
it runs; a **statistics adversary** then tries to kill each positive, and only
findings that survive the attack *and* clear family-wise FDR ship.

The four roles (all run inside the engine):

| Role | Does |
| --- | --- |
| Hypothesis generator | angle-diverse candidate hypotheses grounded in the real data profile |
| Experiment designer | freezes a pre-registered, controlled, numeric-gated spec per hypothesis |
| Implementer | writes + runs a self-contained script, emits result JSON + artifacts |
| Statistics adversary | 3 diverse lenses attack each positive; leakage is a hard veto |

## Step 1 - gather inputs + project config

Hold these (ask once if the idea or data pointer is missing - never guess a dataset):

- **idea** - the strategy thesis / motivation
- **data** - how to load the panel/artifacts (paths, loader calls, cached files)
- **baseline** - a shipped headline number to reproduce, if any (empty is fine)
- **slug** - short kebab id (e.g. `momentum-reversal`)
- **scale** - `quick`, default, or a `+Nk` token budget

Project config - how to adapt to *this* codebase (read a repo `eda.config.json`
if present, else infer + confirm):

- **pythonCmd** - how to run Python here (`python`, or a wrapper like
  `pixi run --manifest-path <env>/pixi.toml python`, `uv run python`, ...)
- **conventions** - a short string of project coding rules injected into every
  code-writing agent (e.g. dataframe library, house loaders, style). Leave empty
  for none.
- **edaDir** - where the records tree lives (default `eda/<slug>`)
- **dataRoot** - where heavy artifacts go (default `<edaDir>/artifacts`; override
  to a scratch/NFS root for large data)

## Step 2 - scaffold the eda/ tree

Create the tree per `reference/eda-tree.md`:

```
<edaDir>/{hypotheses,experiments,results,notebook}/   INDEX.md   PRD.md
```

Write `PRD.md` (idea, data pointers, baseline, success gate). Completion: the
four dirs + `PRD.md` exist.

## Step 3 - launch the engine

Invoke the workflow, passing the gathered inputs as `args`:

```
Workflow({
  scriptPath: "<this skill dir>/quant-eda.workflow.js",
  args: { slug, idea, data, baseline, edaDir, dataRoot, pythonCmd, conventions, scale }
})
```

It runs autonomously: Recon (halts if a given baseline won't reproduce) →
Hypothesize → **all shortlisted hypotheses fan out concurrently**, each through
Design → Implement → Verify with no cross-hypothesis barrier → family-wise FDR →
a synthesis package that brings them back together. Completion: the workflow
returns; every shortlisted hypothesis has a `results/EXP-*-result.json` on disk.

Do **not** build the notebook inside the engine - see the ownership rule.

## Step 4 - own the notebook (single owner)

The jupyter MCP renumbers cell indices on every insert/delete, so a second
writer's index goes silently stale. **One owner per notebook - that is you.**
Read the durable `results/EXP-*-result.json` files from disk (not the possibly
truncated workflow return) and build `<edaDir>/notebook/<slug>.ipynb`:

```
mcp__jupyter__use_notebook(name, path=<abs .ipynb>)  # activate + kernel
mcp__jupyter__read_notebook(brief=True)              # map indices before ANY indexed op
mcp__jupyter__insert_cell(cell_index=-1, type="markdown", ...)
mcp__jupyter__insert_execute_code_cell(...)          # code: insert + run in one step
mcp__jupyter__execute_cell(index, stream=True)       # after every edit, read traceback
```

If the first op errors (stale HTTP), `mcp__jupyter__connect_to_jupyter(url, token)`, then retry.

Notebook shape (optimize for *assumptions visible*, not code visible;
markdown-before-code; keep cells short; push loading/joins/eval into a module):

1. **Thesis** - the mechanism in one paragraph, before any plot.
2. Per **surviving** hypothesis: signal formula → target/universe/horizon →
   result (metric + CI + null-p + FDR-adjusted p) → the adversary's checks → verdict.
3. **Killed hypotheses** appendix - what died and which attack killed it. This is
   the honest core; do not hide it.
4. **Negative controls** - show the foil where the effect vanishes.

## Step 5 - promote memory + final judgment

- Assemble `INDEX.md`: the hypotheses ↔ experiments ↔ verdicts table (the engine
  drafts it; confirm it).
- If the harness has a durable memory, record one finding: survivors, killed,
  headline metric + CI + null-p + FDR-adjusted p, data range, artifact paths,
  leakage verdict.
- Give the plain-words judgment: is there a signal, how strong, what killed the
  rest, what to run next.

## Guardrails (enforced by the engine, honored by you)

- **Pre-register a numeric gate**: the gate is recomputed downstream from the
  frozen threshold - the implementer reports numbers, it does not declare the pass.
- **Family-wise FDR** (Benjamini-Hochberg) across the tested family - a lone
  survivor among K tests is expected under the null.
- **Leakage is a hard veto**: the leakage lens reads the actual script.
- **Trim outliers only on the fit/train set - never OOS.**
- **Do not mistake underpowered for dead** - report the gate's power first.

On-disk schemas: `reference/eda-tree.md`.
