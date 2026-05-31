# Research Experiment Plane Implementation Plan

> **For agents:** Implement task-by-task. Checkboxes are the execution ledger.

**Goal:** Build the Research Experiment Plane as a sibling Control-Plane Workflow that runs bounded research experiments with durable resume, audited artifacts, preserved worktrees, evaluator workspaces, and Research Run Mirror output to MLflow.

**Architecture:** Add a thin shared `agent_control_plane/control_plane/` package only for deep/testable generic primitives, then build `agent_control_plane/research_experiment_controller/` as its own workflow package. The controller owns run lifecycle and research semantics; `experiment_flow.py` owns one bounded Research Experiment path. Replaceable integrations live behind narrow local modules: Hatchet behind the provider-neutral Durable Shell, MLflow behind a provider-neutral Research Run Mirror interface plus adapter, and command-heavy phase helpers in dedicated prerequisite, verification, and boundary modules. Workflow-specific code stays in the Research package until a second real consumer appears.

**Tech Stack:** Python 3.13, pytest, PyYAML, Pydantic, Hatchet SDK, openai-agents, MLflow, git CLI, subprocess with `shell=False`.

---

## Source Context

Read these before coding:

- `CONTEXT.md`
- `docs/adr/0001-minimal-durable-execution-shell.md`
- `.scratch/research-experiment-plane/PRD.md`
- `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`
- `agent_control_plane/task_control_plane/controller.py`
- `agent_control_plane/task_control_plane/agent_runtime.py`
- `agent_control_plane/task_control_plane/hatchet_workflow.py`
- `tests/test_task_control_plane.py`
- `tests/test_agent_runtime.py`
- `tests/test_hatchet_workflow.py`

Do not copy the Hyperliquid code directly. Use the PRD as the source of truth; use this plan as the execution guide.

## Scope Check

This feature spans shared primitives, a new workflow package, Hatchet integration, Research Run Mirror output to MLflow, and CLI entry points. The tasks below are sliced so each commit leaves working, testable software. If work is split across multiple workers, split only on task boundaries and avoid parallel edits to the same file list.

## Design Guardrails

Keep the implementation minimal by preserving narrow module boundaries:

- `controller.py` owns Research Run state, stop policy, and delegation only. It must not run shell commands, import Hatchet/MLflow, inspect worktree diffs, or know adapter internals.
- `experiment_flow.py` owns one bounded Research Experiment sequence. It may call phase helpers and construct provider-neutral requests, but it must not import SDK adapters or embed command-running details.
- `durable_shell.py` is the caller-facing durable execution interface. Hatchet imports stay only in `hatchet_workflow.py` and `hatchet_worker.py`.
- `research_run_mirror.py` is the caller-facing mirror interface and best-effort wrapper. MLflow imports and translation stay only in `mlflow_mirror.py`.
- `prerequisites.py`, `verification.py`, `implementation_boundary.py`, and `evaluation.py` own command execution and boundary checks for their phase. Callers pass simple dataclass requests or artifact models.
- Shared `control_plane/` modules must be deep primitives with Task or likely second-workflow use. Keep Research-only policy and artifact semantics in `research_experiment_controller/`.
- Prefer contract tests over copying full implementations into this plan. Add code snippets only when they define a public interface or prevent an ambiguity.

## Resolved Decisions

- New workflow package: `agent_control_plane/research_experiment_controller/`.
- New shared package: `agent_control_plane/control_plane/`.
- Shared modules must be deep and testable; do not create shared wrappers for one Research-only consumer.
- Do not implement research as a mode of `task_control_plane`.
- A Task ends with a final commit; a Research Experiment ends with a Research Outcome and inspectable artifacts.
- A Research Run Spec is one human-managed YAML file containing the Research Brief and run controls.
- No separate Research Brief file.
- One Research Run Spec execution creates one Research Run.
- One Research Run may create up to `max_experiments` Research Experiments.
- One Research Experiment has one selected plan, one locked spec and design, one implementation/evaluation path, and one terminal Research Outcome.
- One Research Experiment selects at most one plan.
- Copy the resolved Research Run Spec into the Research Run directory. Resume reads the snapshot.
- No extra budget immutability validation on resume.
- Research Budgets are named profiles fixed for the Research Run and used for pipeline/backfill scope.
- Selected budget `max_runtime_minutes` is the default command timeout.
- Use one Research Outcome enum: `no_op`, `blocked`, `prerequisites_failed`, `invalid`, `run_failed`, `completed_rejected`, `completed_inconclusive`, `completed_candidate`.
- Do not add a separate evidence-status axis.
- Add diagnostic fields: `outcome_reason`, `failed_stage`, `failure_classification`.
- Outcome classification must be easy to tune with a small controller-owned policy module.
- Default no-op boundary: no admissible experiment was selected.
- Selected plan with no executable deterministic command is not a healthy no-op.
- Add `prerequisites_failed` for data/prerequisite audit failures likely to affect future experiments.
- `prerequisites_failed` records `failed_stage=data_audit`.
- Failure classifications for data audit include `data_root_missing`, `feature_family_missing`, `schema_mismatch`, `artifact_missing`, `point_in_time_invalid`, `prerequisite_command_failed`.
- `stop_on_prerequisites_failed: true` stops the whole Research Run.
- Use Hatchet only as a Durable Execution Shell adapter.
- Hatchet metadata remains generic: run id, controller state version, current phase, status.
- Keep Hatchet SDK imports out of controller, CLI, and `durable_shell.py`. Only `hatchet_workflow.py` and `hatchet_worker.py` import Hatchet.
- Durable-shell callers use a provider-neutral `ResearchRunInput` plus `run_research_shell(...)`; replacing Hatchet should only touch the shell contract, adapter module, worker startup, and worker wiring.
- Python controller code owns run lifecycle, policies, outcomes, and ledgers. `experiment_flow.py` owns the per-experiment phase sequence and delegates commands, worktrees, evaluator boundaries, and mirror requests to narrow helper modules. Neither layer owns MLflow or Hatchet implementation details.
- No Hatchet human event wait in v1.
- Agents continue with explicit assumptions when human context is missing.
- Use Pydantic only for canonical Research Artifacts at controller-agent boundaries.
- Controller state and ledgers stay lightweight plain JSON/JSONL.
- Research Strategist Agent thread: persistent read-only per Research Run.
- Research Critic Agent thread: fresh read-only per critique pass.
- Research Implementer Agent thread: persistent workspace-write per Research Experiment Worktree.
- Research Evaluator Agent thread: persistent workspace-write per Evaluator Workspace.
- Artifacts are authoritative; thread memory is only convenience.
- Materiality is controller-owned. Agents may declare a revision material, but cannot decide a revision is non-material.
- Default material fields: target, label, universe, data source, feature family, split, primary metric, success gate, baseline set, transaction-cost model, holding period, rebalance frequency, neutralization policy.
- V1 includes the full role chain.
- V1 excludes evaluator-to-implementer repair.
- V1 includes implementation verification repair up to `implementation.max_repairs`.
- V1 excludes parallel experiments.
- V1 excludes phase-by-phase MLflow and MLflow tracing.
- V1 excludes automatic promotion and final commits.
- Research Experiment Controller package creates one preserved Experiment Worktree per selected Research Experiment.
- Existing dirty Experiment Worktree reuse fails.
- `worktree.create: false` is allowed only for no-edit/read-only experiments.
- Implementer writes only inside allowed edit paths from `experiment_design.json`.
- `implementation_boundary.py` audits changed files against allowed edit paths.
- Evaluator gets a writable `evaluation/` directory inside the experiment run dir.
- Evaluator receives `evaluation/manifest.json` containing paths to canonical artifacts, run dir, worktree, data root, locked confirmatory commands, and git SHA.
- No `eval_inputs/` subtree.
- Evaluator can write `evaluation/eval_scratch/` and `evaluation/eval_outputs/`.
- Evaluator can run shell from `evaluation/`.
- Evaluator must not edit the Experiment Worktree or locked artifacts.
- Evaluation Boundary Audit checks worktree state and locked artifact hashes from `manifest.json`.
- Boundary audit failure produces `run_failed` with `failed_stage=evaluation_boundary_audit`.
- Research Run Mirror means an end-of-experiment, best-effort copy of selected run facts into an external browsing/comparison surface. It is not shell-terminal output and it is not authoritative state.
- Research Run Mirror output to MLflow runs at experiment end only.
- MLflow logs params/tags: `research_run_id`, `experiment_id`, `outcome`, `failed_stage`, `failure_classification`, `git_sha`.
- MLflow logs metrics from `command_metrics.json`, `metrics.json`, and numeric leaves in final evaluation result.
- MLflow logs all run-dir artifacts recursively.
- MLflow failure appends a ledger event and does not affect control flow.
- Shared primitives: JSON artifact IO, usage-limit backoff, structured command runner, generic agent runtime, boundary audit helpers.
- Keep the Research Run Mirror request and best-effort wrapper in `research_run_mirror.py`. Keep MLflow SDK imports and MLflow-specific translation inside `mlflow_mirror.py`. `controller.py` imports neither module; `experiment_flow.py` imports only `research_run_mirror.py`.
- Research Run Mirror output to MLflow lives in the Research package unless another workflow uses the same end-of-experiment contract.
- Keep Task planning, approval, review, and commit logic inside `task_control_plane`.

## Target File Structure

Create:

- `agent_control_plane/control_plane/__init__.py`  
  Shared primitive package marker.
- `agent_control_plane/control_plane/json_artifacts.py`  
  Atomic JSON read/write, JSONL append/read, SHA-256 file hashing, artifact hash manifest helpers.
- `agent_control_plane/control_plane/usage_limit.py`  
  Shared usage-limit detection, retry timestamp parsing, and one-retry runner.
- `agent_control_plane/control_plane/command_runner.py`  
  Structured argv command runner with live logs, env overlays, timeouts, process-group termination, and command metrics.
- `agent_control_plane/control_plane/agent_runtime.py`  
  Generic agent runtime with arbitrary role names and capability policy.
- `agent_control_plane/control_plane/boundary_audit.py`  
  Git status snapshots, changed-file checks, path allowlist checks, locked artifact hash checks.

Create:

- `agent_control_plane/research_experiment_controller/__init__.py`
- `agent_control_plane/research_experiment_controller/research_run_spec.py`  
  Dataclass-based YAML loader for Research Run Spec.
- `agent_control_plane/research_experiment_controller/artifacts.py`  
  Pydantic Research Artifact models and enums.
- `agent_control_plane/research_experiment_controller/state.py`  
  Plain JSON state creation/update helpers for Research Runs and Research Experiments.
- `agent_control_plane/research_experiment_controller/ledger.py`  
  Append-only JSONL event helpers.
- `agent_control_plane/research_experiment_controller/context.py`  
  Deterministic `context_pack.md` and prior-run synthesis.
- `agent_control_plane/research_experiment_controller/prompts/strategist-agent.md`
- `agent_control_plane/research_experiment_controller/prompts/critic-agent.md`
- `agent_control_plane/research_experiment_controller/prompts/implementer-agent.md`
- `agent_control_plane/research_experiment_controller/prompts/evaluator-agent.md`
- `agent_control_plane/research_experiment_controller/agents.py`  
  Role definitions, prompt loading, thread open/run helpers.
- `agent_control_plane/research_experiment_controller/worktree.py`  
  Experiment Worktree creation/reuse validation.
- `agent_control_plane/research_experiment_controller/outcomes.py`  
  Outcome classification helpers.
- `agent_control_plane/research_experiment_controller/prerequisites.py`  
  Data root checks, prerequisite/data-audit command execution, and data-audit failure routing.
- `agent_control_plane/research_experiment_controller/verification.py`  
  Implementation verification command execution and same-Implementer repair loop.
- `agent_control_plane/research_experiment_controller/implementation_boundary.py`  
  Allowed edit path audit and implementation diff failure mapping.
- `agent_control_plane/research_experiment_controller/evaluation.py`  
  Evaluator Workspace, manifest, and Evaluation Boundary Audit helpers.
- `agent_control_plane/research_experiment_controller/research_run_mirror.py`  
  Provider-neutral Research Run Mirror request, `ResearchRunMirror` callable protocol, and best-effort ledger wrapper; no MLflow SDK imports.
- `agent_control_plane/research_experiment_controller/mlflow_mirror.py`  
  MLflow Research Run Mirror adapter; only this module imports MLflow or knows MLflow client/run APIs.
- `agent_control_plane/research_experiment_controller/experiment_flow.py`  
  One bounded Research Experiment path; coordinates agents/artifacts and calls helper modules through narrow interfaces.
- `agent_control_plane/research_experiment_controller/controller.py`  
  Research Run start/resume, state loop, stop policy, and delegation to `experiment_flow.py`.
- `agent_control_plane/research_experiment_controller/durable_shell.py`  
  Provider-neutral Research Run input, metadata sink protocol, and shell runner contract; no Hatchet imports.
- `agent_control_plane/research_experiment_controller/hatchet_workflow.py`  
  Hatchet Durable Execution Shell adapter only; generic metadata and no research semantics.
- `agent_control_plane/research_experiment_controller/hatchet_worker.py`
- `agent_control_plane/research_experiment_controller/cli.py`
- `agent_control_plane/research_experiment_controller/__main__.py`

Modify:

- `agent_control_plane/task_control_plane/agent_runtime.py`  
  Replace implementation with compatibility imports/wrappers around shared runtime.
- `agent_control_plane/task_control_plane/controller.py`  
  Use shared JSON, usage-limit, and command runner only where risk is low.
- `agent_control_plane/task_control_plane/hatchet_workflow.py`  
  No semantic change; keep as reference pattern.
- `pixi.toml`  
  Add `research-experiment-worker` task.

Create tests:

- `tests/test_control_plane_json_artifacts.py`
- `tests/test_control_plane_usage_limit.py`
- `tests/test_control_plane_command_runner.py`
- `tests/test_control_plane_agent_runtime.py`
- `tests/test_control_plane_boundary_audit.py`
- `tests/test_research_run_spec.py`
- `tests/test_research_artifacts.py`
- `tests/test_research_state_and_ledger.py`
- `tests/test_research_context.py`
- `tests/test_research_agents.py`
- `tests/test_research_worktree.py`
- `tests/test_research_evaluation.py`
- `tests/test_research_mlflow_mirror.py`
- `tests/test_research_controller.py`
- `tests/test_research_hatchet_workflow.py`
- `tests/test_research_cli.py`
- `tests/test_research_e2e.py`

## Implementation Tasks

### Task 1: Shared JSON Artifact IO

**Files:**
- Create: `agent_control_plane/control_plane/__init__.py`
- Create: `agent_control_plane/control_plane/json_artifacts.py`
- Test: `tests/test_control_plane_json_artifacts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_control_plane_json_artifacts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_control_plane.control_plane.json_artifacts import (
    append_jsonl,
    file_sha256,
    read_json_object,
    read_jsonl,
    write_json,
    write_text,
)


def test_write_and_read_json_object(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "artifact.json"

    write_json(path, {"b": 2, "a": 1})

    assert path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
    assert read_json_object(path) == {"a": 1, "b": 2}


def test_read_json_object_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected JSON object"):
        read_json_object(path)


def test_append_and_read_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"

    append_jsonl(path, {"event": "START", "n": 1})
    append_jsonl(path, {"event": "END", "n": 2})

    assert read_jsonl(path) == [
        {"event": "START", "n": 1},
        {"event": "END", "n": 2},
    ]


def test_read_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"event": "A"}\n\n{"event": "B"}\n', encoding="utf-8")

    assert read_jsonl(path) == [{"event": "A"}, {"event": "B"}]


def test_file_sha256_and_write_text(tmp_path: Path) -> None:
    path = tmp_path / "notes" / "result.md"

    write_text(path, "hello\n")

    assert path.read_text(encoding="utf-8") == "hello\n"
    assert file_sha256(path) == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


def test_write_json_requires_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"

    with pytest.raises(ValueError, match="JSON artifact must be an object"):
        write_json(path, [1, 2, 3])  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_control_plane_json_artifacts.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_control_plane.control_plane'`.

- [ ] **Step 3: Implement JSON helpers**

Create `agent_control_plane/control_plane/__init__.py`:

```python
"""Shared primitives for Agent Control Plane workflows."""
```

Create `agent_control_plane/control_plane/json_artifacts.py`:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError("JSON artifact must be an object.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(data), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json_object(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {target}")
    return data


def append_jsonl(path: str | Path, data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError("JSONL event must be an object.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(data), sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object at {target}:{line_number}")
        events.append(data)
    return events


def write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pixi run pytest tests/test_control_plane_json_artifacts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/control_plane/__init__.py agent_control_plane/control_plane/json_artifacts.py tests/test_control_plane_json_artifacts.py
git commit -m "add shared json artifact helpers"
```

### Task 2: Shared Usage-Limit Backoff

**Files:**
- Create: `agent_control_plane/control_plane/usage_limit.py`
- Modify: `agent_control_plane/task_control_plane/controller.py`
- Test: `tests/test_control_plane_usage_limit.py`
- Test: `tests/test_task_control_plane.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_control_plane_usage_limit.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_control_plane.control_plane.usage_limit import (
    UsageLimitWait,
    parse_usage_limit_retry_at,
    run_with_usage_limit_backoff,
)


def test_parse_time_of_day_retry_at_rolls_forward() -> None:
    now = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)

    retry_at = parse_usage_limit_retry_at(
        "You've hit your usage limit. Try again at 11:14 AM.",
        now,
    )

    assert retry_at == datetime(2026, 5, 31, 11, 14, tzinfo=UTC)


