# Minimal Durable Execution Shell

The Research Experiment Controller uses Hatchet as a thin Durable Execution Shell, not as the owner of research workflow semantics. Hatchet provides generic run metadata plus usage-limit sleep/retry around the Python controller loop. It does not resume inside a Research Experiment phase. Python controller code owns phases, artifacts, materiality policy, outcome classification, command execution, worktrees, and MLflow mirroring so the durable executor can be replaced later without rewriting the research model.
