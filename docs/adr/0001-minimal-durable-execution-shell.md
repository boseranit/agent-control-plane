# Minimal Durable Execution Shell

The Research Experiment Controller uses Hatchet as a Durable Execution Shell, not as the owner of research workflow semantics. Hatchet owns resume, sleep, event wait, step invocation, and generic run metadata; Python controller code owns phases, artifacts, materiality policy, outcome classification, command execution, worktrees, and MLflow mirroring so the durable executor can be replaced later without rewriting the research model.
