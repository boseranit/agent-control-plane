# Research Run Mirror and MLflow adapter wiring

Status: ready-for-agent
Label: ready-for-agent

## Parent

Research Experiment Plane parent issue: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`

## What to build

Implement the provider-neutral Research Run Mirror request, best-effort ledger wrapper, MLflow adapter, and end-of-experiment wiring. MLflow remains a mirror surface only and never controls workflow success.

## Acceptance criteria

- [ ] Controller/experiment flow imports only the provider-neutral mirror interface.
- [ ] MLflow SDK imports live only in the MLflow adapter module.
- [ ] Mirror logs approved params/tags, numeric metrics, and all run-directory artifacts recursively.
- [ ] Mirror failures append ledger events and do not change control flow.
- [ ] Tests cover success, failure, metric extraction, and recursive artifact logging.

## Blocked by

- `.scratch/research-experiment-plane/issues/08-research-run-state-ledger-start-resume.md`
- `.scratch/research-experiment-plane/issues/14-evaluator-workspace-boundary-audit.md`