def test_parse_retry_after_seconds() -> None:
    now = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)

    retry_at = parse_usage_limit_retry_at("retry-after: 30", now)

    assert retry_at == now + timedelta(seconds=30)


def test_non_usage_error_returns_none() -> None:
    now = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)

    assert parse_usage_limit_retry_at("syntax error", now) is None


def test_run_with_usage_limit_backoff_retries_once() -> None:
    attempts = 0
    sleeps: list[float] = []
    events: list[dict[str, object]] = []
    now = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)

    def run() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("usage limit reached; try again at 10:01 AM")
        return "ok"

    result = run_with_usage_limit_backoff(
        run,
        role="strategist",
        now=lambda: now,
        sleep=sleeps.append,
        record_event=events.append,
    )

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [60.0]
    assert events[0]["type"] == "usage_limit"
    assert events[0]["role"] == "strategist"


def test_run_with_usage_limit_backoff_raises_after_second_usage_limit() -> None:
    sleeps: list[float] = []

    def run() -> str:
        raise RuntimeError("usage limit reached; try again at 10:01 AM")

    with pytest.raises(UsageLimitWait):
        run_with_usage_limit_backoff(
            run,
            role="critic",
            now=lambda: datetime(2026, 5, 31, 10, 0, tzinfo=UTC),
            sleep=sleeps.append,
            record_event=lambda _event: None,
        )

    assert sleeps == [60.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_control_plane_usage_limit.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing functions.

- [ ] **Step 3: Implement shared usage-limit module**

Create `agent_control_plane/control_plane/usage_limit.py` by moving the parsing behavior from `task_control_plane.controller` into a generic module. The public functions must use this exact signature:

```python
from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any, TypeVar

T = TypeVar("T")


class UsageLimitWait(RuntimeError):
    def __init__(self, sleep_seconds: float, message: str) -> None:
        super().__init__(message)
        self.sleep_seconds = sleep_seconds


def parse_usage_limit_retry_at(message: str, now: datetime) -> datetime | None:
    if not _looks_like_usage_limit(message):
        return None
    return (
        _parse_relative_retry_time(message, now)
        or _parse_absolute_retry_time(message, now)
        or _parse_time_of_day_retry_time(message, now)
    )


def run_with_usage_limit_backoff(
    run: Callable[[], T],
    *,
    role: str,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    record_event: Callable[[dict[str, Any]], None] | None = None,
) -> T:
    clock = now or _local_now
    sleeper = sleep or time.sleep
    recorder = record_event or (lambda _event: None)
    waited = False
    while True:
        try:
            return run()
        except Exception as exc:
            current = _runtime_datetime(clock())
            message = _exception_message(exc)
            retry_at = parse_usage_limit_retry_at(message, current)
            if retry_at is None:
                raise
            if waited:
                raise UsageLimitWait(0.0, message) from exc
            waited = True
            sleep_seconds = max((retry_at - current).total_seconds(), 0.0)
            recorder(
                {
                    "type": "usage_limit",
                    "role": role,
                    "detected_at": current.isoformat(),
                    "suggested_retry_at": retry_at.isoformat(),
                    "sleep_seconds": sleep_seconds,
                    "message": message,
                }
            )
            sleeper(sleep_seconds)


def _looks_like_usage_limit(message: str) -> bool:
    normalized = message.lower()
    return any(
        marker in normalized
        for marker in (
            "usage limit",
            "rate limit",
            "quota",
            "too many requests",
            "limit reached",
            "limit exceeded",
        )
    )


def _parse_relative_retry_time(message: str, now: datetime) -> datetime | None:
    retry_after_match = re.search(
        r"\bretry-after\s*[:=]\s*(?P<seconds>\d+(?:\.\d+)?)\b",
        message,
        flags=re.IGNORECASE,
    )
    if retry_after_match:
        return now + timedelta(seconds=float(retry_after_match.group("seconds")))

    relative_match = re.search(
        r"\b(?:in|after)\s+(?P<duration>(?:\d+(?:\.\d+)?\s*"
        r"(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)"
        r"(?:\s*(?:,|and)?\s*)?)+)",
        message,
        flags=re.IGNORECASE,
    )
    if relative_match is None:
        return None
    seconds = 0.0
    for amount, unit in re.findall(
        r"(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)",
        relative_match.group("duration"),
        flags=re.IGNORECASE,
    ):
        seconds += float(amount) * _duration_unit_seconds(unit)
    if seconds <= 0:
        return None
    return now + timedelta(seconds=seconds)


def _parse_absolute_retry_time(message: str, now: datetime) -> datetime | None:
    iso_match = re.search(
        r"\b(?P<date>\d{4}-\d{2}-\d{2})[ T]"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
        r"(?P<zone>\s*(?:Z|UTC|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if iso_match:
        zone = _normalized_datetime_zone(iso_match.group("zone"))
        timestamp = f"{iso_match.group('date')}T{iso_match.group('time')}{zone}"
        try:
            return _runtime_datetime(datetime.fromisoformat(timestamp), now.tzinfo)
        except ValueError:
            return None
    return None


def _parse_time_of_day_retry_time(message: str, now: datetime) -> datetime | None:
    time_match = re.search(
        r"\b(?:at|after)\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)"
        r"(?:\s*(?P<zone>UTC|Z|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if time_match is None:
        return None
    time_text = _normalized_time_of_day(time_match.group("time"))
    for format_string in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(time_text, format_string)
        except ValueError:
            continue
        retry_at = datetime.combine(
            now.date(),
            parsed.time(),
            tzinfo=_timezone_from_retry_suffix(time_match.group("zone"), now.tzinfo),
        )
        if retry_at <= now:
            retry_at += timedelta(days=1)
        return retry_at
    return None


def _duration_unit_seconds(unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"s", "sec", "secs", "second", "seconds"}:
        return 1.0
    if normalized in {"m", "min", "mins", "minute", "minutes"}:
        return 60.0
    if normalized in {"h", "hr", "hrs", "hour", "hours"}:
        return 3600.0
    if normalized in {"d", "day", "days"}:
        return 86400.0
    raise ValueError(f"Unknown duration unit: {unit!r}.")


def _normalized_datetime_zone(zone: str | None) -> str:
    if zone is None or not zone.strip():
        return ""
    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return "+00:00"
    if re.fullmatch(r"[+-]\d{4}", normalized):
        return f"{normalized[:3]}:{normalized[3:]}"
    return normalized


def _normalized_time_of_day(time_text: str) -> str:
    normalized = time_text.strip().upper().replace(".", "")
    return re.sub(r"(?<=\d)(AM|PM)$", r" \1", normalized)


def _timezone_from_retry_suffix(zone: str | None, fallback_timezone: tzinfo | None) -> tzinfo:
    if zone is None or not zone.strip():
        return fallback_timezone or UTC
    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return UTC
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", normalized):
        offset = normalized.replace(":", "")
        sign = 1 if offset[0] == "+" else -1
        return timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
    return fallback_timezone or UTC


def _runtime_datetime(value: datetime, fallback_timezone: tzinfo | None = None) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=fallback_timezone or UTC)
    return value


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _exception_message(exc: Exception) -> str:
    if str(exc):
        return str(exc)
    if exc.args:
        return " ".join(str(arg) for arg in exc.args)
    return exc.__class__.__name__
```

- [ ] **Step 4: Refactor Task controller onto shared parser**

In `agent_control_plane/task_control_plane/controller.py`, replace `_usage_limit_retry_at` with a wrapper that calls `parse_usage_limit_retry_at`. Keep existing Task tests passing. Do not change Task state shape in this task.

```python
from agent_control_plane.control_plane.usage_limit import parse_usage_limit_retry_at


def _usage_limit_retry_at(exc: Exception, now: datetime) -> datetime | None:
    return parse_usage_limit_retry_at(_exception_message(exc), now)
```

Remove duplicate parser helper functions from the Task controller only after tests pass.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_control_plane_usage_limit.py tests/test_task_control_plane.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/control_plane/usage_limit.py agent_control_plane/task_control_plane/controller.py tests/test_control_plane_usage_limit.py
git commit -m "share usage limit backoff"
```

### Task 3: Shared Structured Command Runner

**Files:**
- Create: `agent_control_plane/control_plane/command_runner.py`
- Test: `tests/test_control_plane_command_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_control_plane_command_runner.py`:

```python
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from agent_control_plane.control_plane.command_runner import (
    CommandSpec,
    run_command,
    run_command_combined_log,
    write_command_metrics,
)


def test_run_command_rejects_empty_argv(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty argv"):
        run_command(
            CommandSpec(name="bad", argv=()),
            cwd=tmp_path,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )


def test_run_command_streams_stdout_and_stderr(tmp_path: Path) -> None:
    result = run_command(
        CommandSpec(
            name="stream",
            argv=(
                sys.executable,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr)",
            ),
        ),
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert "out" in (tmp_path / "stdout.log").read_text(encoding="utf-8")
    assert "err" in (tmp_path / "stderr.log").read_text(encoding="utf-8")
    assert result.stdout_path == str(tmp_path / "stdout.log")
    assert result.stderr_path == str(tmp_path / "stderr.log")


def test_run_command_injects_env(tmp_path: Path) -> None:
    result = run_command(
        CommandSpec(
            name="env",
            argv=(sys.executable, "-c", "import os; print(os.environ['DATA_ROOT'])"),
        ),
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        env={"DATA_ROOT": "/data/root"},
    )

    assert result.status == "passed"
    assert (tmp_path / "stdout.log").read_text(encoding="utf-8").strip().endswith("/data/root")


def test_run_command_timeout_kills_process(tmp_path: Path) -> None:
    start = time.monotonic()

    result = run_command(
        CommandSpec(
            name="timeout",
            argv=(sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=0.2,
        ),
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    assert time.monotonic() - start < 5
    assert result.status == "timed_out"
    assert result.exit_code is None
    assert "timed out" in (tmp_path / "stderr.log").read_text(encoding="utf-8")


def test_write_command_metrics(tmp_path: Path) -> None:
    result = run_command(
        CommandSpec(name="ok", argv=(sys.executable, "-c", "print('ok')")),
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    write_command_metrics(tmp_path / "command_metrics.json", [result])

    metrics = json.loads((tmp_path / "command_metrics.json").read_text(encoding="utf-8"))
    assert metrics["command_count"] == 1
    assert metrics["command_failed_count"] == 0
    assert metrics["commands"][0]["name"] == "ok"
    assert metrics["commands"][0]["passed"] == 1


def test_run_command_combined_log_writes_stdout_and_stderr_to_one_file(tmp_path: Path) -> None:
    result = run_command_combined_log(
        CommandSpec(
            name="combined",
            argv=(
                sys.executable,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr)",
            ),
        ),
        cwd=tmp_path,
        log_path=tmp_path / "command.log",
    )

    text = (tmp_path / "command.log").read_text(encoding="utf-8")
    assert result.status == "passed"
    assert "out" in text
    assert "err" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_control_plane_command_runner.py -q
```

Expected: FAIL with missing module/functions.

- [ ] **Step 3: Implement command runner**

Create `agent_control_plane/control_plane/command_runner.py` with dataclasses `CommandSpec` and `CommandResult`, plus `run_command` and `write_command_metrics`. Required behavior:

```python
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class CommandResult:
    name: str
    argv: list[str]
    cwd: str
    status: str
    exit_code: int | None
    duration_seconds: float
    timeout_seconds: float | None
    stdout_path: str
    stderr_path: str


def run_command(
    command: CommandSpec,
    *,
    cwd: str | Path,
    stdout_path: str | Path,
    stderr_path: str | Path,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if not command.argv or not all(isinstance(part, str) and part for part in command.argv):
        raise ValueError("CommandSpec requires non-empty argv strings.")
    cwd_path = Path(cwd).resolve()
    out_path = Path(stdout_path)
    err_path = Path(stderr_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    err_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    with out_path.open("a", encoding="utf-8", buffering=1) as stdout_log:
        with err_path.open("a", encoding="utf-8", buffering=1) as stderr_log:
            _write_header(stdout_log, command, cwd_path)
            _write_header(stderr_log, command, cwd_path)
            process = subprocess.Popen(
                list(command.argv),
                cwd=cwd_path,
                env=merged_env,
                shell=False,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            stdout_thread = threading.Thread(target=_stream_text, args=(process.stdout, stdout_log))
            stderr_thread = threading.Thread(target=_stream_text, args=(process.stderr, stderr_log))
            stdout_thread.start()
            stderr_thread.start()
            timed_out = False
            try:
                exit_code = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = None
                stderr_log.write(f"command timed out after {command.timeout_seconds} seconds\n")
                stderr_log.flush()
                _terminate_process_group(process)
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
    duration = round(time.monotonic() - started, 3)
    status = "timed_out" if timed_out else ("passed" if exit_code == 0 else "failed")
    return CommandResult(
        name=command.name,
        argv=list(command.argv),
        cwd=str(cwd_path),
        status=status,
        exit_code=exit_code,
        duration_seconds=duration,
        timeout_seconds=command.timeout_seconds,
        stdout_path=str(out_path),
        stderr_path=str(err_path),
    )


def write_command_metrics(path: str | Path, results: list[CommandResult]) -> None:
    data = {
        "command_count": len(results),
        "command_failed_count": sum(1 for result in results if result.status != "passed"),
        "command_duration_seconds": round(sum(result.duration_seconds for result in results), 3),
        "commands": [
            {
                **asdict(result),
                "passed": 1 if result.status == "passed" else 0,
            }
            for result in results
        ],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command_combined_log(
    command: CommandSpec,
    *,
    cwd: str | Path,
    log_path: str | Path,
    env: dict[str, str] | None = None,
) -> CommandResult:
    return run_command(
        command,
        cwd=cwd,
        stdout_path=log_path,
        stderr_path=log_path,
        env=env,
    )


def _write_header(handle: TextIO, command: CommandSpec, cwd: Path) -> None:
    handle.write(f"===== command START: {command.name} =====\n")
    handle.write(f"argv: {json.dumps(list(command.argv))}\n")
    handle.write(f"cwd: {cwd}\n")
    if command.timeout_seconds is not None:
        handle.write(f"timeout_seconds: {command.timeout_seconds}\n")
    handle.flush()


def _stream_text(pipe: TextIO | None, target: TextIO) -> None:
    if pipe is None:
        return
    try:
        for line in pipe:
            target.write(line)
            target.flush()
    finally:
        pipe.close()


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
```

Implementation note: keep the public API above, but avoid double-opening the same file when `run_command_combined_log` is used. Use one shared log handle or a private runner that understands combined output; do not depend on two append handles to the same path.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pixi run pytest tests/test_control_plane_command_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/control_plane/command_runner.py tests/test_control_plane_command_runner.py
git commit -m "add structured command runner"
```

### Task 4: Shared Generic Agent Runtime

**Files:**
- Create: `agent_control_plane/control_plane/agent_runtime.py`
- Modify: `agent_control_plane/task_control_plane/agent_runtime.py`
- Test: `tests/test_control_plane_agent_runtime.py`
- Test: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write failing shared runtime tests**

Create `tests/test_control_plane_agent_runtime.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_control_plane.control_plane import agent_runtime
from agent_control_plane.control_plane.agent_runtime import (
    AgentRunConfig,
    AgentRuntime,
    RoleCapabilities,
)


class FakeAgent:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls.append(kwargs)


class FakeSession:
    calls: list[dict[str, object]] = []

    def __init__(self, session_id: str, db_path: str | Path) -> None:
        self.session_id = session_id
        self.db_path = db_path
        self.calls.append({"session_id": session_id, "db_path": db_path})

    def close(self) -> None:
        return None


class FakeRunResult:
    final_output = {"status": "ok"}


class FakeRunner:
    calls: list[dict[str, object]] = []

    @classmethod
    def run_sync(cls, agent: FakeAgent, input: str, **kwargs: object) -> FakeRunResult:
        cls.calls.append({"agent": agent, "input": input, **kwargs})
        return FakeRunResult()


def test_generic_runtime_supports_arbitrary_read_only_role(
    tmp_path: Path, monkeypatch
) -> None:
    FakeAgent.calls = []
    FakeSession.calls = []
    FakeRunner.calls = []
    monkeypatch.setattr(agent_runtime, "Agent", FakeAgent)
    monkeypatch.setattr(agent_runtime, "SQLiteSession", FakeSession)
    monkeypatch.setattr(agent_runtime, "Runner", FakeRunner)

    runtime = AgentRuntime(thread_id_factory=lambda role: f"{role}-thread")
    thread = runtime.open_thread(
        AgentRunConfig(
            role="research-strategist",
            cwd=tmp_path,
            instructions="You are the strategist.",
            capabilities=RoleCapabilities.READ_ONLY,
            session_db_path=tmp_path / "sessions.sqlite3",
        )
    )
    result = thread.run("plan", AgentRunConfig(role="research-strategist", cwd=tmp_path))

    assert thread.id == "research-strategist-thread"
    assert result.final_response == '{"status": "ok"}'
    assert FakeAgent.calls[0]["name"] == "research-strategist"
    assert "You are the strategist." in str(FakeAgent.calls[0]["instructions"])
    assert len(FakeAgent.calls[0]["tools"]) == 3


def test_generic_runtime_enables_workspace_write_tools(tmp_path: Path, monkeypatch) -> None:
    FakeAgent.calls = []
    FakeSession.calls = []
    FakeRunner.calls = []
    monkeypatch.setattr(agent_runtime, "Agent", FakeAgent)
    monkeypatch.setattr(agent_runtime, "SQLiteSession", FakeSession)
    monkeypatch.setattr(agent_runtime, "Runner", FakeRunner)

    runtime = AgentRuntime(thread_id_factory=lambda role: f"{role}-thread")
    thread = runtime.open_thread(
        AgentRunConfig(
            role="research-evaluator",
            cwd=tmp_path,
            capabilities=RoleCapabilities.WORKSPACE_WRITE,
        )
    )
    thread.run("evaluate", AgentRunConfig(role="research-evaluator", cwd=tmp_path))

    tool_names = [tool.name for tool in FakeAgent.calls[0]["tools"]]
    assert tool_names == ["read_file", "list_files", "search_text", "shell", "apply_patch"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_control_plane_agent_runtime.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Move generic runtime code**

Create `agent_control_plane/control_plane/agent_runtime.py` by adapting `task_control_plane/agent_runtime.py`:

- Replace `AgentRole = Literal[...]` with `role: str`.
- Add enum:

```python
from enum import Enum


class RoleCapabilities(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
```

- Change `AgentRunConfig` fields to:

```python
@dataclass(frozen=True)
class AgentRunConfig:
    role: str
    cwd: str | Path
    instructions: str | None = None
    capabilities: RoleCapabilities = RoleCapabilities.READ_ONLY
    model: str | None = None
    effort: str | None = None
    output_schema: dict[str, Any] | None = None
    thread_id: str | None = None
    session_db_path: str | Path | None = None
```

- Use `name=config.role` for the OpenAI agent name.
- Use `config.instructions` instead of `developer_instructions`.
- Use write tools only when `config.capabilities == RoleCapabilities.WORKSPACE_WRITE`.
- Preserve JSON schema output validation, read tools, shell tool, and apply-patch tool behavior.

- [ ] **Step 4: Keep Task compatibility**

Replace `agent_control_plane/task_control_plane/agent_runtime.py` with a compatibility wrapper that keeps existing imports working:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Literal

from agent_control_plane.control_plane.agent_runtime import (
    AgentRunConfig as SharedAgentRunConfig,
    AgentRuntime as SharedAgentRuntime,
    AgentThread,
    AgentTurnResult,
    RoleCapabilities,
    _JsonSchemaOutput,
)

AgentRole = Literal["planner", "context", "implementer", "reviewer"]


@dataclass(frozen=True)
class AgentRunConfig:
    role: AgentRole
    cwd: str | Path
    developer_instructions: str | None = None
    model: str | None = None
    effort: str | None = None
    output_schema: dict[str, Any] | None = None
    thread_id: str | None = None
    session_db_path: str | Path | None = None


class AgentRuntime:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._shared = SharedAgentRuntime(*args, **kwargs)

    def __enter__(self) -> AgentRuntime:
        self._shared.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._shared.__exit__(*exc_info)

    def open_thread(self, config: AgentRunConfig) -> AgentThread:
        return self._shared.open_thread(_to_shared_config(config))


def _to_shared_config(config: AgentRunConfig) -> SharedAgentRunConfig:
    capabilities = (
        RoleCapabilities.WORKSPACE_WRITE
        if config.role == "implementer"
        else RoleCapabilities.READ_ONLY
    )
    return SharedAgentRunConfig(
        role=f"task-control-{config.role}",
        cwd=config.cwd,
        instructions=config.developer_instructions,
        capabilities=capabilities,
        model=config.model,
        effort=config.effort,
        output_schema=config.output_schema,
        thread_id=config.thread_id,
        session_db_path=config.session_db_path,
    )
```

- [ ] **Step 5: Run runtime tests**

Run:

```bash
pixi run pytest tests/test_control_plane_agent_runtime.py tests/test_agent_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/control_plane/agent_runtime.py agent_control_plane/task_control_plane/agent_runtime.py tests/test_control_plane_agent_runtime.py
git commit -m "share agent runtime"
```

### Task 5: Research Run Spec Loader

**Files:**
- Create: `agent_control_plane/research_experiment_controller/__init__.py`
- Create: `agent_control_plane/research_experiment_controller/research_run_spec.py`
- Test: `tests/test_research_run_spec.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_run_spec.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller.research_run_spec import (
    ResearchRunSpecError,
    load_research_run_spec,
)


def write_spec(tmp_path: Path, repo: Path) -> Path:
    path = tmp_path / "research-run.yaml"
    path.write_text(
        f"""
version: 1
research_run_id: peer-residual-v1
target_repository: {repo}
max_experiments: 5
research_brief: |
  Test peer residual forecasting.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
  research:
    month_start: "2020-01"
    month_end: "2026-01"
    max_runtime_minutes: 240
data_root: /mnt/redbackup/data
worktree:
  create: true
  root: .worktrees
mlflow:
  enabled: true
  tracking_uri: file:/tmp/mlruns
  experiment_name: peer-residual-v1
codex:
  model: gpt-5.3-codex
  effort: xhigh
implementation:
  max_repairs: 3
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return path


def test_load_research_run_spec(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    spec = load_research_run_spec(write_spec(tmp_path, repo))

    assert spec.research_run_id == "peer-residual-v1"
    assert spec.target_repository == repo.resolve()
    assert spec.max_experiments == 5
    assert spec.research_brief.strip() == "Test peer residual forecasting."
    assert spec.budget == "smoke"
    assert spec.selected_budget.month_start == "2026-01"
    assert spec.selected_budget.max_runtime_minutes == 5
    assert spec.data_root == Path("/mnt/redbackup/data")
    assert spec.worktree.create is True
    assert spec.worktree.root == Path(".worktrees")
    assert spec.mlflow.enabled is True
    assert spec.codex.model == "gpt-5.3-codex"
    assert spec.codex.effort == "xhigh"
    assert spec.implementation.max_repairs == 3
    assert spec.stop_on_prerequisites_failed is True


def test_missing_selected_budget_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_spec(tmp_path, repo)
    text = path.read_text(encoding="utf-8").replace("budget: smoke", "budget: missing")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ResearchRunSpecError, match="selected budget"):
        load_research_run_spec(path)


def test_shell_command_fields_are_not_supported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_spec(tmp_path, repo)
    path.write_text(path.read_text(encoding="utf-8") + "\ncommands: echo bad\n", encoding="utf-8")

    with pytest.raises(ResearchRunSpecError, match="Unsupported"):
        load_research_run_spec(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_run_spec.py -q
```

Expected: FAIL with missing package/module.

- [ ] **Step 3: Implement spec loader**

Create `agent_control_plane/research_experiment_controller/__init__.py`:

```python
"""Research Experiment Controller workflow package."""
```

Create `agent_control_plane/research_experiment_controller/research_run_spec.py` with dataclasses:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

UNSUPPORTED_FIELDS = frozenset({"commands", "eval_inputs", "service_tier", "dependencies"})


@dataclass(frozen=True)
class ResearchBudget:
    month_start: str
    month_end: str
    max_runtime_minutes: int


@dataclass(frozen=True)
class WorktreeConfig:
    create: bool = True
    root: Path = Path(".worktrees")


@dataclass(frozen=True)
class MLflowConfig:
    enabled: bool = False
    tracking_uri: str | None = None
    experiment_name: str | None = None


@dataclass(frozen=True)
class CodexConfig:
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class ImplementationConfig:
    max_repairs: int = 3


@dataclass(frozen=True)
class ResearchRunSpec:
    source_path: Path
    version: int
    research_run_id: str
    target_repository: Path
    max_experiments: int
    research_brief: str
    budget: str
    budgets: dict[str, ResearchBudget]
    selected_budget: ResearchBudget
    data_root: Path
    worktree: WorktreeConfig
    mlflow: MLflowConfig
    codex: CodexConfig
    implementation: ImplementationConfig
    stop_on_prerequisites_failed: bool


class ResearchRunSpecError(ValueError):
    """Raised when a Research Run Spec cannot be loaded."""


def load_research_run_spec(path: str | Path) -> ResearchRunSpec:
    source_path = Path(path)
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ResearchRunSpecError("Research Run Spec must be a mapping.")
    for field in data:
        if field in UNSUPPORTED_FIELDS:
            raise ResearchRunSpecError(f"Unsupported Research Run Spec field '{field}'.")

    budgets = _load_budgets(data.get("budgets"))
    budget_name = _required_string(data, "budget")
    selected_budget = budgets.get(budget_name)
    if selected_budget is None:
        raise ResearchRunSpecError(f"Research Run Spec selected budget is missing: {budget_name}")

    return ResearchRunSpec(
        source_path=source_path.resolve(),
        version=int(data.get("version", 1)),
        research_run_id=_required_string(data, "research_run_id"),
        target_repository=Path(_required_string(data, "target_repository")).expanduser().resolve(),
        max_experiments=_positive_int(data, "max_experiments", 1),
        research_brief=_required_string(data, "research_brief"),
        budget=budget_name,
        budgets=budgets,
        selected_budget=selected_budget,
        data_root=Path(_required_string(data, "data_root")).expanduser(),
        worktree=_load_worktree(data.get("worktree")),
        mlflow=_load_mlflow(data.get("mlflow")),
        codex=_load_codex(data.get("codex")),
        implementation=_load_implementation(data.get("implementation")),
        stop_on_prerequisites_failed=bool(data.get("stop_on_prerequisites_failed", True)),
    )


def _load_budgets(value: Any) -> dict[str, ResearchBudget]:
    if not isinstance(value, dict) or not value:
        raise ResearchRunSpecError("Research Run Spec field 'budgets' must be a non-empty mapping.")
    budgets: dict[str, ResearchBudget] = {}
    for name, item in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ResearchRunSpecError("Research Budget names must be non-empty strings.")
        if not isinstance(item, dict):
            raise ResearchRunSpecError(f"Research Budget '{name}' must be a mapping.")
        budgets[name] = ResearchBudget(
            month_start=_required_string(item, "month_start"),
            month_end=_required_string(item, "month_end"),
            max_runtime_minutes=_positive_int(item, "max_runtime_minutes", 1),
        )
    return budgets


def _load_worktree(value: Any) -> WorktreeConfig:
    data = value if isinstance(value, dict) else {}
    return WorktreeConfig(create=bool(data.get("create", True)), root=Path(str(data.get("root", ".worktrees"))))


def _load_mlflow(value: Any) -> MLflowConfig:
    data = value if isinstance(value, dict) else {}
    return MLflowConfig(
        enabled=bool(data.get("enabled", False)),
        tracking_uri=_optional_string(data, "tracking_uri"),
        experiment_name=_optional_string(data, "experiment_name"),
    )


def _load_codex(value: Any) -> CodexConfig:
    data = value if isinstance(value, dict) else {}
    return CodexConfig(model=_optional_string(data, "model"), effort=_optional_string(data, "effort"))


def _load_implementation(value: Any) -> ImplementationConfig:
    data = value if isinstance(value, dict) else {}
    return ImplementationConfig(max_repairs=_positive_int(data, "max_repairs", 3))


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchRunSpecError(f"Research Run Spec field '{field}' is required.")
    return value


def _optional_string(data: dict[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchRunSpecError(f"Research Run Spec field '{field}' must be a string.")
    return value


def _positive_int(data: dict[str, Any], field: str, default: int) -> int:
    value = int(data.get(field, default))
    if value <= 0:
        raise ResearchRunSpecError(f"Research Run Spec field '{field}' must be positive.")
    return value
```

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_run_spec.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/__init__.py agent_control_plane/research_experiment_controller/research_run_spec.py tests/test_research_run_spec.py
git commit -m "load research run specs"
```

### Task 6: Research Artifact Models

**Files:**
- Create: `agent_control_plane/research_experiment_controller/artifacts.py`
- Modify: `pixi.toml`
- Test: `tests/test_research_artifacts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_artifacts.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_control_plane.research_experiment_controller.artifacts import (
    ConfirmatoryEvaluationResult,
    ExperimentDesign,
    ResearchOutcome,
    ResearchSpec,
    SelectedPlan,
)


def test_research_outcome_values() -> None:
    assert [item.value for item in ResearchOutcome] == [
        "no_op",
        "blocked",
        "prerequisites_failed",
        "invalid",
        "run_failed",
        "completed_rejected",
        "completed_inconclusive",
        "completed_candidate",
    ]


def test_research_spec_preserves_locked_gates() -> None:
    spec = ResearchSpec(
        hypothesis="Peer residuals forecast next-month returns.",
        target="next_month_return",
        prediction_horizon="1M",
        universe="hyperliquid_perps",
        label="forward_return_1m",
        feature_availability_assumptions=["features lagged one bar"],
        split={"train": "2020-01:2024-12", "test": "2025-01:2026-01"},
        primary_metric="information_coefficient",
        secondary_metrics=["turnover"],
        baselines=["market_neutral_null"],
        null_tests=["symbol_shuffle"],
        transaction_cost_assumptions="5 bps",
        success_gates={"information_coefficient": 0.03},
        failure_gates={"information_coefficient": 0.0},
        inconclusive_gates={"min_observations": 100},
    )

    assert spec.success_gates == {"information_coefficient": 0.03}


def test_experiment_design_requires_structured_commands() -> None:
    design = ExperimentDesign(
        prerequisite_commands=[],
        data_audit_commands=[],
        verification_commands=[{"name": "unit", "argv": ["pytest", "-q"]}],
        confirmatory_commands=[{"name": "eval", "argv": ["python", "eval.py"]}],
        exploratory_commands=[],
        expected_outputs=["metrics.json"],
        allowed_write_paths=["research/experiments"],
        timeout_seconds=300,
        resource_budgets={"budget": "smoke"},
        failure_routing={"data": "prerequisites_failed"},
    )

    assert design.verification_commands[0].argv == ["pytest", "-q"]


def test_selected_plan_selects_one_plan() -> None:
    selected = SelectedPlan(
        selected=True,
        plan_id="plan-1",
        rationale="Best admissible design.",
        material_revision_categories=[],
    )

    assert selected.selected is True


def test_final_eval_result_uses_single_outcome_axis() -> None:
    result = ConfirmatoryEvaluationResult(
        outcome=ResearchOutcome.completed_candidate,
        outcome_reason="Locked gates passed.",
        failed_stage=None,
        failure_classification=None,
        metrics={"ic": 0.04},
        gate_results={"information_coefficient": "passed"},
        pre_registered_evidence=["confirmatory command eval"],
    )

    assert result.outcome is ResearchOutcome.completed_candidate


def test_invalid_outcome_rejected() -> None:
    with pytest.raises(ValidationError):
        ConfirmatoryEvaluationResult(
            outcome="success",
            outcome_reason="bad axis",
            failed_stage=None,
            failure_classification=None,
            metrics={},
            gate_results={},
            pre_registered_evidence=[],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_artifacts.py -q
```

Expected: FAIL with missing artifact models.

- [ ] **Step 3: Add explicit Pydantic dependency**

Modify `pixi.toml` under `[dependencies]`:

```toml
pydantic = ">=2,<3"
```

This makes Pydantic an explicit project dependency instead of relying on transitive Hatchet dependencies.

- [ ] **Step 4: Implement artifact models**

Create `agent_control_plane/research_experiment_controller/artifacts.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResearchOutcome(str, Enum):
    no_op = "no_op"
    blocked = "blocked"
    prerequisites_failed = "prerequisites_failed"
    invalid = "invalid"
    run_failed = "run_failed"
    completed_rejected = "completed_rejected"
    completed_inconclusive = "completed_inconclusive"
    completed_candidate = "completed_candidate"


class CommandDeclaration(BaseModel):
    name: str
    argv: list[str] = Field(min_length=1)
    timeout_seconds: float | None = None
    phase: str | None = None


class ContextSummary(BaseModel):
    summary: str
    prior_blockers: list[str] = Field(default_factory=list)
    completed_prerequisites: list[str] = Field(default_factory=list)
    metric_hints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    hypothesis: str
    rationale: str
    signal_family: str
    expected_mechanism: str
    known_risks: list[str]
    falsification_evidence: list[str]


class ResearchSpec(BaseModel):
    hypothesis: str
    target: str
    prediction_horizon: str
    universe: str
    label: str
    feature_availability_assumptions: list[str]
    split: dict[str, Any]
    primary_metric: str
    secondary_metrics: list[str]
    baselines: list[str]
    null_tests: list[str]
    transaction_cost_assumptions: str
    success_gates: dict[str, Any]
    failure_gates: dict[str, Any]
    inconclusive_gates: dict[str, Any]


class ExperimentDesign(BaseModel):
    prerequisite_commands: list[CommandDeclaration] = Field(default_factory=list)
    data_audit_commands: list[CommandDeclaration] = Field(default_factory=list)
    verification_commands: list[CommandDeclaration] = Field(default_factory=list)
    confirmatory_commands: list[CommandDeclaration] = Field(default_factory=list)
    exploratory_commands: list[CommandDeclaration] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    allowed_write_paths: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    resource_budgets: dict[str, Any] = Field(default_factory=dict)
    failure_routing: dict[str, Any] = Field(default_factory=dict)


class Critique(BaseModel):
    decision: str
    fatal_issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)
    material_revision_categories: list[str] = Field(default_factory=list)
    leakage_risks: list[str] = Field(default_factory=list)
    baseline_concerns: list[str] = Field(default_factory=list)
    gate_concerns: list[str] = Field(default_factory=list)


class SelectedPlan(BaseModel):
    selected: bool
    plan_id: str | None = None
    rationale: str
    material_revision_categories: list[str] = Field(default_factory=list)


class DataAudit(BaseModel):
    passed: bool
    outcome_reason: str
    failure_classification: str | None = None
    command_results: list[dict[str, Any]] = Field(default_factory=list)


class Implementation(BaseModel):
    status: str
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    commands_declared: list[CommandDeclaration] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ImplementationRepair(BaseModel):
    repair_attempt: int
    summary: str
    changed_files: list[str] = Field(default_factory=list)


class ImplementationDiffSummary(BaseModel):
    changed_files: list[str]
    allowed_path_violations: list[str] = Field(default_factory=list)
    evaluation_logic_changed: bool = False
    data_handling_changed: bool = False
    high_risk: bool = False
    notes: list[str] = Field(default_factory=list)


class ConfirmatoryEvaluationResult(BaseModel):
    outcome: ResearchOutcome
    outcome_reason: str
    failed_stage: str | None
    failure_classification: str | None
    metrics: dict[str, Any] = Field(default_factory=dict)
    gate_results: dict[str, Any] = Field(default_factory=dict)
    pre_registered_evidence: list[str] = Field(default_factory=list)


class ExploratoryDiagnosticsResult(BaseModel):
    findings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    plots: list[str] = Field(default_factory=list)
    future_experiment_ideas: list[str] = Field(default_factory=list)


class AnalysisLedger(BaseModel):
    entries: list[dict[str, Any]] = Field(default_factory=list)


class EmpiricalCritique(BaseModel):
    status_supported: bool
    concerns: list[str] = Field(default_factory=list)
    overclaiming_risks: list[str] = Field(default_factory=list)
    recommended_outcome: ResearchOutcome


class Summary(BaseModel):
    outcome: ResearchOutcome
    summary: str
    confirmatory_findings: list[str] = Field(default_factory=list)
    exploratory_findings: list[str] = Field(default_factory=list)


class PlanUpdate(BaseModel):
    followups: list[str] = Field(default_factory=list)
    revisit_conditions: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_artifacts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/artifacts.py pixi.toml tests/test_research_artifacts.py
git commit -m "define research artifacts"
```

### Task 7: Research State And Ledger

**Files:**
- Create: `agent_control_plane/research_experiment_controller/state.py`
- Create: `agent_control_plane/research_experiment_controller/ledger.py`
- Test: `tests/test_research_state_and_ledger.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_state_and_ledger.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_control_plane.research_experiment_controller.ledger import append_event, read_events
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    experiment_directory,
    next_experiment_id,
    research_run_directory,
)


def test_research_run_directory_is_scoped_by_run_id(tmp_path: Path) -> None:
    path = research_run_directory(tmp_path, "peer-residual-v1")

    assert path == tmp_path / "peer-residual-v1"


def test_create_initial_state(tmp_path: Path) -> None:
    state = create_initial_state(
        research_run_id="peer-residual-v1",
        run_directory=tmp_path / "peer-residual-v1",
        spec_snapshot_path=tmp_path / "peer-residual-v1" / "research_run_spec.yaml",
        max_experiments=3,
    )

    assert state["research_run_id"] == "peer-residual-v1"
    assert state["status"] == "running"
    assert state["current_phase"] == "ready_for_experiment"
    assert state["controller_state_version"] == 1
    assert state["experiments"] == []


def test_next_experiment_id_counts_existing_experiments() -> None:
    state = {"experiments": [{"experiment_id": "EXP-0001"}]}

    assert next_experiment_id(state) == "EXP-0002"


def test_experiment_directory(tmp_path: Path) -> None:
    assert experiment_directory(tmp_path, "EXP-0002") == tmp_path / "experiments" / "EXP-0002"


def test_ledger_events_round_trip(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"

    append_event(ledger_path, {"event": "START", "research_run_id": "run-1"})
    append_event(ledger_path, {"event": "COMPLETE", "experiment_id": "EXP-0001"})

    assert [event["event"] for event in read_events(ledger_path)] == ["START", "COMPLETE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_state_and_ledger.py -q
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement state and ledger**

Create `agent_control_plane/research_experiment_controller/ledger.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agent_control_plane.control_plane.json_artifacts import append_jsonl, read_jsonl


def append_event(path: str | Path, event: Mapping[str, Any]) -> None:
    append_jsonl(path, event)


def read_events(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(path)
```

Create `agent_control_plane/research_experiment_controller/state.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def research_run_directory(runtime_root: str | Path, research_run_id: str) -> Path:
    return Path(runtime_root).resolve() / research_run_id


def experiment_directory(run_directory: str | Path, experiment_id: str) -> Path:
    return Path(run_directory) / "experiments" / experiment_id


def create_initial_state(
    *,
    research_run_id: str,
    run_directory: str | Path,
    spec_snapshot_path: str | Path,
    max_experiments: int,
) -> dict[str, Any]:
    return {
        "controller_state_version": 1,
        "research_run_id": research_run_id,
        "status": "running",
        "current_phase": "ready_for_experiment",
        "run_directory": str(Path(run_directory)),
        "spec_snapshot_path": str(Path(spec_snapshot_path)),
        "max_experiments": max_experiments,
        "experiments": [],
        "threads": {},
    }


def next_experiment_id(state: dict[str, Any]) -> str:
    experiments = state.get("experiments", [])
    if not isinstance(experiments, list):
        raise ValueError("Research state field 'experiments' must be a list.")
    return f"EXP-{len(experiments) + 1:04d}"
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_state_and_ledger.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/state.py agent_control_plane/research_experiment_controller/ledger.py tests/test_research_state_and_ledger.py
git commit -m "add research state ledger"
```

### Task 8: Boundary Audit Helpers

**Files:**
- Create: `agent_control_plane/control_plane/boundary_audit.py`
- Test: `tests/test_control_plane_boundary_audit.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_control_plane_boundary_audit.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.control_plane.boundary_audit import (
    assert_allowed_paths,
    git_snapshot,
    hash_manifest,
    verify_hash_manifest,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def test_git_snapshot_detects_changed_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    before = git_snapshot(repo)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    after = git_snapshot(repo)

    assert before.status == ""
    assert "README.md" in after.status


def test_assert_allowed_paths_accepts_nested_allowed_file() -> None:
    assert_allowed_paths(["research/experiments/a.py"], ["research/experiments"])


def test_assert_allowed_paths_rejects_outside_file() -> None:
    with pytest.raises(ValueError, match="outside allowed paths"):
        assert_allowed_paths(["pipeline/prod.py"], ["research/experiments"])


def test_hash_manifest_verification(tmp_path: Path) -> None:
    locked = tmp_path / "selected_plan.json"
    locked.write_text('{"selected": true}\n', encoding="utf-8")
    manifest = hash_manifest([locked])

    verify_hash_manifest(manifest)
    locked.write_text('{"selected": false}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="hash changed"):
        verify_hash_manifest(manifest)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_control_plane_boundary_audit.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement boundary audit helpers**

Create `agent_control_plane/control_plane/boundary_audit.py`:

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agent_control_plane.control_plane.json_artifacts import file_sha256


@dataclass(frozen=True)
class GitSnapshot:
    repository: str
    status: str
    diff: str


def git_snapshot(repository: str | Path) -> GitSnapshot:
    repo = Path(repository).resolve()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise ValueError(f"Could not inspect git status: {status.stderr.strip()}")
    diff = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if diff.returncode not in {0, 1}:
        raise ValueError(f"Could not inspect git diff: {diff.stderr.strip()}")
    return GitSnapshot(repository=str(repo), status=status.stdout, diff=diff.stdout)


def assert_allowed_paths(changed_files: Iterable[str], allowed_paths: Iterable[str]) -> None:
    normalized_allowed = tuple(_normalize_relative(path) for path in allowed_paths)
    violations = []
    for changed in changed_files:
        relative = _normalize_relative(changed)
        if not any(relative == allowed or relative.startswith(f"{allowed}/") for allowed in normalized_allowed):
            violations.append(relative)
    if violations:
        raise ValueError(f"Changed files outside allowed paths: {', '.join(violations)}")


def hash_manifest(paths: Iterable[str | Path]) -> dict[str, str]:
    return {str(Path(path).resolve()): file_sha256(path) for path in paths}


def verify_hash_manifest(manifest: dict[str, str]) -> None:
    for path, expected_hash in manifest.items():
        actual_hash = file_sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(f"Locked artifact hash changed: {path}")


def _normalize_relative(path: str | Path) -> str:
    value = str(path).replace("\\", "/").strip("/")
    if value == "." or value.startswith("../") or "/../" in value:
        raise ValueError(f"Unsafe relative path: {path}")
    return value
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_control_plane_boundary_audit.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/control_plane/boundary_audit.py tests/test_control_plane_boundary_audit.py
git commit -m "add boundary audit helpers"
```

### Task 9: Experiment Worktree

**Files:**
- Create: `agent_control_plane/research_experiment_controller/worktree.py`
- Test: `tests/test_research_worktree.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_worktree.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller.worktree import (
    ExperimentWorktreeError,
    prepare_experiment_worktree,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def test_prepare_experiment_worktree_creates_scoped_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)

    worktree = prepare_experiment_worktree(
        target_repository=repo,
        worktree_root=tmp_path / ".worktrees",
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )

    assert worktree.path.exists()
    assert worktree.path == (tmp_path / ".worktrees" / "run-1" / "EXP-0001").resolve()
    assert worktree.branch.startswith("research/run-1/EXP-0001")


def test_dirty_existing_worktree_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    worktree = prepare_experiment_worktree(
        target_repository=repo,
        worktree_root=tmp_path / ".worktrees",
        research_run_id="run-1",
        experiment_id="EXP-0001",
    )
    (worktree.path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ExperimentWorktreeError, match="dirty"):
        prepare_experiment_worktree(
            target_repository=repo,
            worktree_root=tmp_path / ".worktrees",
            research_run_id="run-1",
            experiment_id="EXP-0001",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_worktree.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement worktree helper**

Create `agent_control_plane/research_experiment_controller/worktree.py`:

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class ExperimentWorktreeError(RuntimeError):
    """Raised when an Experiment Worktree cannot be prepared safely."""


@dataclass(frozen=True)
class ExperimentWorktree:
    path: Path
    branch: str
    created: bool


def prepare_experiment_worktree(
    *,
    target_repository: str | Path,
    worktree_root: str | Path,
    research_run_id: str,
    experiment_id: str,
) -> ExperimentWorktree:
    repo = Path(target_repository).resolve()
    path = (Path(worktree_root).resolve() / research_run_id / experiment_id).resolve()
    branch = _branch_name(research_run_id, experiment_id)
    if path.exists():
        _require_clean_worktree(path)
        return ExperimentWorktree(path=path, branch=branch, created=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(path), "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ExperimentWorktreeError(result.stderr.strip() or result.stdout.strip())
    return ExperimentWorktree(path=path, branch=branch, created=True)


def _require_clean_worktree(path: Path) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise ExperimentWorktreeError(f"Could not inspect worktree status: {status.stderr.strip()}")
    if status.stdout.strip():
        raise ExperimentWorktreeError(f"Existing Experiment Worktree is dirty: {path}")


def _branch_name(research_run_id: str, experiment_id: str) -> str:
    raw = f"research/{research_run_id}/{experiment_id}"
    return raw[:120]
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_worktree.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/worktree.py tests/test_research_worktree.py
git commit -m "prepare experiment worktrees"
```

### Task 10: Evaluator Workspace And Boundary Audit

**Files:**
- Create: `agent_control_plane/research_experiment_controller/evaluation.py`
- Test: `tests/test_research_evaluation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_evaluation.py`:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller.evaluation import (
    EvaluationBoundaryError,
    create_evaluator_workspace,
    run_evaluation_boundary_audit,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=path, check=True)
    (path / "README.md").write_text("ready\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def test_create_evaluator_workspace_writes_manifest_with_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    worktree = tmp_path / "worktree"
    run_dir.mkdir()
    worktree.mkdir()
    selected_plan = run_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")

    workspace = create_evaluator_workspace(
        experiment_run_dir=run_dir,
        worktree_path=worktree,
        data_root=Path("/data"),
        git_sha="abc123",
        locked_artifacts=[selected_plan],
        confirmatory_commands=[{"name": "eval", "argv": ["python", "eval.py"]}],
    )

    manifest = json.loads((workspace.path / "manifest.json").read_text(encoding="utf-8"))
    assert workspace.path == run_dir / "evaluation"
    assert (workspace.path / "eval_scratch").is_dir()
    assert (workspace.path / "eval_outputs").is_dir()
    assert manifest["worktree_path"] == str(worktree)
    assert manifest["locked_artifacts"][0]["path"] == str(selected_plan.resolve())
    assert "sha256" in manifest["locked_artifacts"][0]
    assert "eval_inputs" not in [path.name for path in workspace.path.iterdir()]


def test_boundary_audit_detects_locked_artifact_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    selected_plan = run_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_run_dir=run_dir,
        worktree_path=repo,
        data_root=Path("/data"),
        git_sha="abc123",
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )
    selected_plan.write_text('{"selected": false}\n', encoding="utf-8")

    with pytest.raises(EvaluationBoundaryError, match="Locked artifact"):
        run_evaluation_boundary_audit(workspace.manifest_path)


def test_boundary_audit_detects_worktree_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    selected_plan = run_dir / "selected_plan.json"
    selected_plan.write_text('{"selected": true}\n', encoding="utf-8")
    workspace = create_evaluator_workspace(
        experiment_run_dir=run_dir,
        worktree_path=repo,
        data_root=Path("/data"),
        git_sha="abc123",
        locked_artifacts=[selected_plan],
        confirmatory_commands=[],
    )
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(EvaluationBoundaryError, match="worktree changed"):
        run_evaluation_boundary_audit(workspace.manifest_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_evaluation.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement evaluator workspace**

Create `agent_control_plane/research_experiment_controller/evaluation.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.boundary_audit import git_snapshot
from agent_control_plane.control_plane.json_artifacts import file_sha256, write_json


class EvaluationBoundaryError(RuntimeError):
    """Raised when evaluation modifies locked inputs or the Experiment Worktree."""


@dataclass(frozen=True)
class EvaluatorWorkspace:
    path: Path
    manifest_path: Path


def create_evaluator_workspace(
    *,
    experiment_run_dir: str | Path,
    worktree_path: str | Path,
    data_root: str | Path,
    git_sha: str,
    locked_artifacts: list[str | Path],
    confirmatory_commands: list[dict[str, Any]],
) -> EvaluatorWorkspace:
    run_dir = Path(experiment_run_dir)
    workspace = run_dir / "evaluation"
    scratch = workspace / "eval_scratch"
    outputs = workspace / "eval_outputs"
    scratch.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = git_snapshot(worktree_path)
    manifest = {
        "run_dir": str(run_dir.resolve()),
        "worktree_path": str(Path(worktree_path).resolve()),
        "data_root": str(Path(data_root)),
        "git_sha": git_sha,
        "confirmatory_commands": confirmatory_commands,
        "locked_artifacts": [
            {"path": str(Path(path).resolve()), "sha256": file_sha256(path)}
            for path in locked_artifacts
        ],
        "pre_evaluation_worktree_status": before.status,
        "pre_evaluation_worktree_diff": before.diff,
        "eval_scratch": str(scratch.resolve()),
        "eval_outputs": str(outputs.resolve()),
    }
    manifest_path = workspace / "manifest.json"
    write_json(manifest_path, manifest)
    return EvaluatorWorkspace(path=workspace, manifest_path=manifest_path)


def run_evaluation_boundary_audit(manifest_path: str | Path) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    worktree_path = Path(manifest["worktree_path"])
    after = git_snapshot(worktree_path)
    if after.status != manifest.get("pre_evaluation_worktree_status", ""):
        raise EvaluationBoundaryError("Evaluation boundary audit failed: worktree changed.")
    for item in manifest.get("locked_artifacts", []):
        path = Path(item["path"])
        expected_hash = item["sha256"]
        if file_sha256(path) != expected_hash:
            raise EvaluationBoundaryError(f"Locked artifact hash changed: {path}")
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/evaluation.py tests/test_research_evaluation.py
git commit -m "add evaluator workspace audit"
```

### Task 11: Research Context Pack

**Files:**
- Create: `agent_control_plane/research_experiment_controller/context.py`
- Test: `tests/test_research_context.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_context.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_control_plane.research_experiment_controller.context import build_context_pack


def test_context_pack_includes_brief_budget_data_root_and_prior_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    previous = run_dir / "experiments" / "EXP-0001"
    previous.mkdir(parents=True)
    (previous / "summary.json").write_text(
        '{"outcome": "completed_rejected", "summary": "IC under gate"}\n',
        encoding="utf-8",
    )

    text = build_context_pack(
        research_run_id="peer-residual-v1",
        research_brief="Test peer residual forecasting.",
        budget_name="smoke",
        budget={"month_start": "2026-01", "month_end": "2026-01", "max_runtime_minutes": 5},
        data_root=Path("/mnt/redbackup/data"),
        target_repository=tmp_path,
        run_directory=run_dir,
    )

    assert "Research Run: peer-residual-v1" in text
    assert "Test peer residual forecasting." in text
    assert "Budget: smoke" in text
    assert "month_start: 2026-01" in text
    assert "Data Root: /mnt/redbackup/data" in text
    assert "EXP-0001" in text
    assert "completed_rejected" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_context.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement context pack builder**

Create `agent_control_plane/research_experiment_controller/context.py`:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


def build_context_pack(
    *,
    research_run_id: str,
    research_brief: str,
    budget_name: str,
    budget: Mapping[str, Any],
    data_root: str | Path,
    target_repository: str | Path,
    run_directory: str | Path,
) -> str:
    repo = Path(target_repository).resolve()
    run_dir = Path(run_directory)
    lines = [
        f"# Research Context Pack",
        "",
        f"Research Run: {research_run_id}",
        f"Target Repository: {repo}",
        f"Git SHA: {_git_sha(repo)}",
        f"Data Root: {Path(data_root)}",
        "",
        "## Research Brief",
        "",
        research_brief.strip(),
        "",
        "## Budget",
        "",
        f"Budget: {budget_name}",
    ]
    for key, value in budget.items():
        lines.append(f"{key}: {value}")
    lines.extend(["", "## Prior Run Synthesis", ""])
    lines.extend(_prior_run_synthesis(run_dir))
    return "\n".join(lines).rstrip() + "\n"


def _git_sha(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _prior_run_synthesis(run_dir: Path) -> list[str]:
    experiments_dir = run_dir / "experiments"
    if not experiments_dir.exists():
        return ["No prior experiments in this Research Run."]
    rows = []
    for experiment_dir in sorted(path for path in experiments_dir.iterdir() if path.is_dir()):
        summary_path = experiment_dir / "summary.json"
        if summary_path.exists():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            rows.append(
                f"- {experiment_dir.name}: {data.get('outcome', 'unknown')} - {data.get('summary', '')}"
            )
    return rows or ["No prior experiment summaries available."]
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_context.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/context.py tests/test_research_context.py
git commit -m "build research context packs"
```

### Task 12: Research Agents And Prompts

**Files:**
- Create: `agent_control_plane/research_experiment_controller/prompts/strategist-agent.md`
- Create: `agent_control_plane/research_experiment_controller/prompts/critic-agent.md`
- Create: `agent_control_plane/research_experiment_controller/prompts/implementer-agent.md`
- Create: `agent_control_plane/research_experiment_controller/prompts/evaluator-agent.md`
- Create: `agent_control_plane/research_experiment_controller/agents.py`
- Test: `tests/test_research_agents.py`

- [ ] **Step 1: Add role config tests**

Create `tests/test_research_agents.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_control_plane.research_experiment_controller.agents import (
    ResearchAgentRole,
    agent_config,
)
from agent_control_plane.control_plane.agent_runtime import RoleCapabilities


def test_research_agent_capabilities(tmp_path: Path) -> None:
    assert agent_config(ResearchAgentRole.STRATEGIST, tmp_path).capabilities is RoleCapabilities.READ_ONLY
    assert agent_config(ResearchAgentRole.CRITIC, tmp_path).capabilities is RoleCapabilities.READ_ONLY
    assert agent_config(ResearchAgentRole.IMPLEMENTER, tmp_path).capabilities is RoleCapabilities.WORKSPACE_WRITE
    assert agent_config(ResearchAgentRole.EVALUATOR, tmp_path).capabilities is RoleCapabilities.WORKSPACE_WRITE


def test_research_agent_names_are_workflow_scoped(tmp_path: Path) -> None:
    assert agent_config(ResearchAgentRole.STRATEGIST, tmp_path).role == "research-strategist"
    assert agent_config(ResearchAgentRole.CRITIC, tmp_path).role == "research-critic"
    assert agent_config(ResearchAgentRole.IMPLEMENTER, tmp_path).role == "research-implementer"
    assert agent_config(ResearchAgentRole.EVALUATOR, tmp_path).role == "research-evaluator"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_agents.py -q
```

Expected: FAIL with missing `agents.py`.

- [ ] **Step 3: Create prompts**

Create `agent_control_plane/research_experiment_controller/prompts/strategist-agent.md`:

```md
# Research Strategist Agent

You are the Research Strategist Agent for the Research Experiment Controller.
You are read-only. Artifacts are authoritative; thread memory is only continuity.
Own context summary, hypothesis framing, proposal, pre-registration, experiment design, design revision, plan selection, closeout, and plan update.
Do not revise success gates after seeing results.
Distinguish pre-registered evidence from exploratory diagnostics.
When human context is missing, proceed with explicit assumptions and record those assumptions in artifacts.
Return only JSON matching the requested artifact schema.
```

Create `agent_control_plane/research_experiment_controller/prompts/critic-agent.md`:

```md
# Research Critic Agent

You are the Research Critic Agent for the Research Experiment Controller.
You run in a fresh read-only thread for each critique pass.
Check leakage, point-in-time validity, baseline strength, statistical validity, multiple-testing risk, scope control, feasibility, success gates, implementation-plan alignment, and overclaiming.
Do not inherit Strategist, Implementer, or Evaluator assumptions.
Return only JSON matching the requested artifact schema.
```

Create `agent_control_plane/research_experiment_controller/prompts/implementer-agent.md`:

```md
# Research Implementer Agent

You are the Research Implementer Agent for one Research Experiment.
You may edit only the Experiment Worktree and only paths allowed by experiment_design.json.
Implement the selected plan exactly. Do not improve, reinterpret, weaken, or change research semantics.
You may repair mechanical implementation and verification failures.
Do not change labels, universe, splits, metrics, baselines, gates, feature lags, cost assumptions, or missing-data policy.
Do not commit.
Return only JSON matching the requested artifact schema.
```

Create `agent_control_plane/research_experiment_controller/prompts/evaluator-agent.md`:

```md
# Research Evaluator Agent

You are the Research Evaluator Agent for one Research Experiment.
Your cwd is the Evaluator Workspace. You may write scripts in eval_scratch and outputs in eval_outputs.
Read evaluation/manifest.json for paths to canonical artifacts, the Experiment Worktree, data root, locked confirmatory commands, and git SHA.
Do not edit the Experiment Worktree or locked artifacts.
The locked confirmatory plan determines the official outcome.
Exploratory diagnostics may motivate future experiments but must not upgrade the current outcome.
Return only JSON matching the requested artifact schema.
```

- [ ] **Step 4: Implement agent config helper**

Create `agent_control_plane/research_experiment_controller/agents.py`:

```python
from __future__ import annotations

from enum import Enum
from pathlib import Path

from agent_control_plane.control_plane.agent_runtime import AgentRunConfig, RoleCapabilities

PROMPT_DIRECTORY = Path(__file__).parent / "prompts"


class ResearchAgentRole(str, Enum):
    STRATEGIST = "strategist"
    CRITIC = "critic"
    IMPLEMENTER = "implementer"
    EVALUATOR = "evaluator"


def agent_config(
    role: ResearchAgentRole,
    cwd: str | Path,
    *,
    model: str | None = None,
    effort: str | None = None,
    output_schema: dict | None = None,
    thread_id: str | None = None,
    session_db_path: str | Path | None = None,
) -> AgentRunConfig:
    return AgentRunConfig(
        role=f"research-{role.value}",
        cwd=cwd,
        instructions=prompt_for_role(role),
        capabilities=_capabilities(role),
        model=model,
        effort=effort,
        output_schema=output_schema,
        thread_id=thread_id,
        session_db_path=session_db_path,
    )


def prompt_for_role(role: ResearchAgentRole) -> str:
    return (PROMPT_DIRECTORY / f"{role.value}-agent.md").read_text(encoding="utf-8")


def _capabilities(role: ResearchAgentRole) -> RoleCapabilities:
    if role in {ResearchAgentRole.IMPLEMENTER, ResearchAgentRole.EVALUATOR}:
        return RoleCapabilities.WORKSPACE_WRITE
    return RoleCapabilities.READ_ONLY
```

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_agents.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/agents.py agent_control_plane/research_experiment_controller/prompts tests/test_research_agents.py
git commit -m "add research agent roles"
```

### Task 13: Research Run Mirror Interface And MLflow Adapter

**Files:**
- Create: `agent_control_plane/research_experiment_controller/research_run_mirror.py`
- Create: `agent_control_plane/research_experiment_controller/mlflow_mirror.py`
- Test: `tests/test_research_mlflow_mirror.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_research_mlflow_mirror.py` with a small fake MLflow client. Assert:

- `mirror_to_mlflow(ResearchRunMirrorRequest(...), mlflow_client=fake)` logs only end-of-experiment params/tags.
- Numeric leaves are mirrored from `command_metrics.json`, `metrics.json`, and `confirmatory_evaluation_result.json`.
- All run-dir files are logged recursively, including nested evaluation outputs.
- The fake client is visible only to `mlflow_mirror.py` tests, not to controller or experiment-flow tests.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_mlflow_mirror.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement provider-neutral mirror interface**

Create `agent_control_plane/research_experiment_controller/research_run_mirror.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchRunMirrorRequest:
    run_dir: str | Path
    tracking_uri: str | None
    experiment_name: str | None
    research_run_id: str
    experiment_id: str
    outcome: str
    failed_stage: str | None
    failure_classification: str | None
    git_sha: str


ResearchRunMirror = Callable[[ResearchRunMirrorRequest], dict[str, Any]]
```

This is the only caller-facing Research Run Mirror interface. Do not expose MLflow clients, run handles, or SDK result types outside `mlflow_mirror.py`.

- [ ] **Step 4: Implement MLflow adapter**

Create `agent_control_plane/research_experiment_controller/mlflow_mirror.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from agent_control_plane.research_experiment_controller.research_run_mirror import ResearchRunMirrorRequest


class MLflowClient(Protocol):
    def set_tracking_uri(self, uri: str) -> None: ...
    def set_experiment(self, name: str) -> None: ...
    def start_run(self, run_name: str): ...
    def log_params(self, params: dict[str, object]) -> None: ...
    def set_tags(self, tags: dict[str, object]) -> None: ...
    def log_metric(self, key: str, value: float) -> None: ...
    def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None: ...


def mirror_to_mlflow(
    request: ResearchRunMirrorRequest,
    *,
    mlflow_client: MLflowClient | None = None,
) -> dict[str, str]:
    client = mlflow_client or _default_mlflow_client()
    root = Path(request.run_dir)
    if request.tracking_uri:
        client.set_tracking_uri(request.tracking_uri)
    if request.experiment_name:
        client.set_experiment(request.experiment_name)
    with client.start_run(run_name=request.experiment_id):
        client.log_params(
            {
                "research_run_id": request.research_run_id,
                "experiment_id": request.experiment_id,
            }
        )
        client.set_tags(
            {
                "outcome": request.outcome,
                "failed_stage": request.failed_stage or "",
                "failure_classification": request.failure_classification or "",
                "git_sha": request.git_sha,
            }
        )
        for name, path in (
            ("command_metrics", root / "command_metrics.json"),
            ("metrics", root / "metrics.json"),
            ("final_eval", root / "confirmatory_evaluation_result.json"),
        ):
            if path.exists():
                for key, value in _flatten_numeric(json.loads(path.read_text(encoding="utf-8")), prefix=name).items():
                    client.log_metric(key, value)
        for path in sorted(file for file in root.rglob("*") if file.is_file()):
            artifact_path = str(path.parent.relative_to(root)) if path.parent != root else None
            client.log_artifact(str(path), artifact_path=artifact_path)
    return {"status": "mirrored"}


def _default_mlflow_client() -> MLflowClient:
    import mlflow

    return mlflow


def _flatten_numeric(data: Any, *, prefix: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            child_prefix = f"{prefix}.{key}"
            metrics.update(_flatten_numeric(value, prefix=child_prefix))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        metrics[prefix] = float(data)
    return metrics
```

Rules:

- `mlflow_mirror.py` is the only module that imports MLflow or knows MLflow client APIs.
- `mlflow_client` is an adapter test seam only.
- Research code may construct `ResearchRunMirrorRequest` and call `mirror_research_run(...)` later. It must not import `mlflow_mirror.py`, call MLflow methods, pass MLflow modules around, or treat mirror success as controller correctness.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_mlflow_mirror.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/research_run_mirror.py agent_control_plane/research_experiment_controller/mlflow_mirror.py tests/test_research_mlflow_mirror.py
git commit -m "mirror research runs to mlflow"
```

### Task 14: Research Run Start And Snapshot

**Files:**
- Create: `agent_control_plane/research_experiment_controller/controller.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing start-run test**

Append to `tests/test_research_controller.py`:

```python
import json
from pathlib import Path

from agent_control_plane.research_experiment_controller.controller import start_research_run


def write_minimal_spec(tmp_path: Path, repo: Path) -> Path:
    spec = tmp_path / "research-run.yaml"
    spec.write_text(
        f"""
version: 1
research_run_id: run-1
target_repository: {repo}
max_experiments: 2
research_brief: |
  Research direction.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: /data
worktree:
  create: true
  root: .worktrees
mlflow:
  enabled: false
codex:
  model: gpt-5.3-codex
  effort: xhigh
implementation:
  max_repairs: 3
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    return spec


def test_start_research_run_snapshots_spec_and_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_spec(tmp_path, repo)

    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    assert run.research_run_id == "run-1"
    assert run.run_directory == (tmp_path / "runs" / "run-1").resolve()
    assert run.spec_snapshot_path.exists()
    assert run.state_path.exists()
    assert run.ledger_path.exists()
    state = json.loads(run.state_path.read_text(encoding="utf-8"))
    assert state["research_run_id"] == "run-1"
    assert state["current_phase"] == "ready_for_experiment"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_start_research_run_snapshots_spec_and_state -q
```

Expected: FAIL with missing `start_research_run`.

- [ ] **Step 3: Implement start_research_run**

Create `agent_control_plane/research_experiment_controller/controller.py` with:

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import write_json
from agent_control_plane.research_experiment_controller.ledger import append_event
from agent_control_plane.research_experiment_controller.research_run_spec import load_research_run_spec
from agent_control_plane.research_experiment_controller.state import (
    create_initial_state,
    research_run_directory,
)


@dataclass(frozen=True)
class ResearchRun:
    research_run_id: str
    run_directory: Path
    spec_snapshot_path: Path
    state_path: Path
    ledger_path: Path


class ResearchRunError(RuntimeError):
    """Raised when a Research Run cannot continue."""


def start_research_run(
    research_run_spec_path: str | Path,
    *,
    runtime_root: str | Path = "runs",
) -> ResearchRun:
    spec = load_research_run_spec(research_run_spec_path)
    run_directory = research_run_directory(runtime_root, spec.research_run_id)
    if run_directory.exists():
        raise ResearchRunError(f"Research Run already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    spec_snapshot_path = run_directory / "research_run_spec.yaml"
    shutil.copyfile(spec.source_path, spec_snapshot_path)
    state_path = run_directory / "state.json"
    ledger_path = run_directory / "ledger.jsonl"
    state = create_initial_state(
        research_run_id=spec.research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=spec_snapshot_path,
        max_experiments=spec.max_experiments,
    )
    write_json(state_path, state)
    append_event(ledger_path, {"event": "START", "research_run_id": spec.research_run_id})
    return ResearchRun(
        research_run_id=spec.research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=spec_snapshot_path,
        state_path=state_path,
        ledger_path=ledger_path,
    )
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_start_research_run_snapshots_spec_and_state -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/controller.py tests/test_research_controller.py
git commit -m "start research runs"
```

### Task 15: Outcome Classification

**Files:**
- Create: `agent_control_plane/research_experiment_controller/outcomes.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing classification tests**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.artifacts import ResearchOutcome
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_data_audit_failure,
    classify_eval_boundary_failure,
    should_stop_research_run,
)


def test_classify_data_audit_failure() -> None:
    outcome = classify_data_audit_failure("data_root_missing")

    assert outcome["outcome"] == ResearchOutcome.prerequisites_failed.value
    assert outcome["failed_stage"] == "data_audit"
    assert outcome["failure_classification"] == "data_root_missing"


def test_classify_eval_boundary_failure() -> None:
    outcome = classify_eval_boundary_failure("locked artifact changed")

    assert outcome["outcome"] == ResearchOutcome.run_failed.value
    assert outcome["failed_stage"] == "evaluation_boundary_audit"
    assert outcome["failure_classification"] == "boundary_violation"


def test_stop_on_prerequisites_failed_boolean() -> None:
    assert should_stop_research_run(
        outcome=ResearchOutcome.prerequisites_failed.value,
        stop_on_prerequisites_failed=True,
    )
    assert not should_stop_research_run(
        outcome=ResearchOutcome.completed_rejected.value,
        stop_on_prerequisites_failed=True,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_classify_data_audit_failure tests/test_research_controller.py::test_classify_eval_boundary_failure tests/test_research_controller.py::test_stop_on_prerequisites_failed_boolean -q
```

Expected: FAIL with missing `outcomes.py`.

- [ ] **Step 3: Implement outcomes**

Create `agent_control_plane/research_experiment_controller/outcomes.py`:

```python
from __future__ import annotations

from agent_control_plane.research_experiment_controller.artifacts import ResearchOutcome

DATA_AUDIT_FAILURE_CLASSIFICATIONS = frozenset(
    {
        "data_root_missing",
        "feature_family_missing",
        "schema_mismatch",
        "artifact_missing",
        "point_in_time_invalid",
        "prerequisite_command_failed",
    }
)


def classify_data_audit_failure(failure_classification: str) -> dict[str, str]:
    if failure_classification not in DATA_AUDIT_FAILURE_CLASSIFICATIONS:
        raise ValueError(f"Unknown data-audit failure classification: {failure_classification}")
    return {
        "outcome": ResearchOutcome.prerequisites_failed.value,
        "outcome_reason": f"Data/prerequisite audit failed: {failure_classification}.",
        "failed_stage": "data_audit",
        "failure_classification": failure_classification,
    }


def classify_eval_boundary_failure(reason: str) -> dict[str, str]:
    return {
        "outcome": ResearchOutcome.run_failed.value,
        "outcome_reason": reason,
        "failed_stage": "evaluation_boundary_audit",
        "failure_classification": "boundary_violation",
    }


def should_stop_research_run(*, outcome: str, stop_on_prerequisites_failed: bool) -> bool:
    return bool(stop_on_prerequisites_failed and outcome == ResearchOutcome.prerequisites_failed.value)
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_classify_data_audit_failure tests/test_research_controller.py::test_classify_eval_boundary_failure tests/test_research_controller.py::test_stop_on_prerequisites_failed_boolean -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/outcomes.py tests/test_research_controller.py
git commit -m "classify research outcomes"
```

### Task 16: Controller Phase Skeleton

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/controller.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing phase-order test**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.controller import (
    ResearchPhaseInput,
    run_research_loop,
)


def test_run_research_loop_repeats_until_max_experiments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    run = start_research_run(write_minimal_spec(tmp_path, repo), runtime_root=tmp_path / "runs")
    seen: list[str] = []

    def phase_runner(input: ResearchPhaseInput) -> dict[str, object]:
        seen.append(input.phase)
        return {"status": "experiment_completed", "outcome": "completed_rejected"}

    result = run_research_loop(
        run.research_run_id,
        runtime_root=tmp_path / "runs",
        phase_runner=phase_runner,
    )

    assert result["status"] == "completed"
    assert seen == ["ready_for_experiment", "ready_for_experiment"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_run_research_loop_repeats_until_max_experiments -q
```

Expected: FAIL with missing `run_research_loop`.

- [ ] **Step 3: Implement loop skeleton**

Extend `controller.py`:

```python
@dataclass(frozen=True)
class ResearchPhaseInput:
    research_run_id: str
    run_directory: str
    state_path: str
    phase: str
    runtime_root: str = "runs"


def load_research_run(
    research_run_id: str,
    *,
    runtime_root: str | Path = "runs",
) -> ResearchRun:
    run_directory = research_run_directory(runtime_root, research_run_id)
    return ResearchRun(
        research_run_id=research_run_id,
        run_directory=run_directory,
        spec_snapshot_path=run_directory / "research_run_spec.yaml",
        state_path=run_directory / "state.json",
        ledger_path=run_directory / "ledger.jsonl",
    )


def run_research_loop(
    research_run_id: str,
    *,
    runtime_root: str | Path = "runs",
    phase_runner=None,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    run = load_research_run(research_run_id, runtime_root=runtime_root)
    spec = load_research_run_spec(run.spec_snapshot_path)
    runner = phase_runner or (
        lambda phase_input: run_current_phase_once(
            phase_input,
            agent_runtime=agent_runtime,
        )
    )
    while True:
        state = _read_state(run.state_path)
        if state.get("status") == "completed":
            return {"status": "completed", "research_run_id": research_run_id}
        if state.get("status") == "failed":
            return {"status": "failed", "research_run_id": research_run_id}
        if len(state.get("experiments", [])) >= spec.max_experiments:
            state["status"] = "completed"
            state["current_phase"] = "completed"
            write_json(run.state_path, state)
            return {"status": "completed", "research_run_id": research_run_id}
        phase = str(state.get("current_phase"))
        result = runner(
            ResearchPhaseInput(
                research_run_id=research_run_id,
                run_directory=str(run.run_directory),
                state_path=str(run.state_path),
                phase=phase,
                runtime_root=str(runtime_root),
            )
        )
        if result.get("status") == "experiment_completed":
            _record_experiment_completion(run, state, result)
            if should_stop_research_run(
                outcome=str(result.get("outcome")),
                stop_on_prerequisites_failed=spec.stop_on_prerequisites_failed,
            ):
                state["status"] = "completed"
                state["current_phase"] = "completed"
                write_json(run.state_path, state)
                return {"status": "completed", "research_run_id": research_run_id}
            continue
        if result.get("status") in {"completed", "failed"}:
            return result


def run_current_phase_once(
    input: ResearchPhaseInput,
    *,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    raise ResearchRunError(f"Research phase is not implemented yet: {input.phase}")


def _read_state(path: str | Path) -> dict[str, Any]:
    from agent_control_plane.control_plane.json_artifacts import read_json_object

    return read_json_object(path)


def _record_experiment_completion(
    run: ResearchRun,
    state: dict[str, Any],
    result: dict[str, Any],
) -> None:
    experiment_id = str(result.get("experiment_id") or next_experiment_id(state))
    state.setdefault("experiments", []).append(
        {"experiment_id": experiment_id, "outcome": result.get("outcome")}
    )
    state["current_phase"] = "ready_for_experiment"
    write_json(run.state_path, state)
    append_event(
        run.ledger_path,
        {
            "event": "EXPERIMENT_COMPLETE",
            "experiment_id": experiment_id,
            "outcome": result.get("outcome"),
        },
    )
```

Add imports for `next_experiment_id` and `should_stop_research_run`. Keep state reading behind the JSON artifact helper.

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_run_research_loop_repeats_until_max_experiments -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/controller.py tests/test_research_controller.py
git commit -m "add research loop skeleton"
```

### Task 17: Data Audit And Prerequisites

**Files:**
- Create: `agent_control_plane/research_experiment_controller/prerequisites.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing data-audit test**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.prerequisites import (
    PrerequisiteAuditRequest,
    run_data_audit_phase,
)


def test_data_audit_missing_data_root_returns_prerequisites_failed(tmp_path: Path) -> None:
    result = run_data_audit_phase(
        PrerequisiteAuditRequest(
            data_root=tmp_path / "missing-data",
            prerequisite_commands=[],
            data_audit_commands=[],
            cwd=tmp_path,
            run_dir=tmp_path / "run",
            timeout_seconds=60,
        )
    )

    assert result["status"] == "experiment_completed"
    assert result["outcome"] == "prerequisites_failed"
    assert result["failed_stage"] == "data_audit"
    assert result["failure_classification"] == "data_root_missing"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_data_audit_missing_data_root_returns_prerequisites_failed -q
```

Expected: FAIL with missing `run_data_audit_phase`.

- [ ] **Step 3: Implement prerequisite/data-audit module**

Create `agent_control_plane/research_experiment_controller/prerequisites.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.command_runner import CommandSpec, run_command, write_command_metrics
from agent_control_plane.research_experiment_controller.outcomes import classify_data_audit_failure


@dataclass(frozen=True)
class PrerequisiteAuditRequest:
    data_root: str | Path
    prerequisite_commands: list[dict[str, Any]]
    data_audit_commands: list[dict[str, Any]]
    cwd: str | Path
    run_dir: str | Path
    timeout_seconds: float


def run_data_audit_phase(request: PrerequisiteAuditRequest) -> dict[str, Any]:
    data_root = Path(request.data_root)
    run_dir = Path(request.run_dir)
    if not data_root.exists():
        return {"status": "experiment_completed", **classify_data_audit_failure("data_root_missing")}
    command_results = []
    command_groups = (
        ("prerequisite", request.prerequisite_commands),
        ("data_audit", request.data_audit_commands),
    )
    for phase, commands in command_groups:
        for index, command in enumerate(commands, start=1):
            result = run_command(
                CommandSpec(
                    name=str(command.get("name", f"{phase}-{index}")),
                    argv=tuple(command["argv"]),
                    timeout_seconds=float(command.get("timeout_seconds", request.timeout_seconds)),
                ),
                cwd=request.cwd,
                stdout_path=run_dir / f"{phase}_{index}_stdout.log",
                stderr_path=run_dir / f"{phase}_{index}_stderr.log",
                env={
                    "RESEARCH_DATA_ROOT": str(data_root),
                    "RESEARCH_RUN_DIR": str(run_dir),
                    "RESEARCH_REPO_ROOT": str(Path(request.cwd)),
                },
            )
            command_results.append(result)
    write_command_metrics(run_dir / "command_metrics.json", command_results)
    if any(result.status != "passed" for result in command_results):
        return {"status": "experiment_completed", **classify_data_audit_failure("prerequisite_command_failed")}
    return {"status": "data_audit_passed", "command_results": [result.__dict__ for result in command_results]}
```

- [ ] **Step 4: Run test**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_data_audit_missing_data_root_returns_prerequisites_failed -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/prerequisites.py tests/test_research_controller.py
git commit -m "classify prerequisite failures"
```

### Task 18: Implementation Verification Repair Loop

**Files:**
- Create: `agent_control_plane/research_experiment_controller/verification.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing repair-loop test**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.verification import run_verification_commands


def test_verification_failure_routes_to_same_implementer_until_limit(tmp_path: Path) -> None:
    calls: list[str] = []

    def repair_once(log_path: Path) -> None:
        calls.append(str(log_path))

    result = run_verification_commands(
        verification_commands=[
            {"name": "fail", "argv": ["python", "-c", "import sys; sys.exit(1)"]}
        ],
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        timeout_seconds=60,
        max_repairs=1,
        repair_callback=repair_once,
    )

    assert result["status"] == "failed"
    assert result["outcome"] == "run_failed"
    assert result["failed_stage"] == "verification"
    assert calls
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_verification_failure_routes_to_same_implementer_until_limit -q
```

Expected: FAIL with missing `run_verification_commands`.

- [ ] **Step 3: Implement verification module**

Create `agent_control_plane/research_experiment_controller/verification.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.command_runner import CommandSpec, run_command, write_command_metrics


def run_verification_commands(
    *,
    verification_commands: list[dict[str, Any]],
    cwd: str | Path,
    run_dir: str | Path,
    timeout_seconds: float,
    max_repairs: int,
    repair_callback: Callable[[Path], None],
) -> dict[str, Any]:
    attempt = 0
    while True:
        results = []
        for index, command in enumerate(verification_commands, start=1):
            results.append(
                run_command(
                    CommandSpec(
                        name=str(command.get("name", f"verification-{index}")),
                        argv=tuple(command["argv"]),
                        timeout_seconds=float(command.get("timeout_seconds", timeout_seconds)),
                    ),
                    cwd=cwd,
                    stdout_path=Path(run_dir) / f"verification_{attempt}_{index}_stdout.log",
                    stderr_path=Path(run_dir) / f"verification_{attempt}_{index}_stderr.log",
                )
            )
        write_command_metrics(Path(run_dir) / "command_metrics.json", results)
        if all(result.status == "passed" for result in results):
            return {"status": "passed", "command_results": [result.__dict__ for result in results]}
        if attempt >= max_repairs:
            return {
                "status": "failed",
                "outcome": "run_failed",
                "failed_stage": "verification",
                "failure_classification": "verification_command_failed",
            }
        repair_callback(Path(run_dir) / f"verification_{attempt}_1_stderr.log")
        attempt += 1
```

The real controller callback must run the same Implementer thread with the failed command logs. Do not add evaluator-to-implementer repair.

- [ ] **Step 4: Run test**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_verification_failure_routes_to_same_implementer_until_limit -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/verification.py tests/test_research_controller.py
git commit -m "add implementation verification loop"
```

### Task 19: Provider-Neutral Durable Shell And Hatchet Adapter

**Files:**
- Create: `agent_control_plane/research_experiment_controller/durable_shell.py`
- Create: `agent_control_plane/research_experiment_controller/hatchet_workflow.py`
- Create: `agent_control_plane/research_experiment_controller/hatchet_worker.py`
- Test: `tests/test_research_hatchet_workflow.py`

- [ ] **Step 1: Write failing shell/adapter tests**

Create `tests/test_research_hatchet_workflow.py` with tiny fakes. Assert:

- `build_hatchet_workflows(fake_hatchet)` registers exactly one durable task named `research-run`.
- `run_research_shell(ResearchRunInput(...), controller_runner=fake)` delegates to the controller runner once.
- Metadata updates contain only generic fields: `research_run_id`, `controller_state_version`, `current_phase`, and `status`.
- No test outside this file imports Hatchet.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_hatchet_workflow.py -q
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement provider-neutral shell**

Create `agent_control_plane/research_experiment_controller/durable_shell.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ResearchRunInput:
    research_run_id: str
    runtime_root: str = "runs"


class MetadataSink(Protocol):
    def set_run_metadata(self, metadata: dict[str, object]) -> None: ...


ControllerRunner = Callable[[ResearchRunInput], dict[str, Any]]


def run_research_shell(
    input: ResearchRunInput,
    *,
    metadata_sink: MetadataSink | None = None,
    controller_runner: ControllerRunner | None = None,
) -> dict[str, Any]:
    _set_generic_metadata(
        metadata_sink,
        {
            "research_run_id": input.research_run_id,
            "controller_state_version": 1,
            "current_phase": "controller_loop",
            "status": "running",
        },
    )
    runner = controller_runner or _run_controller_loop
    result = runner(input)
    _set_generic_metadata(
        metadata_sink,
        {
            "research_run_id": input.research_run_id,
            "controller_state_version": 1,
            "current_phase": "completed",
            "status": str(result.get("status")),
        },
    )
    return result


def _set_generic_metadata(sink: MetadataSink | None, metadata: dict[str, object]) -> None:
    setter = getattr(sink, "set_run_metadata", None)
    if callable(setter):
        setter(metadata)


def _run_controller_loop(input: ResearchRunInput) -> dict[str, Any]:
    from agent_control_plane.research_experiment_controller.controller import run_research_loop

    return run_research_loop(input.research_run_id, runtime_root=input.runtime_root)
```

- [ ] **Step 4: Implement Hatchet adapter and worker**

Create `agent_control_plane/research_experiment_controller/hatchet_workflow.py`:

```python
from __future__ import annotations

from datetime import timedelta
from typing import Any

from hatchet_sdk import DurableContext, Hatchet
from pydantic import BaseModel

from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
    run_research_shell,
)


class HatchetResearchRunInput(BaseModel):
    research_run_id: str
    runtime_root: str = "runs"


def build_hatchet_workflows(hatchet: Hatchet) -> list[Any]:
    @hatchet.durable_task(
        name="research-run",
        input_validator=HatchetResearchRunInput,
        execution_timeout=timedelta(days=30),
    )
    async def research_run(input: HatchetResearchRunInput, ctx: DurableContext) -> dict[str, Any]:
        return run_research_shell(
            ResearchRunInput(
                research_run_id=input.research_run_id,
                runtime_root=input.runtime_root,
            ),
            metadata_sink=ctx,
        )

    return [research_run]
```

Create `agent_control_plane/research_experiment_controller/hatchet_worker.py`:

```python
from __future__ import annotations

from hatchet_sdk import Hatchet

from agent_control_plane.research_experiment_controller.hatchet_workflow import build_hatchet_workflows


def main() -> None:
    hatchet = Hatchet()
    build_hatchet_workflows(hatchet)
    worker = hatchet.worker("research-experiment-controller")
    worker.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Keep the boundary narrow**

Rules:

- `controller.py`, `cli.py`, and tests outside `test_research_hatchet_workflow.py` import from `durable_shell.py`, not Hatchet.
- `durable_shell.py` imports no Hatchet SDK symbols.
- `durable_shell.py` does not import Hatchet adapter modules. Its only default dependency on controller code is the local `_run_controller_loop` function.
- `HatchetResearchRunInput` is adapter-private. The public durable interface is only `ResearchRunInput` plus `run_research_shell(...)`.
- Only `hatchet_workflow.py` and `hatchet_worker.py` import `hatchet_sdk`.
- Hatchet decorators contain generic durable metadata only. No materiality, outcome classification, or research artifact semantics in decorators.
- Future executor replacement must be local to the shell contract, adapter module, worker startup, and `pixi` worker wiring.

- [ ] **Step 6: Run tests**

Run:

```bash
pixi run pytest tests/test_research_hatchet_workflow.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/durable_shell.py agent_control_plane/research_experiment_controller/hatchet_workflow.py agent_control_plane/research_experiment_controller/hatchet_worker.py tests/test_research_hatchet_workflow.py
git commit -m "add research hatchet shell"
```

### Task 20: Research CLI

**Files:**
- Create: `agent_control_plane/research_experiment_controller/cli.py`
- Create: `agent_control_plane/research_experiment_controller/__main__.py`
- Modify: `pixi.toml`
- Test: `tests/test_research_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_research_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_control_plane.research_experiment_controller.cli import main


def test_cli_run_starts_research_run(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = tmp_path / "research-run.yaml"
    spec.write_text(
        f"""
version: 1
research_run_id: cli-run
target_repository: {repo}
max_experiments: 1
research_brief: |
  CLI test.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: /data
worktree:
  create: true
  root: .worktrees
mlflow:
  enabled: false
implementation:
  max_repairs: 1
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )

    code = main(["run", str(spec), "--runtime-root", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert code == 0
    assert "Started Research Run: cli-run" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_cli.py -q
```

Expected: FAIL with missing CLI.

- [ ] **Step 3: Implement CLI**

Create `agent_control_plane/research_experiment_controller/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agent_control_plane.research_experiment_controller.controller import (
    ResearchRunError,
    start_research_run,
)
from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
    run_research_shell,
)
from agent_control_plane.research_experiment_controller.research_run_spec import ResearchRunSpecError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-experiment-controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Start a Research Run from a Research Run Spec.")
    run_parser.add_argument("research_run_spec_path")
    run_parser.add_argument("--runtime-root", default="runs")
    resume_parser = subparsers.add_parser("resume", help="Resume a Research Run.")
    resume_parser.add_argument("research_run_id")
    resume_parser.add_argument("--runtime-root", default="runs")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run = start_research_run(args.research_run_spec_path, runtime_root=args.runtime_root)
            print(f"Started Research Run: {run.research_run_id}")
            print(f"Run directory: {run.run_directory}")
            print(f"State: {run.state_path}")
            return 0
        if args.command == "resume":
            result = run_research_shell(
                ResearchRunInput(
                    research_run_id=args.research_run_id,
                    runtime_root=args.runtime_root,
                )
            )
            print(f"Resumed Research Run: {args.research_run_id}")
            print(f"Status: {result.get('status')}")
            return 0
    except (OSError, ResearchRunError, ResearchRunSpecError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2
```

Create `agent_control_plane/research_experiment_controller/__main__.py`:

```python
from __future__ import annotations

from agent_control_plane.research_experiment_controller.cli import main

raise SystemExit(main())
```

Add to `[feature.dev.tasks]` in `pixi.toml`:

```toml
research-experiment-worker = "python -m agent_control_plane.research_experiment_controller.hatchet_worker"
```

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/cli.py agent_control_plane/research_experiment_controller/__main__.py pixi.toml tests/test_research_cli.py
git commit -m "add research cli"
```

### Task 21: End-To-End Fake Runtime

**Files:**
- Create: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Modify: `agent_control_plane/research_experiment_controller/controller.py`
- Test: `tests/test_research_e2e.py`

- [ ] **Step 1: Write end-to-end test**

Create `tests/test_research_e2e.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agent_control_plane.research_experiment_controller.controller import (
    start_research_run,
    run_research_loop,
)


def test_research_run_stops_after_prerequisites_failed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = tmp_path / "research-run.yaml"
    spec.write_text(
        f"""
version: 1
research_run_id: e2e-run
target_repository: {repo}
max_experiments: 5
research_brief: |
  E2E prerequisite failure.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {tmp_path / "missing-data"}
worktree:
  create: true
  root: .worktrees
mlflow:
  enabled: false
implementation:
  max_repairs: 1
stop_on_prerequisites_failed: true
""",
        encoding="utf-8",
    )
    run = start_research_run(spec, runtime_root=tmp_path / "runs")

    result = run_research_loop(run.research_run_id, runtime_root=tmp_path / "runs")

    assert result["status"] == "completed"
    state = json.loads(run.state_path.read_text(encoding="utf-8"))
    assert state["experiments"][0]["outcome"] == "prerequisites_failed"
    assert len(state["experiments"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_e2e.py -q
```

Expected: FAIL until `run_current_phase_once` delegates to the first `experiment_flow.py` path.

- [ ] **Step 3: Implement minimal first phase path**

Create `experiment_flow.py` and keep the controller thin:

```python
@dataclass(frozen=True)
class ExperimentFlowRequest:
    research_run_id: str
    experiment_id: str
    run_directory: Path
    experiment_directory: Path
    ledger_path: Path
    spec: ResearchRunSpec
    state: dict[str, Any]


def run_experiment_flow(
    request: ExperimentFlowRequest,
    *,
    agent_runtime: Any | None = None,
) -> dict[str, Any]:
    ...
```

For this first slice, `run_experiment_flow` builds `context_pack.md`, runs the data-root audit through `prerequisites.py`, writes `data_audit.json` and `summary.json`, and returns the `prerequisites_failed` result.

In `controller.py`, `run_current_phase_once` only loads state/spec, allocates `experiment_id`, creates the experiment directory, and calls `run_experiment_flow(ExperimentFlowRequest(...))`. Include `ledger_path` in the request so experiment-level helpers can append audit events without importing controller internals. Do not put command execution or context-building internals in `controller.py`.

- [ ] **Step 4: Run end-to-end test**

Run:

```bash
pixi run pytest tests/test_research_e2e.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all research tests**

Run:

```bash
pixi run pytest tests/test_research_*.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/experiment_flow.py agent_control_plane/research_experiment_controller/controller.py tests/test_research_e2e.py
git commit -m "add research e2e prerequisite path"
```

### Task 22: Full Agent Phase Implementation

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Modify: `agent_control_plane/research_experiment_controller/agents.py`
- Test: `tests/test_research_controller.py`
- Test: `tests/test_research_e2e.py`

- [ ] **Step 1: Add fake agent runtime contract test**

Append a fake-runtime test to `tests/test_research_controller.py`.

Use a tiny `FakeResearchRuntime.open_thread(config)` that returns queued JSON responses by `config.role`. The test should run one complete experiment with:

- Strategist outputs for `context_summary.json`, `proposal.json`, `research_spec.json`, `experiment_design.json`, `selected_plan.json`, `summary.json`, and `plan_update.json`.
- Fresh Critic outputs for `critique.json` and `empirical_critique.json`.
- Implementer output for `implementation.json`.
- Evaluator outputs for `confirmatory_evaluation_result.json`, `exploratory_diagnostics_result.json`, and `analysis_ledger.json`.

Assert the loop completes, writes every core artifact, uses the expected role names, and does not require real agents, MLflow, Hatchet, or external data.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_full_phase_writes_core_artifacts_with_fake_agents -q
```

Expected: FAIL until controller invokes role chain and writes artifacts.

- [ ] **Step 3: Implement experiment flow role chain**

In `experiment_flow.py`, implement the full single-experiment path inside `run_experiment_flow`. Keep this file as the phase coordinator: put command execution in `prerequisites.py`/`verification.py`, worktree setup in `worktree.py`, implementation path checks in `implementation_boundary.py`, evaluator setup/audits in `evaluation.py`, and mirror wrapping in `research_run_mirror.py`.

Required sequence:

1. Build `context_pack.md`.
2. Run persistent Strategist thread for:
   - `context_summary.json`
   - `proposal.json`
   - `research_spec.json`
   - `experiment_design.json`
   - `selected_plan.json`
3. Run fresh Critic thread for `critique.json`.
4. If `selected_plan.selected is False`, write `summary.json` with `outcome=no_op`.
5. Run prerequisite and data-audit commands through `prerequisites.run_data_audit_phase(PrerequisiteAuditRequest(...))`.
6. Prepare Experiment Worktree when `worktree.create` is true.
7. Run Implementer thread and write `implementation.json`.
8. Audit Implementer changed files through `implementation_boundary.audit_implementation_paths`.
9. Run verification commands and implementation repair loop through `verification.run_verification_commands`.
10. Write `implementation_diff_summary.json`.
11. Create Evaluator Workspace and manifest.
12. Run Evaluator thread and write:
    - `confirmatory_evaluation_result.json`
    - `exploratory_diagnostics_result.json`
    - `analysis_ledger.json`
13. Run Evaluation Boundary Audit.
14. Run fresh Critic thread for `empirical_critique.json`.
15. Run Strategist closeout and write:
    - `summary.json`
    - `plan_update.json`
16. Return `{"status": "experiment_completed", "experiment_id": experiment_id, "outcome": summary["outcome"]}`.

Use small same-file helpers only for artifact/agent plumbing:

```python
def _run_json_agent(thread, turn_input: str, config, model_cls):
    result = thread.run(turn_input, config)
    return model_cls.model_validate_json(result.final_response)


def _write_artifact(path: Path, model) -> None:
    write_json(path, model.model_dump(mode="json"))
```

Do not add evaluator-to-implementer repair. If evaluation produces a runtime/source defect, classify as `run_failed` and preserve artifacts. Keep `controller.py` as the run loop only; do not move MLflow, Hatchet, prerequisite command execution, verification repair, evaluator boundary logic, or implementation boundary audit logic back into it. Task 25 wires the Research Run Mirror hook after ledger-failure behavior exists.

- [ ] **Step 4: Run the fake-agent test**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_full_phase_writes_core_artifacts_with_fake_agents -q
```

Expected: PASS.

- [ ] **Step 5: Run research controller tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py tests/test_research_e2e.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/experiment_flow.py agent_control_plane/research_experiment_controller/agents.py tests/test_research_controller.py tests/test_research_e2e.py
git commit -m "run research experiment phases"
```

### Task 23: Material Revision Policy

**Files:**
- Create: `agent_control_plane/research_experiment_controller/materiality.py`
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing materiality tests**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.materiality import (
    DEFAULT_MATERIAL_FIELDS,
    requires_fresh_critic,
)


def test_material_policy_trusts_agent_material_declaration() -> None:
    assert requires_fresh_critic(
        strategist_declared_categories=["success gate"],
        changed_categories=[],
        material_fields=DEFAULT_MATERIAL_FIELDS,
    )


def test_material_policy_does_not_trust_agent_non_material_silence() -> None:
    assert requires_fresh_critic(
        strategist_declared_categories=[],
        changed_categories=["primary metric"],
        material_fields=DEFAULT_MATERIAL_FIELDS,
    )


def test_material_policy_ignores_minor_command_formatting() -> None:
    assert not requires_fresh_critic(
        strategist_declared_categories=[],
        changed_categories=["command formatting"],
        material_fields=DEFAULT_MATERIAL_FIELDS,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_material_policy_trusts_agent_material_declaration tests/test_research_controller.py::test_material_policy_does_not_trust_agent_non_material_silence tests/test_research_controller.py::test_material_policy_ignores_minor_command_formatting -q
```

Expected: FAIL with missing `materiality.py`.

- [ ] **Step 3: Implement materiality helper**

Create `agent_control_plane/research_experiment_controller/materiality.py`:

```python
from __future__ import annotations

DEFAULT_MATERIAL_FIELDS = frozenset(
    {
        "target",
        "label",
        "universe",
        "data source",
        "feature family",
        "split",
        "primary metric",
        "success gate",
        "baseline set",
        "transaction-cost model",
        "holding period",
        "rebalance frequency",
        "neutralization policy",
    }
)


def requires_fresh_critic(
    *,
    strategist_declared_categories: list[str],
    changed_categories: list[str],
    material_fields: frozenset[str] = DEFAULT_MATERIAL_FIELDS,
) -> bool:
    declared = {_normalize(category) for category in strategist_declared_categories}
    changed = {_normalize(category) for category in changed_categories}
    material = {_normalize(field) for field in material_fields}
    return bool(declared & material or changed & material)


def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", " ")
```

- [ ] **Step 4: Wire into experiment flow**

In `experiment_flow.py`, after design critique and any Strategist revision, call `requires_fresh_critic`. If true, start a fresh Critic thread and write `critique_revision.json`. Use flow-detected changed categories from artifact comparison and agent-declared categories from `SelectedPlan.material_revision_categories` or `Critique.material_revision_categories`.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/materiality.py agent_control_plane/research_experiment_controller/experiment_flow.py tests/test_research_controller.py
git commit -m "add material revision policy"
```

### Task 24: Implementation Boundary Audit

**Files:**
- Create: `agent_control_plane/research_experiment_controller/implementation_boundary.py`
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing allowed-path audit test**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.implementation_boundary import audit_implementation_paths


def test_implementation_path_audit_rejects_changed_file_outside_allowed_paths() -> None:
    result = audit_implementation_paths(
        changed_files=["pipeline/prod.py"],
        allowed_write_paths=["research/experiments"],
    )

    assert result["outcome"] == "run_failed"
    assert result["failed_stage"] == "implementation_boundary_audit"
    assert result["failure_classification"] == "allowed_path_violation"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_implementation_path_audit_rejects_changed_file_outside_allowed_paths -q
```

Expected: FAIL with missing helper.

- [ ] **Step 3: Implement implementation boundary module**

Create `agent_control_plane/research_experiment_controller/implementation_boundary.py`:

```python
from __future__ import annotations

from typing import Any

from agent_control_plane.control_plane.boundary_audit import assert_allowed_paths


def audit_implementation_paths(
    *,
    changed_files: list[str],
    allowed_write_paths: list[str],
) -> dict[str, Any]:
    try:
        assert_allowed_paths(changed_files, allowed_write_paths)
    except ValueError as exc:
        return {
            "outcome": "run_failed",
            "outcome_reason": str(exc),
            "failed_stage": "implementation_boundary_audit",
            "failure_classification": "allowed_path_violation",
        }
    return {"status": "passed"}
```

`experiment_flow.py` calls this helper after Implementer returns and before verification. If it fails, write `implementation_diff_summary.json`, preserve the worktree, return an experiment completion with `run_failed`.

- [ ] **Step 4: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_implementation_path_audit_rejects_changed_file_outside_allowed_paths -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/implementation_boundary.py agent_control_plane/research_experiment_controller/experiment_flow.py tests/test_research_controller.py
git commit -m "audit implementation boundaries"
```

### Task 25: Research Run Mirror Wiring

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/research_run_mirror.py`
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Test: `tests/test_research_mlflow_mirror.py`

- [ ] **Step 1: Add failing Research Run Mirror failure test**

Append to `tests/test_research_mlflow_mirror.py`:

```python
from agent_control_plane.research_experiment_controller.ledger import read_events
from agent_control_plane.research_experiment_controller.research_run_mirror import (
    ResearchRunMirrorRequest,
    mirror_research_run,
)


class FailingMirror:
    def __call__(self, request: ResearchRunMirrorRequest) -> dict[str, object]:
        raise RuntimeError("mlflow down")


def test_mlflow_failure_appends_ledger_event_and_continues(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    result = mirror_research_run(
        ResearchRunMirrorRequest(
            run_dir=tmp_path,
            tracking_uri="file:/tmp/mlruns",
            experiment_name="exp",
            research_run_id="run-1",
            experiment_id="EXP-0001",
            outcome="completed_rejected",
            failed_stage=None,
            failure_classification=None,
            git_sha="abc",
        ),
        ledger_path=ledger_path,
        mirror=FailingMirror(),
    )

    assert result["status"] == "mlflow_mirror_failed"
    assert read_events(ledger_path)[0]["event"] == "MLFLOW_MIRROR_FAILED"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_mlflow_mirror.py::test_mlflow_failure_appends_ledger_event_and_continues -q
```

Expected: FAIL with missing helper.

- [ ] **Step 3: Implement Research Run Mirror wrapper**

Add to `research_run_mirror.py`:

```python
from typing import Any

from agent_control_plane.research_experiment_controller.ledger import append_event


def mirror_research_run(
    request: ResearchRunMirrorRequest,
    *,
    ledger_path: str | Path,
    mirror: ResearchRunMirror | None = None,
) -> dict[str, Any]:
    mirror_fn = mirror or _default_research_run_mirror
    try:
        return mirror_fn(request)
    except Exception as exc:
        append_event(
            ledger_path,
            {
                "event": "MLFLOW_MIRROR_FAILED",
                "experiment_id": request.experiment_id,
                "message": str(exc),
            },
        )
        return {"status": "mlflow_mirror_failed", "message": str(exc)}


def _default_research_run_mirror(request: ResearchRunMirrorRequest) -> dict[str, Any]:
    from agent_control_plane.research_experiment_controller.mlflow_mirror import mirror_to_mlflow

    return mirror_to_mlflow(request)
```

- [ ] **Step 4: Wire Research Run Mirror request**

In `experiment_flow.py`, after end-of-experiment artifacts are written:

```python
if spec.mlflow.enabled:
    mirror_research_run(
        ResearchRunMirrorRequest(
            run_dir=experiment_dir,
            tracking_uri=spec.mlflow.tracking_uri,
            experiment_name=spec.mlflow.experiment_name,
            research_run_id=spec.research_run_id,
            experiment_id=experiment_id,
            outcome=str(summary.outcome),
            failed_stage=confirmatory.failed_stage,
            failure_classification=confirmatory.failure_classification,
            git_sha=git_sha,
        ),
        ledger_path=request.ledger_path,
    )
```

The flow may construct the request, but it must not import `mlflow_mirror.py`, import MLflow, call MLflow client methods, or inspect mirror internals. Do not call the mirror phase-by-phase. `controller.py` must not know whether MLflow exists.

- [ ] **Step 5: Run test**

Run:

```bash
pixi run pytest tests/test_research_mlflow_mirror.py::test_mlflow_failure_appends_ledger_event_and_continues -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/research_run_mirror.py agent_control_plane/research_experiment_controller/experiment_flow.py tests/test_research_mlflow_mirror.py
git commit -m "wire research run mirror"
```

### Task 26: Resolved Research Run Spec Snapshot

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/research_run_spec.py`
- Modify: `agent_control_plane/research_experiment_controller/controller.py`
- Test: `tests/test_research_run_spec.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing resolved snapshot test**

Append to `tests/test_research_run_spec.py`:

```python
from agent_control_plane.research_experiment_controller.research_run_spec import resolved_spec_dict


def test_resolved_spec_dict_includes_defaults(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = load_research_run_spec(write_spec(tmp_path, repo))

    resolved = resolved_spec_dict(spec)

    assert resolved["version"] == 1
    assert resolved["research_run_id"] == "peer-residual-v1"
    assert resolved["target_repository"] == str(repo.resolve())
    assert resolved["budget"] == "smoke"
    assert resolved["budgets"]["smoke"]["max_runtime_minutes"] == 5
    assert resolved["worktree"] == {"create": True, "root": ".worktrees"}
    assert resolved["mlflow"]["enabled"] is True
    assert resolved["implementation"] == {"max_repairs": 3}
    assert resolved["stop_on_prerequisites_failed"] is True
```

Append to `tests/test_research_controller.py`:

```python
def test_start_research_run_writes_resolved_spec_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = write_minimal_spec(tmp_path, repo)

    run = start_research_run(spec_path, runtime_root=tmp_path / "runs")

    snapshot_text = run.spec_snapshot_path.read_text(encoding="utf-8")
    assert "research_run_id: run-1" in snapshot_text
    assert "max_repairs: 3" in snapshot_text
    assert "stop_on_prerequisites_failed: true" in snapshot_text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_run_spec.py::test_resolved_spec_dict_includes_defaults tests/test_research_controller.py::test_start_research_run_writes_resolved_spec_snapshot -q
```

Expected: FAIL because `resolved_spec_dict` does not exist and `start_research_run` copies the raw source file.

- [ ] **Step 3: Implement resolved spec serialization**

Add to `agent_control_plane/research_experiment_controller/research_run_spec.py`:

```python
def resolved_spec_dict(spec: ResearchRunSpec) -> dict[str, Any]:
    return {
        "version": spec.version,
        "research_run_id": spec.research_run_id,
        "target_repository": str(spec.target_repository),
        "max_experiments": spec.max_experiments,
        "research_brief": spec.research_brief,
        "budget": spec.budget,
        "budgets": {
            name: {
                "month_start": budget.month_start,
                "month_end": budget.month_end,
                "max_runtime_minutes": budget.max_runtime_minutes,
            }
            for name, budget in spec.budgets.items()
        },
        "data_root": str(spec.data_root),
        "worktree": {
            "create": spec.worktree.create,
            "root": str(spec.worktree.root),
        },
        "mlflow": {
            "enabled": spec.mlflow.enabled,
            "tracking_uri": spec.mlflow.tracking_uri,
            "experiment_name": spec.mlflow.experiment_name,
        },
        "codex": {
            "model": spec.codex.model,
            "effort": spec.codex.effort,
        },
        "implementation": {
            "max_repairs": spec.implementation.max_repairs,
        },
        "stop_on_prerequisites_failed": spec.stop_on_prerequisites_failed,
    }
```

- [ ] **Step 4: Write resolved YAML snapshot in controller**

In `agent_control_plane/research_experiment_controller/controller.py`, replace the `shutil.copyfile` snapshot line in `start_research_run` with:

```python
import yaml
from agent_control_plane.research_experiment_controller.research_run_spec import resolved_spec_dict


spec_snapshot_path.write_text(
    yaml.safe_dump(resolved_spec_dict(spec), sort_keys=False),
    encoding="utf-8",
)
```

Remove the now-unused `shutil` import if no longer needed.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_run_spec.py tests/test_research_controller.py::test_start_research_run_writes_resolved_spec_snapshot -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/research_run_spec.py agent_control_plane/research_experiment_controller/controller.py tests/test_research_run_spec.py tests/test_research_controller.py
git commit -m "snapshot resolved research specs"
```

### Task 27: No-Op And Blocked Classification

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/outcomes.py`
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing classification tests**

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.outcomes import (
    classify_blocked,
    classify_no_op,
    classify_selected_without_commands,
)


def test_classify_no_op_means_no_admissible_experiment() -> None:
    outcome = classify_no_op("Critic rejected every admissible candidate.")

    assert outcome["outcome"] == "no_op"
    assert outcome["failed_stage"] is None
    assert outcome["failure_classification"] is None
    assert "Critic rejected" in outcome["outcome_reason"]


def test_classify_blocked_records_external_condition() -> None:
    outcome = classify_blocked("credential_missing", "Data vendor credential unavailable.")

    assert outcome["outcome"] == "blocked"
    assert outcome["failed_stage"] == "controller"
    assert outcome["failure_classification"] == "credential_missing"


def test_selected_without_commands_is_not_healthy_no_op() -> None:
    outcome = classify_selected_without_commands()

    assert outcome["outcome"] == "blocked"
    assert outcome["failed_stage"] == "selection"
    assert outcome["failure_classification"] == "no_deterministic_commands"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_controller.py::test_classify_no_op_means_no_admissible_experiment tests/test_research_controller.py::test_classify_blocked_records_external_condition tests/test_research_controller.py::test_selected_without_commands_is_not_healthy_no_op -q
```

Expected: FAIL with missing functions.

- [ ] **Step 3: Implement classification helpers**

Add to `agent_control_plane/research_experiment_controller/outcomes.py`:

```python
def classify_no_op(reason: str) -> dict[str, str | None]:
    return {
        "outcome": ResearchOutcome.no_op.value,
        "outcome_reason": reason,
        "failed_stage": None,
        "failure_classification": None,
    }


def classify_blocked(
    failure_classification: str,
    reason: str,
    *,
    failed_stage: str = "controller",
) -> dict[str, str]:
    return {
        "outcome": ResearchOutcome.blocked.value,
        "outcome_reason": reason,
        "failed_stage": failed_stage,
        "failure_classification": failure_classification,
    }


def classify_selected_without_commands() -> dict[str, str]:
    return classify_blocked(
        "no_deterministic_commands",
        "A plan was selected but did not declare deterministic commands.",
        failed_stage="selection",
    )
```

- [ ] **Step 4: Wire selected-without-commands path**

In `run_experiment_flow`, after `selected_plan.json` is written and before data audit, add:

```python
if selected_plan.selected and not experiment_design.verification_commands and not experiment_design.confirmatory_commands:
    outcome = classify_selected_without_commands()
    write_json(experiment_dir / "summary.json", outcome)
    return {"status": "experiment_completed", "experiment_id": experiment_id, **outcome}
```

Implementation-only experiments are allowed when verification commands exist. A selected plan with neither verification nor confirmatory commands is `blocked`, not `no_op`.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_controller.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/outcomes.py agent_control_plane/research_experiment_controller/experiment_flow.py tests/test_research_controller.py
git commit -m "classify no op blocked outcomes"
```

### Task 28: Feature Spec Artifacts For Material Signals

**Files:**
- Modify: `agent_control_plane/research_experiment_controller/artifacts.py`
- Modify: `agent_control_plane/research_experiment_controller/experiment_flow.py`
- Test: `tests/test_research_artifacts.py`
- Test: `tests/test_research_controller.py`

- [ ] **Step 1: Add failing FeatureSpec tests**

Append to `tests/test_research_artifacts.py`:

```python
from agent_control_plane.research_experiment_controller.artifacts import FeatureSpec


def test_feature_spec_records_point_in_time_validity() -> None:
    feature = FeatureSpec(
        feature_id="peer_residual_lookback_30d",
        inputs=["returns", "peer_groups"],
        transformation_logic="Rolling residual against peer basket.",
        lookback_window="30d",
        lag="1 bar",
        normalization="zscore by timestamp",
        missing_data_policy="drop if peer group has fewer than 5 assets",
        backfill_range="2020-01:2026-01",
        availability_at_decision_time_proof="Uses only timestamps <= decision timestamp.",
        expected_failure_modes=["thin peer group", "missing returns"],
    )

    assert feature.feature_id == "peer_residual_lookback_30d"
    assert "decision timestamp" in feature.availability_at_decision_time_proof
```

Append to `tests/test_research_controller.py`:

```python
from agent_control_plane.research_experiment_controller.experiment_flow import feature_spec_path


def test_feature_spec_path_is_material_feature_scoped(tmp_path: Path) -> None:
    assert feature_spec_path(tmp_path, "peer_residual").name == "feature_spec_peer_residual.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pixi run pytest tests/test_research_artifacts.py::test_feature_spec_records_point_in_time_validity tests/test_research_controller.py::test_feature_spec_path_is_material_feature_scoped -q
```

Expected: FAIL with missing `FeatureSpec` and `feature_spec_path`.

- [ ] **Step 3: Add FeatureSpec model**

Add to `agent_control_plane/research_experiment_controller/artifacts.py`:

```python
class FeatureSpec(BaseModel):
    feature_id: str
    inputs: list[str]
    transformation_logic: str
    lookback_window: str
    lag: str
    normalization: str
    missing_data_policy: str
    backfill_range: str
    availability_at_decision_time_proof: str
    expected_failure_modes: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add feature spec path helper**

Add to `agent_control_plane/research_experiment_controller/experiment_flow.py`:

```python
def feature_spec_path(experiment_dir: str | Path, feature_id: str) -> Path:
    safe_feature_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in feature_id
    ).strip("_")
    if not safe_feature_id:
        raise ResearchRunError("Feature spec id must contain at least one safe character.")
    return Path(experiment_dir) / f"feature_spec_{safe_feature_id}.json"
```

When Strategist or Implementer declares generated material features, write one `feature_spec_<feature_id>.json` per feature using `FeatureSpec`. If no material features are declared, write none.

- [ ] **Step 5: Run tests**

Run:

```bash
pixi run pytest tests/test_research_artifacts.py tests/test_research_controller.py::test_feature_spec_path_is_material_feature_scoped -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add agent_control_plane/research_experiment_controller/artifacts.py agent_control_plane/research_experiment_controller/experiment_flow.py tests/test_research_artifacts.py tests/test_research_controller.py
git commit -m "support feature spec artifacts"
```

### Task 29: Task Control Plane Uses Shared Command Runner

**Files:**
- Modify: `agent_control_plane/task_control_plane/controller.py`
- Test: `tests/test_task_control_plane.py`
- Test: `tests/test_control_plane_command_runner.py`

- [ ] **Step 1: Add regression test for Task combined command log**

Append to `tests/test_task_control_plane.py`:

```python
def test_task_tests_still_write_combined_command_log_after_shared_runner(tmp_path: Path) -> None:
    target_repository, task_run = create_single_task_run_with_passing_command(tmp_path)

    result = run_active_task_tests(task_run.task_state_path)

    state = json.loads(task_run.task_state_path.read_text(encoding="utf-8"))
    command_log_path = Path(state["tasks"][0]["artifacts"]["command_log"])
    text = command_log_path.read_text(encoding="utf-8")
    assert result["passed"] is True
    assert "test command START: unit" in text or "command START: unit" in text
    assert "created by tests" not in text
    assert (target_repository / "test-created.txt").exists()
```

- [ ] **Step 2: Run test before refactor**

Run:

```bash
pixi run pytest tests/test_task_control_plane.py::test_task_tests_still_write_combined_command_log_after_shared_runner -q
```

Expected: PASS before refactor. This proves current behavior is captured.

- [ ] **Step 3: Refactor Task test command execution**

In `agent_control_plane/task_control_plane/controller.py`, replace internal subprocess streaming in `_run_test_command` with shared `run_command_combined_log` while preserving Task result shape.

Use this adapter:

```python
from agent_control_plane.control_plane.command_runner import CommandSpec, run_command_combined_log


def _run_test_command(
    *,
    command: TestCommand,
    target_repository: Path,
    command_log: TextIO,
    log_lock: threading.Lock,
) -> dict[str, Any]:
    result = run_command_combined_log(
        CommandSpec(name=command.name, argv=tuple(command.argv)),
        cwd=target_repository,
        log_path=Path(command_log.name),
    )
    return {
        "name": result.name,
        "argv": result.argv,
        "started_at": _utc_timestamp(),
        "ended_at": _utc_timestamp(),
        "exit_code": result.exit_code,
        "status": "passed" if result.status == "passed" else "failed",
        "duration_seconds": result.duration_seconds,
    }
```

Keep Task behavior: one combined `command.log`, all declared commands run, no shell strings.

- [ ] **Step 4: Run Task command tests**

Run:

```bash
pixi run pytest tests/test_task_control_plane.py tests/test_control_plane_command_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane/task_control_plane/controller.py agent_control_plane/control_plane/command_runner.py tests/test_task_control_plane.py tests/test_control_plane_command_runner.py
git commit -m "reuse command runner in task tests"
```

### Task 30: Boundary Alignment Check

**Files:**
- No planned file changes
- Fix only the violating module if a boundary check fails
- Test: no runtime tests

- [ ] **Step 1: Verify replaceable integration boundaries**

Run:

```bash
rg -n "hatchet_sdk|import mlflow|from mlflow" agent_control_plane/research_experiment_controller
```

Expected:

```text
agent_control_plane/research_experiment_controller/hatchet_workflow.py:...
agent_control_plane/research_experiment_controller/hatchet_worker.py:...
agent_control_plane/research_experiment_controller/mlflow_mirror.py:...
```

No other Research modules should import Hatchet or MLflow.

Run:

```bash
rg -n "from .*mlflow_mirror|import .*mlflow_mirror" agent_control_plane/research_experiment_controller
```

Expected: only `research_run_mirror.py` imports the MLflow adapter.

- [ ] **Step 2: Verify controller and experiment flow stay coordinators**

Run:

```bash
rg -n "run_command\\(|subprocess|[Hh]atchet|assert_allowed_paths|from .*mlflow_mirror|import mlflow" agent_control_plane/research_experiment_controller/controller.py agent_control_plane/research_experiment_controller/experiment_flow.py
```

Expected: no matches. Command execution belongs in `prerequisites.py` and `verification.py`; allowed-path internals belong in `implementation_boundary.py`; MLflow SDK calls and adapter imports belong outside controller/flow; Hatchet belongs in `hatchet_workflow.py` and `hatchet_worker.py`.

- [ ] **Step 3: Verify PRD out-of-scope exclusions**

Run:

```bash
rg -n "eval_inputs|phase-by-phase MLflow|MLflow tracing|event wait|auto.*promotion|git commit" agent_control_plane/research_experiment_controller tests/test_research_*.py
```

Expected: no implementation of excluded behavior. Test names or prompt text may mention exclusions only to forbid them.

- [ ] **Step 4: Commit if fixes were needed**

Run only when Step 1-3 found violations and code was changed:

```bash
git add agent_control_plane/research_experiment_controller tests
git commit -m "tighten research boundaries"
```

### Task 31: Full Test Pass And Docs Check

**Files:**
- Modify: `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`
- Do not modify `.scratch/research-experiment-plane/PRD.md`; treat it as source of truth
- No code files unless tests require a direct fix

- [ ] **Step 1: Run all tests**

Run:

```bash
pixi run pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run formatting**

Run:

```bash
pixi run ruff format .
pixi run ruff check . --fix
```

Expected: PASS or files reformatted with no remaining lint errors.

- [ ] **Step 3: Run tests after formatting**

Run:

```bash
pixi run pytest -q
```

Expected: PASS.

- [ ] **Step 4: Update issue status**

Modify `.scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md`:

```md
Status: implemented
Label: ready-for-review
```

Append this under `## Comments`:

```md
Implemented Research Experiment Plane v1.

Verification:
- `pixi run pytest -q`
- `pixi run ruff format .`
- `pixi run ruff check . --fix`
- `pixi run pytest -q`
```

- [ ] **Step 5: Commit**

Run:

```bash
git add agent_control_plane tests pixi.toml .scratch/research-experiment-plane/issues/01-implement-research-experiment-plane.md
git commit -m "implement research experiment plane"
```

## Self-Review

### Spec Coverage

- Single Research Run Spec with embedded Research Brief: Tasks 5, 14, 20, 26.
- Bounded multiple experiments per Research Run: Tasks 7, 16, 21.
- One selected plan per Research Experiment: Tasks 6, 22.
- Single Research Outcome enum and reason fields: Tasks 6, 15, 27.
- `prerequisites_failed` and `stop_on_prerequisites_failed`: Tasks 15, 17, 21.
- Research Budgets: Tasks 5, 11, 17.
- Resolved spec snapshot on start/resume: Task 26.
- Minimal Hatchet Durable Execution Shell: Task 19.
- Generic Hatchet metadata only: Task 19.
- Shared primitives: Tasks 1, 2, 3, 4, 8, 29.
- Task Control Plane reuse of shared command runner: Task 29.
- Pydantic at artifact boundaries: Task 6.
- Controller state and ledger as plain JSON/JSONL: Task 7.
- Per-experiment flow separated from run loop: Tasks 21, 22, 25.
- Agent thread lifetimes and role permissions: Task 12, Task 22.
- Material Revision Policy controller-owned: Task 23.
- Feature specs for material generated signals: Task 28.
- Experiment Worktree preserve/dirty-reuse fail: Task 9.
- Implementation allowed-path audit: Task 24.
- Implementation verification repair loop: Task 18.
- No evaluator-to-implementer repair loop: Task 22 explicitly excludes it.
- Evaluator Workspace without `eval_inputs`: Task 10.
- Evaluation Boundary Audit checks worktree and locked artifact hashes: Task 10.
- Research Run Mirror interface plus MLflow adapter, recursive artifacts, selected metrics only: Task 13, Task 25.
- Replaceable integration boundary checks: Task 30.
- No Hatchet human event wait: Task 19 has no event wait; Task 12 prompts agents to proceed with assumptions.
- No final commit or automatic promotion in workflow code: Task 22 returns terminal outcomes and writes artifacts only.

### Placeholder Scan

Placeholder marker phrases were scanned and removed. Each task names exact files, commands, expected test state, and concrete code or required behavior.

### Type Consistency

Use these names consistently:

- `ResearchRunSpec`
- `ResearchBudget`
- `ResearchRun`
- `ResearchPhaseInput`
- `ResearchRunInput`
- `ResearchOutcome`
- `CommandSpec`
- `CommandResult`
- `EvaluatorWorkspace`
- `ResearchAgentRole`
- `RoleCapabilities`
- `ResearchRunMirrorRequest`
- `ResearchRunMirror`
- `ExperimentFlowRequest`
- `run_experiment_flow`
- `start_research_run`
- `run_research_loop`
- `run_research_shell`
- `run_current_phase_once`
- `run_data_audit_phase`
- `PrerequisiteAuditRequest`
- `run_verification_commands`
- `audit_implementation_paths`
- `prepare_experiment_worktree`
- `create_evaluator_workspace`
- `run_evaluation_boundary_audit`
- `mirror_to_mlflow`
- `mirror_research_run`
- `resolved_spec_dict`
- `classify_no_op`
- `classify_blocked`
- `classify_selected_without_commands`
- `FeatureSpec`
- `feature_spec_path`
- `run_command_combined_log`
