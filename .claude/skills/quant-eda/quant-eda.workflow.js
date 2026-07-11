export const meta = {
  name: 'quant-eda',
  description: 'Autonomous, project-agnostic quant EDA: recon+baseline, angle-diverse hypotheses, pre-registered controlled experiments, adversarial verification with family-wise FDR, synthesis package',
  phases: [
    { title: 'Recon', detail: 'load data, profile, reproduce baseline', model: 'claude-sonnet-5' },
    { title: 'Hypothesize', detail: 'angle-diverse generators + dedup/rank barrier' },
    { title: 'Design', detail: 'pre-register a controlled spec per hypothesis' },
    { title: 'Implement', detail: 'write + run a self-contained experiment script, then characterize the result', model: 'claude-sonnet-5' },
    { title: 'Verify', detail: '3 diverse adversary lenses attack each positive' },
    { title: 'Select', detail: 'family-wise FDR across the tested family' },
    { title: 'Synthesize', detail: 'patch result JSON, write INDEX, return brief', model: 'claude-sonnet-5' },
  ],
}

// ---------- inputs (all optional; project specifics arrive here, nothing hardcoded) ----------
// Some harnesses deliver `args` as a JSON-encoded string; parse it so keys resolve.
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const SLUG = A.slug || 'investigation'
const IDEA = A.idea || '(no idea provided — read PRD.md)'
const DATA = A.data || '(no data pointers in PRD.md)'
const BASELINE = A.baseline || ''                          // shipped headline number to reproduce, if any
const EDA = A.edaDir || `eda/${SLUG}`                        // text/records tree (relative to project root by default)
const DROOT = A.dataRoot || `${EDA}/artifacts`                // heavy binary artifacts (override to a scratch/NFS root)
const PY = A.pythonCmd || 'python'                           // how to run python here (e.g. a pixi/conda/uv wrapper)
const CONV = A.conventions ? `\nProject conventions (follow exactly): ${A.conventions}\n` : ''
const FDR_Q = typeof A.fdrQ === 'number' ? A.fdrQ : 0.10

const QUICK = A.scale === 'quick'
const FLEET = budget.total ? Math.max(4, Math.floor(budget.total / 120000)) : null
const TOP_K = A.topK || (FLEET ? Math.min(8, FLEET) : QUICK ? 3 : 5)

// ---------- doctrine (universal quant-research rigor; no project specifics) ----------
const DESIGNER_DOCTRINE = `EXPERIMENT DESIGNER protocol (pre-register BEFORE running):
- Name the ONE ingredient the test changes; keep the rest of the pipeline identical vs the control.
- A null/foil control is MANDATORY: collapse the thesis variable to its trivial level (shuffle it, zero it, or swap a matched random surrogate) and confirm the effect vanishes. Score the foil on the SAME eval rows & seed as the main test.
- Pre-register the success metric AND its power: state the plausible effect size, the effective n (independent observations, not rows), the metric's SE, and the probability the gate passes under the alternative. A gate with <50% power at the plausible effect cannot yield a real negative — fix it before running.
- Target discipline: anchor the feature window and the label/return window so the feature's own effect is NOT inside the target (window overlap is the classic look-ahead that inflates OOS performance). Drop degenerate rows where the label is mechanically fixed.
- Split: prefer expanding/rolling walk-forward over a single static holdout; single-window gates hide real-but-weak edges. Count independent units per split from the data itself, not from row counts.
- Fairness: every variant scored on identical eval rows, the same seed, the same bootstrap scheme, the same selection metric.
- The frozen spec governs the CLAIM, not curiosity: a descriptive characterization pass after the pre-registered numbers is expected and unconstrained by the spec. It can sharpen the interpretation, never the verdict.`

