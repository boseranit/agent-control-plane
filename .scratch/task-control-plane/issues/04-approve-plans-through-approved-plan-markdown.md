# Approve Plans Through the Approved Plan Markdown Artifact

Status: ready-for-agent
Label: ready-for-agent

## Parent

Task Control Plane PRD: `.scratch/task-control-plane/PRD.md`

## What to build

Make the Approved Plan real. When planning reaches `status: planned`, the Controller writes the planner's Markdown plan into the authoritative Approved Plan artifact. If plan approval is enabled, the Controller opens the artifact through an injectable editor hook and requires explicit human approval. If plan approval is disabled, the Controller marks the plan approved automatically.

The implementer-facing plan must be the Approved Plan artifact, not raw planner history.

## Acceptance criteria

- [ ] A planner `plan_markdown` is written to the Task's Approved Plan Markdown artifact.
- [ ] The Approved Plan Markdown artifact is treated as the authoritative plan.
- [ ] The planning artifact references the Approved Plan path and records approval metadata.
- [ ] When `require_plan_approval` is false, the Controller approves the planner plan without opening an editor.
- [ ] When `require_plan_approval` is true, the Controller opens the Approved Plan through an injectable editor hook.
- [ ] When `require_plan_approval` is true, the Controller requires explicit approval through an injectable confirmation hook.
- [ ] If approval is declined, the Controller stops before implementation and records the Task state appropriately.
- [ ] The implementation phase input uses the Approved Plan path only, not raw planner drafts.
- [ ] Tests cover auto-approval, editor-based approval, edited Approved Plan content, declined approval, planning artifact metadata, and implementer-facing input construction.

## Blocked by

- `.scratch/task-control-plane/issues/02-plan-task-with-persistent-planner-agent.md`
- `.scratch/task-control-plane/issues/03-resolve-planner-questions-with-context-agent.md`
