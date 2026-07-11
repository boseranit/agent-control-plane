---
name: locating-the-edge
description: Locate where a quantitative result lives by varying one construction decision at a time, then test its interpretation against plausible alternatives. Use when a result may depend on upstream choices or subpopulations, when a model underperforms a baseline, or when an aggregate finding needs confound checks, a bounded claim, or follow-up hypotheses.
---

# Definitions

## Slice
A slice is one construction decision made before the model fits — a single knob in how you cut, combine, scale, or scope the data on its way into the model. In standard terms it's an **ablation** (ML) or one **factor** in a design-of-experiments sense. "Slicing" the construction means isolating one of those knobs and changing only it.

The point of the word: the model is downstream of a stack of choices, and each choice is independently variable. A slice is one of them.

Example slices:
- aggregation — sum a counterparty's futures + options into one feature, or keep them as separate features
- inclusion — which features/buckets go in
- subpopulation — which rows you fit/score on (a vol regime, a time-of-day window, large-move days only)
- normalization, target horizon, clipping/winsorization of features, estimator — same idea, other knobs

## Foil
A foil — a **negative control** — is the mirror experiment that rules out a confound: the deliberate opposite of the variant you believe in, run specifically to try to break your own hypothesis.

The problem it solves: if you test "drop options, keep futures" and it looks fine, you can't tell why — is it because futures is the right slice, or just because you removed noisy features? The foil is the inverse: "drop futures, keep options." If your story is right, the foil should be worse. If the foil is better, your prior was backwards.

# Locating the edge

Don't ask "does the signal work?" Ask:

> **Is there a real edge the shipped construction is mangling, and where does it live?**

You answer it by changing one **slice** at a time and watching which slice the metric tracks; running the full set of defensible slices is **specification-curve** (multiverse) analysis. A **slice** is one construction decision made before the model fits — how the data is cut, combined, scaled, or scoped. A null result on the shipped model is often a mangled or under-powered slice, not an absent edge.

After any material result, identify its boundaries, test rival explanations, and turn unresolved patterns into follow-up hypotheses. Steps 7-8 apply whether the result came from a slice battery or elsewhere.

Applies to any project with a headline metric (IC, Sharpe, AUC, delta-MSE) and construction choices upstream of the model.

## Steps

1. **Reproduce the shipped number bit-exact.** Build a harness that replays the pipeline from cached artifacts and reproduces the shipped model's headline metric. Every variant reuses it, changing one slice. *Done when:* the harness prints the committed metric to tolerance.

2. **Enumerate the slices.** List every construction decision baked in before the fit — each is a slice you can turn. Look for: **aggregation** (combine vs keep separate), **inclusion** (which features/entities/buckets), **subpopulation** (which rows: regime, time-of-day, magnitude), **normalization** (scaling/standardization), **target** (horizon, transform), **estimator** (weighting, shrinkage). *Done when:* a written list, each slice naming the shipped choice plus ≥1 alternative.

3. **Build the battery — one slice per variant.** Each variant changes exactly one slice; the rest of the pipeline stays byte-identical (same fit, eval rows, seed, leakage controls). Then any metric gap is attributable to that slice. *Done when:* every variant differs from baseline in exactly one slice, and baseline reproduces inside the battery.

4. **Add the foil.** For every "drop X / keep Y" or "Y is what carries it" hypothesis, run the mirror — keep X, drop Y. Without it you confound *the right slice* with *fewer/simpler features*. The foil is what catches your own prior being wrong. *Done when:* every keep/drop claim has its mirror in the battery.

5. **Score on the powered metric, not the shipped gate.** A single-window holdout gate is often too weak to see a real effect. Pool the full sample / walk-forward with a bootstrap blocked by the independence unit (usually date), add a per-period breakdown, and state the gate's power at the plausible effect size. *Done when:* each variant has a powered point estimate + CI + per-period path, and the gate's power is computed.

6. **Read which slice the metric tracks.** The conclusion is *locational*: "the edge concentrates in slice Z; the shipped construction smears it" — then name what to ship. *Done when:* the winning slice is named, the mangling mechanism stated, and the shipped-model recommendation made (whether it confirms or overturns the current one).

7. **Interrogate the result.** State the leading interpretation and credible alternatives, including confounding where plausible. Choose breakdowns or diagnostics on which the explanations predict different outcomes. Look for where the result strengthens, weakens, reverses, disappears, or depends on a small part of the data. *Done when:* the observed boundaries and remaining explanations are explicit.

8. **Revise and recurse.** Rewrite the claim to match its observed scope and uncertainty. Turn unexpected or unresolved patterns into falsifiable follow-up hypotheses, then name the next test that distinguishes the remaining explanations. *Done when:* the bounded claim, credible alternatives, and next test are recorded.

## Disciplines

- **One ingredient.** Exactly one slice per variant. A variant that moves two slices answers nothing.
- **Fairness.** Same eval rows, bootstrap seed, iteration count, and selection protocol for every variant — unless the experiment is *about* that protocol.
- **Leakage.** Any trailing statistic uses strictly-prior data; verify once by perturbing future rows and confirming past values are unchanged.
- **Adaptive is descriptive.** Follow-ups chosen after seeing the result may narrow its interpretation or generate hypotheses, not confirm a new claim. Validate new claims independently.

## Failure modes

- **Confounded variant** — moved more than one slice, so the gap is unattributable. Defence: one ingredient.
- **Missing foil** — a keep/drop result with no mirror confirms your prior instead of testing it.
- **Underpowered verdict** — calling a slice dead on a gate too weak to detect the effect; compute power before concluding absence.
- **Premature kill** — concluding "no edge" before ruling out that a different slice carries it. The question is *where*, not *whether*.
- **Single-story reading** — testing only the preferred explanation. Name credible rivals and use diagnostics where their predictions differ.
- **Post-hoc promotion** — treating a discovered pattern as confirmed. Record it as a hypothesis and test it separately.

## See also

For the full end-to-end audit — flaw-hypothesis catalog across evaluation/target/features/model/protocol, parallel subagent experiments, ranked synthesis — this slicing battery is the feature/aggregation family inside the broader **research-critique** skill. Use that when the question is wider than "where does the edge live."