const ADVERSARY_DOCTRINE = `STATISTICS ADVERSARY kill-list (attack the positive; default to "not proven"):
- Leakage / look-ahead: perturb FUTURE rows and confirm trailing features are unchanged; check feature-vs-label window overlap; read the actual code, never trust a comment.
- Outliers: trim ONLY the fit/train set, NEVER the OOS/test set — scoring a trimmed holdout is selection-on-the-outcome and manufactures performance.
- In-sample vs OOS on RAW predictions: any latch/winsor/clip/scale in the eval can mask overfit — also check the unprocessed prediction.
- Effective sample: observations sharing one event/day are ~1 independent draw; deflate the t-stat/Sharpe for overlap and autocorrelation before trusting significance.
- Multiple testing: a lone-spec t~2 is a threshold-straddling artifact; demand stability across reasonable spec choices and across time halves. Highly-correlated variants can't be ranked on a few hundred observations.
- Regime / non-stationarity: check per-period means and rolling metric sign; pooled-positive but per-period-negative is a regime artifact, not skill.
- Base-rate control: does a random drop of the same fraction of rows reproduce the "improvement"? A conditioning gate that merely discards data is not an edge.
- Overfit: fit a low-complexity equivalent through the same pipeline; if it matches within noise, the extra structure is unsupported.
- Power: do NOT call an underpowered null "dead" — report the gate's power at the plausible effect first; a null on a weak gate is uninformative, not negative.`

const CHARACTERIZE_DOCTRINE = `CHARACTERIZATION principles (a descriptive pass AFTER the pre-registered numbers; it informs interpretation, never the verdict):
- An aggregate statistic is a summary, not an understanding. Locate the effect: where in the signal's range, when within the horizon, in which slice of the sample it actually lives.
- Chase entanglement: name the most mundane variable that could paint the same picture, measure how tied it is to the signal, and ask both whether the effect survives with it held fixed and whether it alone reproduces it.
- Follow the result, not a checklist: let each answer choose the next probe; stop when the interpretation stops moving.
- A null deserves the same pass — flat-everywhere and real-but-diluted are different nulls with different follow-ups.
- End by restating the finding in one sharper sentence, and by naming the strongest unresolved question phrased so it could be pre-registered next round.`

// ---------- schemas ----------
const RECON_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['baseline_reproduced', 'n_units', 'range', 'columns', 'profile_note'],
  properties: {
    baseline_reproduced: { type: 'boolean' },
    baseline_note: { type: 'string' },
    n_units: { type: 'number' },                    // independent observations (days/events), not rows
    range: { type: 'string' },                       // span of the sample (dates / index range)
    columns: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['name', 'dtype', 'role'],
      properties: { name: { type: 'string' }, dtype: { type: 'string' }, role: { type: 'string' }, notes: { type: 'string' } } } },
    regimes: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
    profile_note: { type: 'string' },
  },
}
const CANDIDATE = {
  type: 'object', additionalProperties: false,
  required: ['title', 'mechanism', 'signal', 'target', 'universe', 'horizon', 'why_might_work'],
  properties: {
    title: { type: 'string' }, mechanism: { type: 'string' }, signal: { type: 'string' },
    target: { type: 'string' }, universe: { type: 'string' }, horizon: { type: 'string' },
    why_might_work: { type: 'string' }, expected_effect: { type: 'string' },
  },
}
const HYPO_SCHEMA = { type: 'object', additionalProperties: false, required: ['hypotheses'],
  properties: { hypotheses: { type: 'array', items: CANDIDATE } } }
