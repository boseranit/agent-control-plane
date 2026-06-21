# Repo Purpose
This repo implements a Research Experiment Controller for bounded, auditable quantitative research loops.
The intended behavior is to mimic a real workflow where experienced researchers
form testable hypotheses, a dedicated implementer makes the required code
changes, required signals/feature data is backfilled, an independent evaluator
checks the evidence, and the next experiment builds on what was learned. A new
experiment may be a direct follow-up, a controlled variation, an adjacent
hypothesis, or a fresh hypothesis when the prior path is blocked or lower value.
Use the terminology in `CONTEXT.md`.

# Operating Rules
- Treat saved artifacts as authoritative. Agent thread memory is continuity only.
- Keep the controller deterministic: it owns state transitions, artifact
  persistence, phase order, outcome routing, boundary checks, and mirrors. It does not make research judgments.
- Keep SDK-specific code behind adapters. Controller code should depend on the neutral runtime and mirror interfaces, not provider SDK types.
- Prefer small, direct changes that match the existing modules and tests.
- Run pytest through Pixi: use `pixi run -e dev pytest ...`, not `pytest`, `python -m pytest`, or `python3 -m pytest`.
- When changing loop behavior, update the relevant role prompt in `agent_control_plane/research_experiment_controller/prompts/`, the artifact schema in `agent_control_plane/research_experiment_controller/artifacts.py`, and focused tests. Use structured command specs (`argv`, `cwd`, `timeout`), not shell strings, for experiment commands.

# Research Loop Contract
- A human-authored Research Run Spec starts one Research Run and defines the
  agenda, target repository, output root, data root, budgets, worktree behavior, agent model, and optional continuation inputs.
- The Strategist is persistent within a Research Run. It must read the context artifacts, propose exactly one selected plan or no plan, classify how the plan relates to prior work when continuation memory is available, and write the canonical handover artifacts.
- The Critic is fresh for each critique pass and must not inherit Strategist,
  Implementer, or Evaluator conversation state.
- The Implementer is scoped to one Experiment Worktree and may edit only the selected design's `allowed_write_paths`.
- The Evaluator is scoped to one Evaluator Workspace. Confirmatory evaluation
  decides the official completed outcome; exploratory diagnostics can only seed
  future experiments.
- Completed experiments receive empirical closeout. The closeout can add `plan_update.json`, but it must not change the official outcome fields.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default five canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo using root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.