const RANKED_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['shortlist'],
  properties: { shortlist: { type: 'array', items: { type: 'object', additionalProperties: false,
    required: ['id', 'title', 'mechanism', 'signal', 'target', 'universe', 'horizon', 'record_path', 'rank_rationale'],
    properties: {
      id: { type: 'string' }, title: { type: 'string' }, mechanism: { type: 'string' },
      signal: { type: 'string' }, target: { type: 'string' }, universe: { type: 'string' },
      horizon: { type: 'string' }, record_path: { type: 'string' }, rank_rationale: { type: 'string' },
    } } },
  },
}
const SPEC_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['exp_id', 'hypothesis_id', 'one_variable_changed', 'control_null', 'split', 'success_metric', 'threshold', 'gate_direction', 'power_note', 'leakage_guards', 'spec_path'],
  properties: {
    exp_id: { type: 'string' }, hypothesis_id: { type: 'string' },
    one_variable_changed: { type: 'string' }, control_null: { type: 'string' },
    split: { type: 'string' }, success_metric: { type: 'string' }, threshold: { type: 'number' },
    gate_direction: { type: 'string', enum: ['above', 'below'] },
    power_note: { type: 'string' }, leakage_guards: { type: 'array', items: { type: 'string' } },
    spec_path: { type: 'string' },
  },
}
const RESULT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['exp_id', 'hypothesis_id', 'ran_ok', 'gate_metric', 'gate_value', 'gate_threshold', 'gate_direction', 'n_units', 'shuffle_null_p', 'seed', 'data_range', 'result_path', 'characterization', 'open_questions'],
  properties: {
    exp_id: { type: 'string' }, hypothesis_id: { type: 'string' },
    ran_ok: { type: 'boolean' },
    gate_metric: { type: 'string' }, gate_value: { type: 'number' }, gate_threshold: { type: 'number' },
    gate_direction: { type: 'string', enum: ['above', 'below'] },
    n_units: { type: 'number' }, ci_low: { type: 'number' }, ci_high: { type: 'number' },
    shuffle_null_p: { type: 'number' },
    seed: { type: 'number' }, data_range: { type: 'string' },
    artifacts: { type: 'object', additionalProperties: true },
    characterization: { type: 'string' },              // descriptive: where/when the effect lives + the sharpened claim
    open_questions: { type: 'array', items: { type: 'string' } },    // strongest unresolved questions, pre-registrable next round
    result_path: { type: 'string' }, error: { type: 'string' }, notes: { type: 'string' },
  },
}
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['lens', 'killed', 'reason'],
  properties: {
    lens: { type: 'string' }, killed: { type: 'boolean' }, reason: { type: 'string' },
    evidence: { type: 'string' },
  },
}
const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['index_written', 'survivors', 'killed', 'notebook_outline', 'follow_ups'],
  properties: {
    index_written: { type: 'boolean' },
    survivors: { type: 'array', items: { type: 'string' } },
    killed: { type: 'array', items: { type: 'string' } },
    notebook_outline: { type: 'string' },
    follow_ups: { type: 'array', items: { type: 'string' } },    // ranked next-round candidates distilled from open_questions
    headline: { type: 'string' },
  },
}

// ---------- Phase 1: Recon + baseline ----------
phase('Recon')
const recon = await agent(
  `You are the RECON agent for an autonomous quant-EDA run (slug "${SLUG}").
Idea: ${IDEA}
Data pointers: ${DATA}
Baseline to reproduce: ${BASELINE || '(none given)'}${CONV}

Do:
1. Load the data with: ${PY} <script>. Read ${EDA}/PRD.md for full context first.
2. Profile it: count INDEPENDENT observations (n_units = days/events, not rows), the sample range, per-column dtype+role (feature/target/id/time), missingness, and obvious regime segments. Write a profile note to ${EDA}/results/recon_profile.json.
3. If a baseline is given, reproduce its headline number from cached artifacts and set baseline_reproduced accordingly, explaining any mismatch — a mismatch is a red flag the run must surface, never hide.
Stop and report rather than guessing if the data will not load.
Return the RECON schema.`,
  { schema: RECON_SCHEMA, label: 'recon', phase: 'Recon', model: 'claude-sonnet-5', effort: 'medium' },
)

// HALT if a provided baseline failed to reproduce — do not build on a broken base.
if (BASELINE && recon.baseline_reproduced === false && !A.allowBrokenBaseline) {
  return {
    slug: SLUG, edaDir: EDA, halted: 'baseline_not_reproduced', recon,
    note: 'A baseline was given but did not reproduce; halting. Re-run with args.allowBrokenBaseline=true to override.',
  }
}

// ---------- Phase 2: Hypothesize (parallel) + rank (barrier) ----------
phase('Hypothesize')
const ANGLES = [
  { key: 'mechanism', ask: 'microstructure/causal-mechanism variants of the core idea — what exactly causes the mispricing and where it should show up' },
  { key: 'conditioning', ask: 'cross-sectional / state conditioning — WHEN and for WHOM the edge is strongest (size, liquidity, counterparty, moneyness, volatility)' },
  { key: 'regime', ask: 'time/regime-conditional versions — does the edge live in a regime; is it stationary' },
  { key: 'target', ask: 'alternative target definition / horizon / transformation that better isolates the claimed effect' },
  { key: 'interaction', ask: 'nonlinearity, thresholds, interactions between the signal and a second variable' },
  { key: 'skeptic', ask: "DEVIL'S ADVOCATE — the null/foil hypotheses: mundane explanations (regime, base-rate, autocorrelation, one big move) that would reproduce the preliminary result WITHOUT any real edge" },
]
const angles = QUICK ? ANGLES.slice(0, 3) : ANGLES
const reconStr = JSON.stringify(recon)
const pooled = (await parallel(angles.map((ang) => () =>
  agent(
    `You are a HYPOTHESIS GENERATOR (angle: ${ang.key}) for slug "${SLUG}".
Core idea: ${IDEA}
Data profile (ground every hypothesis in THIS, not guesses): ${reconStr}

Propose 2-4 falsifiable hypotheses from this angle: ${ang.ask}
Each must have a concrete signal construction computable from the profiled columns, a target, universe, horizon, and a stated mechanism (the edge you claim). Do NOT write files.
Return the HYPO schema.`,
    { schema: HYPO_SCHEMA, label: `hypo:${ang.key}`, phase: 'Hypothesize' },
  ),
))).filter(Boolean).flatMap((r) => r.hypotheses)

const ranked = await agent(
  `You are the RANK+DEDUP agent for slug "${SLUG}". Candidate hypotheses (JSON): ${JSON.stringify(pooled)}
Data profile: ${reconStr}

Do:
1. Merge near-duplicates (keep the sharpest phrasing).
2. Rank by mechanistic plausibility, testability from the available data, and edge if true. Keep at most ${TOP_K}. ALWAYS keep at least one skeptic/null hypothesis.
3. Assign ids H01.. and WRITE each shortlisted record to ${EDA}/hypotheses/H0N-<kebab-title>.md with this frontmatter then sections Thesis / Signal / Target-universe-horizon / Gate / Leakage-guard / Decision:
---
id: H0N
slug: <kebab>
status: ready-to-run
experiments: []
---
record_path = the file you wrote.
Return the RANKED schema.`,
  { schema: RANKED_SCHEMA, label: 'rank', phase: 'Hypothesize' },
)
const shortlist = ranked.shortlist.slice(0, TOP_K)
log(`baseline_reproduced=${recon.baseline_reproduced}; shortlisted ${shortlist.length} hypotheses`)

// ---------- Phases 3-5: pipeline per hypothesis (Design -> Implement -> Verify) ----------
const LENSES = ['leakage', 'overfit-power', 'regime-robustness']
const expId = (idx) => `EXP-${String(idx + 1).padStart(4, '0')}`

// Fan out ALL shortlisted hypotheses at once: each flows Design -> Implement -> Verify
// independently and concurrently (no cross-hypothesis barrier), then they converge at the
// Select (FDR) + Synthesize barriers to be brought back together.
log(`fanning out ${shortlist.length} hypotheses concurrently through design -> implement -> verify`)
const results = await pipeline(
  shortlist,
  // Design — freeze a pre-registered spec BEFORE any compute
  (h, _h, idx) => agent(
    `You are the EXPERIMENT DESIGNER for ${h.id} ("${h.title}"), experiment ${expId(idx)}, slug "${SLUG}".
Hypothesis: ${JSON.stringify(h)}
Data profile: ${reconStr}${CONV}

${DESIGNER_DOCTRINE}
Freeze a spec BEFORE any compute: the one variable changed, the null/foil control (scored on the IDENTICAL eval rows + seed as the main test), the walk-forward split, the pre-registered success metric + a NUMERIC threshold + gate_direction ("above" = pass when metric >= threshold, "below" = pass when metric <= threshold) + a power note (effective n, SE, pass-probability), and explicit leakage guards. Set exp_id="${expId(idx)}", hypothesis_id="${h.id}". WRITE it to ${EDA}/experiments/${expId(idx)}-spec.json (spec_path = that file). A frozen spec is never edited — a redesign gets a new exp id.
Return the SPEC schema.`,
    { schema: SPEC_SCHEMA, label: `design:${h.id}`, phase: 'Design' },
  ),
  // Implement — self-contained script; reports numbers, does NOT decide the gate
  (spec, h, idx) => agent(
    `You are the IMPLEMENTER for ${expId(idx)} (${h.id}: "${h.title}"), slug "${SLUG}".
Frozen spec (binding for the gate numbers; the characterization pass afterwards is yours to steer): ${JSON.stringify(spec)}${CONV}

Do:
1. Write a SELF-CONTAINED script ${EDA}/experiments/${expId(idx)}_run.py — import the project's modules read-only; do NOT edit shared modules (parallel siblings run at the same time).
2. Run it: ${PY} ${EDA}/experiments/${expId(idx)}_run.py
3. Honor the doctrine: trim outliers ONLY on train/fit, never OOS; report effective n = independent units (n_units); use a FIXED seed and report it; compute a permutation-null p (shuffle_null_p) and a bootstrap CI (blocked by the independent unit). Fairness: every variant scored on identical eval rows, the same seed, the same bootstrap scheme, tables as a columnar file (parquet/feather/sds), plots as png. Write the returned result object as JSON to ${EDA}/results/${expId(idx)}-result.json (result_path = that file).
4. Write artifacts to ${DROOT}/{models,oos,nulls,plots}/${expId(idx)}_*.
5. THEN characterize what you found, per the principles below — extend the script or add ${EDA}/experiments/${expId(idx)}_char.py.

${CHARACTERIZE_DOCTRINE}

Echo gate_metric, gate_value, gate_threshold, gate_direction, seed, data_range faithfully — a downstream agent RE-DECIDES pass/fail from these numbers, so do not try to tune the verdict. Put the descriptive pass in characterization (ending with the sharpened one-sentence claim) and open_questions; it cannot alter the gate fields. If the run errors, set ran_ok=false and put the traceback tail in error.
Return the RESULT schema.`,
    { schema: RESULT_SCHEMA, label: `impl:${h.id}`, phase: 'Implement', model: 'claude-sonnet-5', effort: 'high' },
  ),
  // Verify — gate recomputed from frozen threshold; 3 lenses; leakage is a hard veto
  (res, h, idx) => {
    const positive = !!res && res.ran_ok === true && (res.gate_direction === 'below'
      ? res.gate_value <= res.gate_threshold
      : res.gate_value >= res.gate_threshold)
    if (res) res.looks_positive = positive    // decided from the frozen threshold, not the implementer's say-so
    if (!positive) return Promise.resolve({ ...(res || {}), hypothesis: h, verdicts: [], survived: false })
    const resForAdv = { ...res }
    // strip narrative so persuasive prose can't anchor the adversary
    delete resForAdv.notes
    delete resForAdv.characterization
    delete resForAdv.open_questions
    return parallel(LENSES.map((lens) => () =>
      agent(
        `You are a STATISTICS ADVERSARY (lens: ${lens}) attacking a POSITIVE result. Try to REFUTE it; default killed=true when unproven. Ignore prose claims — verify from data and code.
Result: ${JSON.stringify(resForAdv)}
Experiment ${expId(idx)} (${h.id}: "${h.title}").${CONV}

${ADVERSARY_DOCTRINE}

Your lens:
- leakage: you MUST read ${EDA}/experiments/${expId(idx)}_run.py, check feature-vs-label window overlap, and re-run the future-perturbation test with ${PY} — no code comment counts as proof.
- overfit-power: in-sample vs OOS raw prediction, low-complexity equivalent, effective-n t-stat, gate power.
- regime-robustness: per-period stability, rolling metric sign flips, base-rate/random-drop control, one-big-observation dependence.
Read ${EDA}/experiments/${expId(idx)}-spec.json for the pre-registered gate. Artifacts at ${DROOT}.
Return the VERDICT schema.`,
        { schema: VERDICT_SCHEMA, label: `verify:${h.id}:${lens}`, phase: 'Verify' },
      ),
    )).then((vs) => {
      const verdicts = vs.filter(Boolean)
      const notKilled = verdicts.filter((v) => !v.killed).length
      const leak = verdicts.find((v) => v.lens === 'leakage')
      const leakKilled = leak ? leak.killed : true    // no leakage verdict => treat as killed (conservative)
      return { ...res, hypothesis: h, verdicts, survived: !leakKilled && notKilled >= 2 }
    })
  },
)

// ---------- Phase 6: Select — family-wise FDR (Benjamini-Hochberg) across the tested family ----------
phase('Select')
const clean = results.filter(Boolean)
const tested = clean.filter((r) => r.looks_positive && typeof r.shuffle_null_p === 'number')
const m = tested.length
const byP = [...tested].sort((a, b) => a.shuffle_null_p - b.shuffle_null_p)
let kmax = 0
byP.forEach((r, i) => { if (r.shuffle_null_p <= ((i + 1) / m) * FDR_Q) kmax = i + 1 })
byP.forEach((r, i) => {
  r.family_size = m
  r.bh_adjusted_p = Math.min(1, (r.shuffle_null_p * m) / (i + 1))
  r.bh_pass = i + 1 <= kmax
})
// Ships only if it survived the adversary AND cleared family-wise FDR.
clean.forEach((r) => { r.final_survivor = r.survived === true && r.bh_pass === true })
const survivors = clean.filter((r) => r.final_survivor)
log(`family_size=${m}, fdr_q=${FDR_Q}, survivors=${survivors.length}`)

// ---------- Phase 7: Synthesize (single writer) ----------
phase('Synthesize')
const synth = await agent(
  `You are the SYNTHESIS agent for slug "${SLUG}". Per-experiment results with adversary verdicts + FDR fields (JSON): ${JSON.stringify(clean)}

Do (you are the SOLE writer now — safe):
1. Patch each ${EDA}/results/EXP-*-result.json: add "adversary": [{lens,killed,reason}], "family_size", "bh_adjusted_p", and set "verdict":
   - survived = passed the adversary (leakage-veto + majority) AND bh_pass (family-wise FDR)
   - killed = positive but the adversary killed it OR it failed family-wise FDR
   - inconclusive = ran_ok but did not clear the pre-registered gate
2. Write ${EDA}/INDEX.md: a table Hypothesis | Experiment | gate metric+value | bh_adjusted_p | verdict | driving reason, plus a one-line status header, plus a Follow-ups section: pool the experiments' open_questions, merge duplicates, rank by how much an answer would change the interpretation, each phrased as a pre-registrable next-round hypothesis (follow_ups = that ranked list).
3. Draft a notebook outline the primary will build: thesis, one section per SURVIVING hypothesis (signal -> result + CI + null-p + bh_adjusted_p -> adversary checks -> characterization's sharpened claim -> verdict), a killed-hypotheses appendix (what died + which attack killed it), and the negative controls.
Return the SYNTH schema.`,
  { schema: SYNTH_SCHEMA, label: 'synthesize', phase: 'Synthesize', model: 'claude-sonnet-5', effort: 'medium' },
)

return {
  slug: SLUG, edaDir: EDA, dataRoot: DROOT, family_size: m, fdr_q: FDR_Q,
  recon,
  shortlist: shortlist.map((h) => ({ id: h.id, title: h.title, record_path: h.record_path })),
  survivors: survivors.map((r) => ({ exp_id: r.exp_id, hypothesis_id: r.hypothesis_id, gate_metric: r.gate_metric, gate_value: r.gate_value, bh_adjusted_p: r.bh_adjusted_p, final_survivor: r.final_survivor, result_path: r.result_path })),
  results: clean.map((r) => ({ exp_id: r.exp_id, hypothesis_id: r.hypothesis_id, ran_ok: r.ran_ok, looks_positive: r.looks_positive, adversary_survived: r.survived, bh_adjusted_p: r.bh_adjusted_p })),
  synthesis: synth,
}