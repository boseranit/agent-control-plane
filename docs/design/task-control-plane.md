# Task Control Plane Design Spec

Status: draft-ready for implementation planning
Last updated: 2026-06-01
Primary glossary: [CONTEXT.md](../../CONTEXT.md)
SDK reference: [OpenAI Codex Python SDK API Reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md)
Usage: [Task Control Plane Usage](../usage/task-control-plane.md)

## 1. Purpose

The Task Control Plane is the first Control-Plane Workflow in this Agent Control Plane repo. It coordinates Codex agents through a deterministic software-task loop while keeping the outer workflow in ordinary Python code.

The workflow is intentionally not a free-form autonomous agent. The Controller decides which agent runs next, which artifacts exist, when human approval is required, when tests run, when reviewer feedback returns to the implementer, and when a Task may be committed.

The canonical work unit is a Task. One Task proceeds through planning, optional question answering, optional human plan approval, implementation, deterministic tests, fresh review, iterative repair, and exactly one final commit.

## 2. Scope

### In Scope

- A synchronous CLI-driven Task Control Plane workflow.
- Explicit Task Spec input.
- Local markdown Issue Directory input normalized into a snapshotted Task Spec.
- A deterministic Controller state machine.
- One Target Repository per Task Run.
- Sequential Task execution in Task Spec order.
- Persistent Planner Agent, Context Agent, and Implementer Agent threads per Task.
- Fresh Reviewer Agent thread per review attempt.
- SDK `output_schema` usage for structured agent outputs.
- Optional human plan approval through `$EDITOR`.
- Batched human answers for unresolved planning questions.
- Controller-run test commands after every implementer turn.
- Streaming command output into one command log per Task.
- Reviewer approval loop.
- Commit-all task completion.
- Durable Controller-owned Task State and resumable Task Runs.
- Usage-limit sleep until the suggested retry time.
- Local artifacts only for v1 runtime behavior.

### Out Of Scope For v1

- Migrating or fixing the Hyperliquid research orchestrator.
- Extracting shared framework code before a second workflow exists.
- MLflow integration in Task Control Plane runtime behavior.
- Worktree creation.
- Automatic branch creation.
- Automatic revert or cleanup of failed Task changes.
- Task dependency graphs.
- Environment variable injection for tests.
- Target branch validation.
- Service tier configuration.
- Per-role model or effort configuration.
- Final post-review test rerun.
- Post-review drift checks.
- A separate command-runner agent.
- Agent-based Task Spec generation from rough notes.

## 3. Existing Repository State

The repo contains the Task Control Plane implementation under:

```text
agent_control_plane/task_control_plane/
```

It includes Task Spec and Task Source loading, run creation/resume, Planner/Context/Implementer/Reviewer prompt/schema files, deterministic test execution, review repair, commit advance, and Hatchet entrypoints. Runtime state is JSON, and artifact names use the existing hyphenated filenames listed in this document.

## 4. Core Terms

Use the glossary in `CONTEXT.md` as canonical. The most important terms for implementation are:

- Task Control Plane: this workflow.
- Task Spec: human-managed YAML input.
- Task Run: one execution of a Task Spec.
- Task State: Controller-owned runtime state.
- Controller: deterministic coordinator.
- Target Repository: the repo being modified and committed.
- Planner Agent: produces a plan or structured questions.
- Context Agent: answers Planner Agent questions during planning.
- Approved Plan: authoritative implementation plan.
- Implementer Agent: modifies the Target Repository.
- Reviewer Agent: approves or rejects the current implementation.
- Review Approval: decision that the Task is ready to commit.

Avoid using "orchestrator" as a code/domain term for this workflow. The Controller is deterministic code; the agents are role-specific Codex threads.

## 5. High-Level Flow

The target loop is:

```text
with Codex() as codex:
    task_source = load_task_source(task_source_path)
    task_spec = task_source.task_spec
    run = create_or_resume_run(task_spec)

    for task in remaining_tasks(run):
        require_clean_target_repository_unless_resuming_active_task(run, task)

        task_state = create_or_resume_task_state(run, task)
        context_path = write_task_context_once(run, task)

        planner_thread = create_or_resume_planner_thread(...)
        context_thread = create_or_resume_context_thread(...)

        planner_output = run_planner(...)
        append_planner_output(planning_artifact, planner_output)

        while planner_output.status == "needs_answers":
            context_answers = run_context_agent(...)
            record_answers(planning_artifact, context_answers)

            unresolved = unresolved_questions(context_answers)
            if unresolved:
                human_answers = ask_human_for_answers(unresolved)
                record_answers(planning_artifact, human_answers)

            planner_output = run_planner_followup(...)
            append_planner_output(planning_artifact, planner_output)

        write_approved_plan_candidate(planner_output.plan_markdown)
        if task_spec.require_plan_approval:
            open_editor(approved_plan_path)
            require_human_approval(approved_plan_path)
        mark_plan_approved(planning_artifact, approved_plan_path)

        implementer_thread = create_or_resume_implementer_thread(...)
        implementer_result = run_implementer(...)
        write_json(implementation_result_path, implementer_result)

        approved = False
        while not approved:
            fail_if_max_iterations_reached()
            increment_iteration()

            test_result = run_test_commands_streaming_to_command_log(...)
            record_test_status(task_state, test_result)

            if not test_result.passed:
                implementer_result = run_implementer_with_failed_tests(...)
                write_json(implementation_result_path, implementer_result)
                continue

            reviewer_thread = create_fresh_reviewer_thread(...)
            review = run_reviewer(...)
            append_review_output(review_log, review)

            if review.status == "approved":
                approved = True
                break

            implementer_result = run_implementer_with_reviewer_json_verbatim(...)
            write_json(implementation_result_path, implementer_result)

        commit_sha = commit_all_target_repository_changes(...)
        mark_task_completed(task_state, commit_sha)
```

## 6. Task Sources

The Controller runtime still uses a snapshotted Task Spec as the canonical input for resume. The `run` command can now accept either:

- a Task Spec YAML file;
- an Issue Directory containing local markdown issue files.

An Issue Directory import is deterministic. `README.md`, when present, is PRD/run context. Each non-README `*.md` file becomes one Task in lexical order. The file stem becomes the Task ID, the first `#` heading becomes the title, and the full markdown file becomes the prompt.

If an Issue Directory is inside the Target Repository and is untracked, those source files are ignored for clean checks and excluded from Task commits. Tracked or staged changes to the source files still make the Target Repository dirty before a Task starts.

Example:

```text
task-control run .planning/issues/cross-sectional-samples-collapse
task-control run /tmp/issue-breakdown --repo /path/to/target/repo
```

## 7. Task Spec

### Authoring Location

Task Specs are authored by convention at:

```text
task_specs/<target-branch-name>/task-spec.yaml
```

The branch name is the Target Repository branch name, sanitized for filesystem use by the future authoring helper. The Controller does not infer this path and does not validate the path against the current target branch in v1.

The CLI must receive an explicit Task Source path. YAML Task Spec paths are still accepted:

```text
task-control run task_specs/<branch>/task-spec.yaml
```

### Required Fields

```yaml
target_repository: /absolute/or/relative/path/to/target/repo
tasks:
  - id: task-001
    title: Add batch runtime
    prompt: |
      Implement the batch runtime entrypoint.
```

`target_repository` is required. It resolves to the single Target Repository for the entire Task Run.

Each Task requires:

- `id`: stable explicit Task ID.
- `title`: short human title, used in commit messages.
- `prompt`: the actual task request.

### Optional Fields

```yaml
description: |
  Implement the first pass of runtime batch support across these tasks.

context: |
  Shared background that every role may use.

require_plan_approval: true
max_iterations: 10

codex:
  model: gpt-5.5
  effort: high

test_commands:
  - name: unit
    argv: ["pixi", "run", "test"]

tasks:
  - id: task-001
    title: Add batch runtime
    prompt: |
      Implement the batch runtime entrypoint.
    context: |
      Extra details specific to this Task.
```

Defaults:

- `require_plan_approval`: `true`.
- `max_iterations`: `10`.
- `codex.model`: omitted means SDK/app default.
- `codex.effort`: omitted means SDK/app default.
- `test_commands`: may be empty, but if empty the reviewer gate loses a deterministic test signal. Prefer requiring at least one command after the first implementation milestone unless a concrete no-test use case appears.

### Explicitly Unsupported v1 Fields

Reject these if present:

- `env`, `environment`, `env_vars`, `environment_variables`.
- `target_branch`, `branch`, `base_branch`.
- `service_tier`.
- `dependencies`, `dependency_graph`, `depends_on`.
- shell-string test commands.

The rejection should explain that the field is not supported in v1 rather than silently ignoring it.

### Test Commands

Test commands are named argv objects:

```yaml
test_commands:
  - name: unit
    argv: ["pixi", "run", "test"]
  - name: lint
    argv: ["pixi", "run", "ruff", "check", "."]
```

Rules:

- Run in declaration order.
- Run with `cwd` set to the Target Repository.
- Do not run through a shell.
- Do not inject Task Spec environment variables in v1.
- Stream stdout and stderr into the single Task command log.
- A non-zero exit from any command makes the test result failed.
- Always run every declared test command. Do not stop at the first failure.
- The Implementer Agent receives the aggregate command result after all commands finish.

## 8. Runtime Layout

Task Runs live under the top-level runtime root:

```text
runs/
  RUN-2026-05-27-104500/
    task-spec.yaml
    task-state.json
    tasks/
      task-001/
        context.json
        planning.json
        approved-plan.md
        implementation-result.json
        review.log
        command.log
```

`runs/` is gitignored.

### Run ID

Generate by local timestamp with optional CLI override:

```text
RUN-YYYY-MM-DD-HHMMSS
```

If an override is provided, fail if the run directory already exists.

### Task Spec Snapshot

On `run`, copy the explicit input file to:

```text
runs/<run-id>/task-spec.yaml
```

Resume uses only this snapshot and `task-state.json`. It does not re-read or trust the original Task Spec path.

## 9. Task State

`task-state.json` is Controller-owned and authoritative. Humans do not edit it.

Current shape:

```json
{
  "run_id": "run-20260531T104500Z-abc12345",
  "phase": "ready_for_planning",
  "active_task_id": "task-001",
  "active_task": {"id": "task-001", "title": "Add batch runtime"},
  "target_repository": "/home/boser/project",
  "run_directory": "/abs/runs/run-...",
  "task_spec_snapshot_path": "/abs/runs/run-.../task-spec.yaml",
  "task_state_path": "/abs/runs/run-.../task-state.json",
  "task_source_untracked_root": ".planning/issues/cross-sectional-samples-collapse",
  "tasks": [
    {
      "id": "task-001",
      "title": "Add batch runtime",
      "status": "active",
      "phase": "ready_for_planning",
      "iterations": 0,
      "artifacts": {
        "task_context": "/abs/runs/.../tasks/task-001/context.json",
        "planning": "/abs/runs/.../tasks/task-001/planning.json",
        "approved_plan": "/abs/runs/.../tasks/task-001/approved-plan.md",
        "implementation_result": "/abs/runs/.../tasks/task-001/implementation-result.json",
        "review_log": "/abs/runs/.../tasks/task-001/review.log",
        "command_log": "/abs/runs/.../tasks/task-001/command.log"
      }
    }
  ]
}
```

The top-level `phase` is the run status.

### Task Status Values

- `pending`
- `active`
- `completed`
- `failed`

### Task Phase Values

Use phases as implementation state-machine labels, not as user-facing domain language:

- `pending`
- `ready_for_planning`
- `planning_needs_answers`
- `plan_ready`
- `plan_pending_approval`
- `plan_approved`
- `plan_approval_declined`
- `failed_test_repair_pending`
- `review_rejection_repair_pending`
- `ready_for_tests`
- `tests_failed`
- `tests_passed`
- `review_rejected`
- `commit_ready`
- `target_repository_dirty_before_next_task`
- `completed`
- `failed`

The exact names can change during implementation, but they must support deterministic resume without inferring progress from artifacts.

## 10. Task Artifacts

### `context.json`

Generated once before planning. Keep it stable and small.

It should include:

- Task ID, title, prompt, and optional Task context.
- Run description and run context, if present.
- Target Repository absolute path.
- Task Run path.
- Absolute paths to the Task artifacts.

It should not automatically embed:

- Target repo `AGENTS.md`.
- Target repo `CONTEXT.md`.
- Target repo ADRs.
- Arbitrary markdown files.
- Git diff.
- Previous task histories.
- Command log content.

Agents run with `cwd` set to the Target Repository and may inspect relevant files directly.

### `planning.json`

Planning metadata and history. It is not the authoritative Approved Plan content.

Recommended shape:

```json
{
  "planner_outputs": [],
  "answer_batches": [],
  "approved_plan": {
    "path": "/abs/.../approved-plan.md",
    "approval": {
      "status": "approved",
      "mode": "human",
      "approved_plan_path": "/abs/.../approved-plan.md",
      "approved_at": "2026-05-27T10:50:00+10:00"
    }
  }
}
```

`planner_outputs` appends each Planner Agent structured output.

`answer_batches` appends each planning question-answer cycle:

```json
{
  "questions": [
    {
      "id": "Q1",
      "context": "Need to know the expected test location.",
      "question": "Where should tests for this feature live?",
      "type": "repo_context"
    }
  ],
  "context_answers": [
    {
      "question_id": "Q1",
      "status": "answered",
      "answer": "Put tests under tests/task_control_plane/...",
      "reason": "Existing tests for this package live there."
    }
  ],
  "human_answers": []
}
```

### `approved-plan.md`

The authoritative Approved Plan.

If plan approval is enabled:

1. Controller writes the Planner Agent `plan_markdown`.
2. Controller opens `$EDITOR`.
3. Human edits or leaves unchanged.
4. Controller asks for explicit approval.
5. This file becomes the Approved Plan.

If plan approval is disabled:

1. Controller writes the Planner Agent `plan_markdown`.
2. This file becomes the Approved Plan automatically.

The Implementer Agent receives this path, not raw planner output.

### `implementation-result.json`

Latest Implementer Agent result only. Overwrite after each implementer turn.

Suggested output shape:

```json
{
  "status": "implementation_complete",
  "summary": "Implemented the requested change.",
  "changed_files": ["path/to/file.py"],
  "recommended_commands": []
}
```

Allowed status values:

- `implementation_complete`: Controller proceeds to test commands.

### `review.log`

Append-only review history. One JSON object per Reviewer Agent attempt.

Example:

```json
{"attempt":1,"status":"rejected","blocking_issues":["..."],"requested_changes":["..."],"non_blocking_issues":[]}
{"attempt":2,"status":"approved","blocking_issues":[],"requested_changes":[],"non_blocking_issues":["..."]}
```

### `command.log`

One append-only command log per Task. Stream command output while commands run.

Recommended format:

```text
=== iteration 2 command 1: unit ===
$ pixi run test
started_at: 2026-05-27T10:53:00+10:00
cwd: /home/boser/project

[stdout]
...

[stderr]
...

exit_code: 0
completed_at: 2026-05-27T10:54:00+10:00
duration_seconds: 60.123
status: passed
```

The Controller tells the Reviewer Agent where this log is; it does not embed log contents in the review prompt by default.

## 11. Codex SDK Integration

Use the synchronous SDK.

Relevant SDK surface:

- `Codex(...)`
- `Codex.thread_start(...)`
- `Codex.thread_resume(thread_id, ...)`
- `Thread.id`
- `Thread.run(input, output_schema=..., effort=..., cwd=..., approval_mode=..., sandbox_policy=...)`

One long-lived `Codex` client should be used per `run` or `resume` process:

```python
with Codex() as codex:
    controller.run_or_resume(codex)
```

### Thread Creation And Resume

Create or resume threads through a small adapter:

```python
def create_or_resume_thread(
    codex: Codex,
    thread_id: str | None,
    *,
    role: Role,
    cwd: Path,
    developer_instructions: str,
    approval_mode: ApprovalMode,
    sandbox: SandboxMode,
    model: str | None,
) -> Thread:
    ...
```

If `thread_id` exists, call `thread_resume`. Otherwise call `thread_start`. Persist new thread IDs immediately after thread creation.

Role prompts are loaded from Markdown files and passed as `developer_instructions` when starting or resuming a thread. Do not paste prompts into every turn input.

### Role Defaults

| Role | Thread lifetime | Approval mode | Sandbox |
| --- | --- | --- | --- |
| Planner Agent | Persistent per Task | `auto_review` | read-only |
| Context Agent | Persistent per Task | `auto_review` | read-only |
| Implementer Agent | Persistent per Task | `auto_review` | workspace-write |
| Reviewer Agent | Fresh per review attempt | `deny_all` | read-only |

### Output Schemas

Each role output should use SDK `output_schema`. Schemas live with the workflow package:

```text
agent_control_plane/task_control_plane/schemas/
  planner_output.schema.json
  context_answers.schema.json
  implementer_result.schema.json
  reviewer_output.schema.json
```

The existing skeleton names can be migrated:

- `planner-output.schema.json` -> `planner_output.schema.json`
- `context-answers-output.schema.json` -> `context_answers.schema.json`

Do not paste schemas into prompts. Prompts should describe the expected shape and behavior, while the SDK receives the actual schema object.

### Minimal Post-Run Checks

The Controller should parse `final_response` and perform only routing checks:

- Planner status is `planned` or `needs_answers`.
- Planned output has non-empty `plan_markdown`.
- Needs-answers output has non-empty questions with stable IDs.
- Context output has one answer or unresolved marker per planner question.
- Reviewer status is `approved` or `rejected`.
- Implementer status is known.

Do not implement a separate strict validation layer beyond what the Controller needs to route safely.

## 12. Role Prompt Requirements

Prompt files:

```text
agent_control_plane/task_control_plane/prompts/
  planner-agent.md
  context-agent.md
  implementer-agent.md
  reviewer-agent.md
```

### Planner Agent Prompt

Must say:

- You are the Planner Agent for Task Control Plane.
- Plan exactly the active Task.
- Inspect the Target Repository directly when useful.
- Do not modify files.
- Questions are encouraged when uncertainty affects the implementation plan.
- Do not ask low-value questions.
- Return `planned` with `plan_markdown` when ready.
- Return `needs_answers` with structured questions when blocked by uncertainty.
- Do not implement.

### Context Agent Prompt

Must say:

- You are the Context Agent for Task Control Plane.
- Answer Planner Agent questions only.
- Inspect the Target Repository directly when useful.
- Do not modify files.
- Return one answer object for every Planner Agent question.
- Use `answered` when repo/context answers it.
- Use `unresolved` when human input is needed.
- Include a concise `reason`.
- Do not ask the human directly.
- Do not implement.

### Implementer Agent Prompt

Must say:

- You are the Implementer Agent for Task Control Plane.
- Implement exactly the Approved Plan for the active Task.
- The Approved Plan is authoritative.
- Do not choose between planner drafts and the Approved Plan.
- You may inspect the Target Repository directly.
- You may edit the Target Repository.
- Keep changes scoped to the Task.
- Do not commit.
- After failed tests, inspect the command log path and fix the implementation.
- After reviewer rejection, address the reviewer JSON verbatim.
- Return a structured implementation result.

### Reviewer Agent Prompt

Must say:

- You are the Reviewer Agent for Task Control Plane.
- You run fresh for each review attempt.
- You may inspect the Target Repository directly.
- You should inspect git status/diff/commits as needed.
- You should read the Approved Plan and command log from their paths as needed.
- You must evaluate the complete current Target Repository changes.
- If `status` is `approved`, the Controller will commit all current Target Repository changes for this Task.
- Put only commit-blocking issues in `blocking_issues` or `requested_changes`.
- Put advisory observations in `non_blocking_issues`.
- `non_blocking_issues` do not prevent commit when `status` is `approved`.
- Do not modify files.

## 13. Planner And Context Loop

### Initial Planner Input

The turn input should be lean:

```text
Plan the active Task.

Task ID: task-001
Task title: Add batch runtime
Task prompt: ...
Task context: ...

Task context artifact: /abs/.../context.json
Plan artifact: /abs/.../planning.json
Approved Plan artifact: /abs/.../approved-plan.md
```

### Planner Output: Planned

```json
{
  "status": "planned",
  "questions": [],
  "plan_markdown": "..."
}
```

### Planner Output: Needs Answers

```json
{
  "status": "needs_answers",
  "questions": [
    {
      "id": "Q1",
      "context": "Need to preserve API compatibility.",
      "question": "Should compute_batch preserve the current artifact API?",
      "type": "design_decision"
    },
    {
      "id": "Q2",
      "context": "Need to know local test placement.",
      "question": "Where should tests for feature runtime live?",
      "type": "repo_context"
    }
  ]
}
```

### Context Agent Output

```json
{
  "answers": [
    {
      "question_id": "Q1",
      "status": "unresolved",
      "reason": "This is a product/design decision, not discoverable from the Target Repository."
    },
    {
      "question_id": "Q2",
      "status": "answered",
      "answer": "Tests should live under tests/runtime/ because existing runtime tests are there.",
      "reason": "The Target Repository contains existing runtime tests in that directory."
    }
  ]
}
```

### Human Answers

Unresolved questions are batched for the human. The Controller records answers in `planning.json` and passes the latest answer batch back to the Planner Agent.

Human answers should use the same question IDs:

```json
[
  {
    "question_id": "Q1",
    "answer": "Yes, preserve the current artifact API."
  }
]
```

## 14. Plan Approval

The Controller writes the Planner Agent `plan_markdown` to `approved-plan.md`.

If `require_plan_approval: false`:

- Mark approval mode `automatic`.
- Continue to implementation.

If `require_plan_approval: true`:

- Mark Task phase `plan_pending_approval`.
- Open `$EDITOR` for `approved-plan.md`.
- After editor exits, ask for explicit approval.
- If approved, mark approval mode `human`.
- If not approved, do not continue. The first version can abort with a resumable state rather than adding a plan-revision UI.

Editor behavior:

- Use `$EDITOR` if set.
- Fall back to a clear error telling the user to set `$EDITOR`.
- Do not force the human to edit JSON.

## 15. Implementation And Test Loop

### Initial Implementer Input

```text
Implement the active Task using the Approved Plan.

Task ID: task-001
Task title: Add batch runtime
Task prompt: ...

Task context artifact: /abs/.../context.json
Approved Plan: /abs/.../approved-plan.md
Implementation result artifact: /abs/.../implementation-result.json
Command log: /abs/.../command.log
```

### After Every Implementer Turn

The Controller:

1. Writes the latest `implementation-result.json`.
2. Increments the Task iteration counter before the gate cycle.
3. Runs all `test_commands`.
4. Streams output into `command.log`.
5. Records pass/fail status in `task-state.json`.

If tests fail:

- Do not run Reviewer Agent.
- Send the command log path and Approved Plan path to the same Implementer Agent.
- Continue the loop.

Failed-tests input:

```text
The deterministic test commands failed.

Approved Plan: /abs/.../approved-plan.md
Command log: /abs/.../command.log

Inspect the command log, fix the implementation, and return a new implementation result.
```

### Iteration Counting

One `max_iterations` counter covers both:

- failed-test repair cycles.
- reviewer-rejection repair cycles.

Default is `10`.

If the limit is reached:

- Mark Task failed.
- Mark Task Run failed.
- Stop.
- Leave Target Repository dirty for inspection.
- Do not revert.
- Do not skip to the next Task.

## 16. Review Loop

Reviewer Agent starts only after the latest Controller-run tests pass.

### Reviewer Input

```text
Review the active Task.

Task ID: task-001
Task title: Add batch runtime
Task prompt: ...

Task context artifact: /abs/.../context.json
Approved Plan: /abs/.../approved-plan.md
Command log: /abs/.../command.log
Review log: /abs/.../review.log

Inspect the Target Repository directly as needed. Approval means the Controller will commit all current Target Repository changes for this Task.
```

The Controller does not embed a diff packet. Reviewer should run git inspection commands itself.

### Reviewer Output

```json
{
  "status": "approved",
  "blocking_issues": [],
  "requested_changes": [],
  "non_blocking_issues": []
}
```

or:

```json
{
  "status": "rejected",
  "blocking_issues": [
    "The implementation does not update the documented CLI path."
  ],
  "requested_changes": [
    "Update the CLI help text and add a test for the new command."
  ],
  "non_blocking_issues": [
    "Consider simplifying the helper name later."
  ]
}
```

On rejection:

- Append full review JSON to `review.log`.
- Send full review JSON verbatim to the Implementer Agent.
- Do not summarize or reinterpret the review.

Rejection input:

```text
The Reviewer Agent rejected the Task. Address the reviewer feedback exactly.

Reviewer output:
<verbatim reviewer JSON>
```

On approval:

- Append full review JSON to `review.log`.
- Commit all current Target Repository changes.

## 17. Commit Boundary

The Controller commits only when:

- Latest Controller-run test commands passed.
- Latest Reviewer Agent output has `status: approved`.

It does not run a redundant final test after review.

It does not perform a post-review drift check in v1.

Commit behavior:

```text
git add --all
git commit -m "<task-id>: <task title>"
git rev-parse HEAD
```

The commit includes all current non-ignored Target Repository changes.
With an ignored untracked Issue Directory source, the Controller first stages tracked updates with `git add --update`, then stages non-source untracked files with an exclude pathspec.

If there are no changes to commit:

- Treat as a Task failure in v1 unless a future explicit no-op Task mode is introduced.
- Record the failure in state.
- Stop the run.

After commit:

- Record `commit_sha` in Task State.
- Mark Task `completed`.
- Move to the next Task.
- Require Target Repository clean before starting the next Task.

## 18. Resume Behavior

CLI commands:

```text
task-control run TASK_SOURCE_PATH
task-control resume RUN-2026-05-27-104500
```

`run`:

- Loads the explicit Task Source path.
- Requires Target Repository clean.
- Creates new Task Run.
- Snapshots the normalized Task Spec.
- Starts from first pending Task.

`resume`:

- Loads `runs/<run-id>/task-spec.yaml`.
- Loads `runs/<run-id>/task-state.json`.
- Does not accept a new Task Spec path.
- Continues the active Task from the state phase.
- Allows dirty Target Repository only when resuming the active Task.

The first resume implementation can be conservative. It should avoid duplicating irreversible completed work. For example:

- If `plan_approved`, do not rerun planning.
- If `commit_ready`, proceed to commit after checking state.
- If an agent turn was interrupted before output was recorded, rerun that turn on the same persistent thread where possible.

## 19. Usage-Limit Handling

The Controller must not retry every few seconds after Codex usage-limit errors.

Wrap Codex calls in:

```python
run_with_usage_limit_sleep(callable, *args, **kwargs)
```

Behavior:

1. Run the Codex operation.
2. If it succeeds, return result.
3. If it raises or returns an error that contains a usage-limit message, inspect the message.
4. Parse suggested retry time, for example:
   - `try again at 11:14 AM`
   - future absolute timestamps, if SDK returns them later.
5. Record waiting state in `task-state.json`.
6. Sleep until the suggested time, plus a small buffer.
7. Record wake-up.
8. Retry the same operation.

If no retry time can be parsed:

- Prefer failing with a clear resumable error over spinning.
- Record the unparsed message in state.

Time parsing:

- Interpret time-only strings in the user's local timezone.
- If the parsed local time is already in the past, treat it as the next day.

## 20. Git And Target Repository Rules

Before starting a new Task:

- Target Repository path must exist.
- It must be a git worktree.
- Tracked and staged changes must be clean.
- Untracked files must be clean, except for the untracked Issue Directory source
  excluded with a git pathspec.

When resuming the active Task:

- Dirty state is allowed because it may be the in-progress implementation.

Never in v1:

- `git reset --hard`.
- automatic checkout.
- automatic branch creation.
- automatic worktree add.
- automatic cleanup of untracked files.

Reviewer approval applies to all current changes that `git add --all` will stage.
For an Issue Directory Task Source inside the Target Repository, untracked source files under that directory are not staged or committed. Tracked modifications under that directory still follow normal git behavior.

## 21. CLI Design

Use Typer or argparse. The current Pixi environment includes Typer and Rich, but argparse is acceptable if the CLI stays small.

Target commands:

```text
task-control run TASK_SOURCE_PATH [--repo TARGET_REPOSITORY]
task-control resume RUN_ID
```

`TASK_SOURCE_PATH` may be a Task Spec YAML file or an Issue Directory. `--repo` is only needed when an Issue Directory is outside the Target Repository.

Future helper command, not part of the Controller loop:

```text
task-control init-spec --repo /path/to/target
```

The helper may write:

```text
task_specs/<sanitized-target-branch>/task-spec.yaml
```

But the `run` command must still receive an explicit Task Source path.

## 22. Proposed Package Structure

The current repo uses:

```text
agent_control_plane/task_control_plane/
```

Continue with that package unless the project later adopts a `src/` layout. Keep the workflow package cohesive and extract shared modules only after another workflow is migrated.

Recommended target structure:

```text
agent_control_plane/
  __init__.py
  task_control_plane/
    __init__.py
    __main__.py
    cli.py
    controller.py
    task_spec.py
    run_state.py
    artifacts.py
    codex_sdk.py
    commands.py
    git.py
    human.py
    usage_limits.py
    prompts.py
    prompts/
      planner.md
      context_agent.md
      implementer.md
      reviewer.md
    schemas/
      planner_output.schema.json
      context_answers.schema.json
      implementer_result.schema.json
      reviewer_output.schema.json
```

Responsibilities:

- `cli.py`: parse `run` and `resume`; call Controller.
- `task_spec.py`: load and validate human-managed Task Spec.
- `run_state.py`: read/write `task-state.json`, phase transitions, thread IDs.
- `artifacts.py`: paths and artifact read/write helpers.
- `codex_sdk.py`: Codex client/thread adapter and role config.
- `commands.py`: run test commands with streaming command log.
- `git.py`: clean checks, branch/SHA/status helpers, commit all changes.
- `human.py`: editor approval and batched human question answers.
- `usage_limits.py`: parse usage-limit messages and sleep.
- `prompts.py`: prompt and schema loading helpers.
- `controller.py`: deterministic workflow state machine.

Avoid building a generic workflow framework in v1.

## 23. Implementation Plan

### Phase 1: Runtime Names And Artifact Layout

Goal: keep the implementation-backed runtime contract stable.

Tasks:

1. Task Spec YAML uses `target_repository`.
2. Task Run snapshots to `task-spec.yaml`.
3. Controller state is `task-state.json`.
4. Task context is `context.json`.
5. Planning history is `planning.json`.
6. Approved Plan is `approved-plan.md`.
7. Latest implementer result is `implementation-result.json`.
8. Review history is `review.log`.
9. Prompt and schema files keep `*-agent` naming.
10. Planner questions use `context`.

Tests:

- Task Spec loads `target_repository`.
- Unsupported fields still reject.
- New run writes agreed paths.
- `task-state.json` is JSON and has expected fields.
- `context.json` contains minimal path-oriented context.

### Phase 2: State Model And Run/Resume CLI

Goal: durable Task Run lifecycle.

Tasks:

1. Introduce `run_state.py`.
2. Define run/task statuses and phases.
3. Implement atomic state writes:
   - write temporary file.
   - fsync if practical.
   - replace target.
4. Implement `task-control run TASK_SOURCE_PATH`.
5. Implement `task-control resume RUN_ID`.
6. Ensure `resume` loads saved `task-spec.yaml`, not original path.
7. Store absolute artifact paths in state.
8. Store created/updated timestamps.

Tests:

- `run` creates a new run with snapshot and state.
- `resume` uses saved snapshot.
- `resume` does not accept a new Task Spec path.
- run ID override fails when directory exists.
- runtime root defaults to top-level `runs`.

### Phase 3: Git And Context Artifacts

Goal: reliable Target Repository boundary.

Tasks:

1. Implement `git.py` helpers:
   - `require_git_worktree`.
   - `require_clean_repo`.
   - `current_branch`.
   - `current_sha`.
   - `status_short`.
   - `commit_all`.
2. Enforce clean Target Repository before new Task.
3. Allow dirty Target Repository only when resuming active Task.
4. Implement one-time `context.json` writing per Task.

Tests:

- dirty Target Repository blocks new run/new Task.
- resume active Task allows dirty repo.
- context contains task fields, run fields, repo path, artifact paths.
- context does not embed repo docs automatically.

### Phase 4: Codex SDK Adapter

Goal: role-thread lifecycle through the SDK.

Tasks:

1. Implement role enum/config.
2. Load role prompts as developer instructions.
3. Load output schemas as JSON objects.
4. Implement create-or-resume thread helper.
5. Persist Planner/Context/Implementer thread IDs immediately.
6. Implement fresh Reviewer thread creation.
7. Use public SDK symbols where possible:
   - `openai_codex.Codex`
   - `openai_codex.ApprovalMode`
   - `openai_codex.types.SandboxMode`
   - `openai_codex.types.ReasoningEffort`
8. Keep all SDK-specific adaptation out of the Controller where practical.

Tests:

- Planner starts with `auto_review`, read-only, target repo cwd.
- Planner resumes existing thread ID.
- Context starts/resumes similarly.
- Implementer uses workspace-write.
- Reviewer starts fresh each attempt with `deny_all`, read-only.
- `Thread.run` receives `output_schema`.
- Role prompts are passed as `developer_instructions`.

### Phase 5: Planning Loop

Goal: complete Planner/Context/human answer cycle.

Tasks:

1. Implement initial planner turn input.
2. Append planner outputs to `planning.json`.
3. Implement needs-answers loop.
4. Implement Context Agent turn input.
5. Record context answers.
6. Batch unresolved questions for human answers.
7. Record human answers.
8. Send latest answer batch back to Planner Agent.
9. End only on `planned`.

Tests:

- planned output writes `planning.json`.
- needs-answers output starts Context Agent.
- context answered questions recorded.
- unresolved questions sent to human provider.
- human answers recorded.
- planner follow-up sees latest answers.
- multiple planning rounds append history.
- malformed routing fields fail clearly.

### Phase 6: Plan Approval

Goal: authoritative Approved Plan Markdown.

Tasks:

1. Write `approved-plan.md` from planner `plan_markdown`.
2. If approval disabled, mark approved by controller.
3. If approval enabled, open `$EDITOR`.
4. Require explicit approval after editor returns.
5. Record approval metadata in `planning.json`.
6. Do not let implementer start before plan approval.

Tests:

- approval disabled writes plan and proceeds.
- approval enabled invokes editor callback.
- approval rejection stops/resumes safely.
- `planning.json` references `approved-plan.md`.
- implementer input does not include raw planner drafts.

### Phase 7: Implementer Agent

Goal: persistent implementation thread and latest implementation result artifact.

Tasks:

1. Add implementer prompt and schema.
2. Create/resume Implementer Agent thread.
3. Build initial implementation input with Task/context/Approved Plan paths.
4. Write latest `implementation-result.json`.
5. Accept only `implementation_complete` output before deterministic tests.

Tests:

- implementer thread persists in state.
- implementation result overwrites previous result.
- initial input includes Approved Plan path.
- initial input excludes raw planner history.
- unknown implementer status is rejected.

### Phase 8: Streaming Test Commands

Goal: deterministic test gate after each implementer turn.

Tasks:

1. Implement command runner with argv commands.
2. Stream stdout/stderr into `command.log`.
3. Append clear command headers and exit summaries.
4. Record aggregate pass/fail in state.
5. On aggregate failure, send failed-tests input to Implementer Agent.
6. Skip Reviewer Agent on failed tests.

Tests:

- command output appears in log before process exit if practical to test.
- non-zero command marks failure.
- all declared commands run even after earlier command failures.
- aggregate failure includes all command results.
- failed tests produce implementer retry input.
- reviewer not started on failed tests.

### Phase 9: Reviewer Loop

Goal: fresh review attempts and verbatim feedback.

Tasks:

1. Add reviewer prompt and schema.
2. Start fresh Reviewer Agent per attempt.
3. Build review input with artifact paths.
4. Append review JSON to `review.log`.
5. If rejected, send reviewer JSON verbatim to Implementer Agent.
6. If approved, proceed to commit.
7. Count both test failures and reviewer rejections toward `max_iterations`.

Tests:

- reviewer starts only after tests pass.
- reviewer receives `deny_all`, read-only, target repo cwd.
- reviewer prompt explains commit-all semantics.
- rejected review is appended and passed verbatim.
- approved review exits loop.
- non-blocking issues do not block commit.
- max iterations stops run and leaves repo dirty.

### Phase 10: Commit And Next Task

Goal: one commit per Task.

Tasks:

1. Implement commit-all helper.
2. Commit message format: `<task-id>: <task title>`.
3. Record commit SHA.
4. Mark Task complete.
5. Advance to next pending Task.
6. Require clean repo before next Task.
7. Mark run completed after final Task.

Tests:

- commit includes tracked and untracked non-ignored files.
- commit SHA recorded in state.
- no changes to commit fails Task.
- next Task does not start if repo is dirty.
- final Task completion marks run completed.

### Phase 11: Usage-Limit Sleep

Goal: no tight retry loops.

Tasks:

1. Implement message extraction from SDK exceptions and TurnResult errors.
2. Detect usage-limit messages.
3. Parse suggested retry time.
4. Record wait state in `task-state.json`.
5. Sleep until retry time plus small buffer.
6. Retry the same operation.
7. Fail clearly if no retry time can be parsed.

Tests:

- parses `try again at 11:14 AM`.
- same-day future time sleeps expected duration using fake clock.
- past time rolls to next day.
- unparseable usage-limit message fails without tight loop.
- state records waiting and resumed events.

### Phase 12: End-To-End Controller Tests

Goal: confidence in the full deterministic loop without real Codex calls.

Tasks:

1. Build fake Codex client and fake threads for all roles.
2. Exercise single Task happy path.
3. Exercise planner question-answer path.
4. Exercise plan approval disabled and enabled.
5. Exercise failed tests then implementer retry.
6. Exercise reviewer rejection then implementer retry.
7. Exercise max iterations failure.
8. Exercise resume from mid-planning.
9. Exercise resume from plan-approved.
10. Exercise resume from post-review/pre-commit.

Tests:

- Unit tests for modules.
- Integration tests with fake Codex and real temporary git repos.
- CLI tests for `run` and `resume`.
- Ruff check.

## 24. Testing Strategy

Testing should use real temporary git repositories and fake Codex clients.

Recommended test layers:

- Task Spec parser unit tests.
- Run state read/write unit tests.
- Artifact path unit tests.
- Git helper integration tests with temp repos.
- Command runner integration tests with small Python commands.
- Codex adapter unit tests with fake SDK objects.
- Planner/Context loop tests.
- Plan approval tests with fake editor callback.
- Implementer/test/reviewer loop tests with fake threads.
- Full Controller integration tests.
- CLI tests.

Avoid tests that require real Codex calls.

## 25. Risks And Design Tradeoffs

### SDK Output Schema Does Not Replace Routing Checks

The SDK `output_schema` guides structure, but the Controller still needs minimal checks for routing. Keep these checks narrow and explicit.

### Sleeping On Usage Limits Can Block A Terminal For Hours

This is intentional per user preference. The Controller should print/log the wake time clearly before sleeping.

### Commit-All Requires Clean Start Discipline

Since reviewer approval commits all current Target Repository changes, requiring a clean repo before each new Task is non-negotiable.

### Reviewer Reads Artifacts By Path

Prompts stay lean, but a reviewer may miss a log unless the prompt is explicit. The reviewer prompt must strongly direct it to inspect the Approved Plan and command log paths.

### No Post-Review Drift Check

This keeps v1 minimal. It relies on Reviewer Agent read-only sandbox. If future tools allow reviewer writes, revisit this.

### No Automatic Revert

Failed Tasks leave useful dirty state for inspection. This is useful but requires the next run/new Task to enforce clean-start behavior.

### No Shared Framework Yet

Keeping everything under Task Control Plane may duplicate ideas from the future research workflow. That is acceptable until there is real second-workflow duplication.

## 26. Acceptance Criteria For v1

The v1 workflow is complete when:

1. `task-control run TASK_SOURCE_PATH` can run a Task Spec YAML file or an Issue Directory with one or more Tasks.
2. The Target Repository must be clean before a new Task starts.
3. A Task Run snapshots `task-spec.yaml` and writes `task-state.json`.
4. Each Task writes the agreed compact artifact set.
5. Planner Agent can return either `planned` or `needs_answers`.
6. Context Agent can answer planner questions and escalate unresolved questions to the human.
7. Human plan approval can be enabled or disabled.
8. Approved Plan Markdown is the implementer-facing source of truth.
9. Implementer Agent can modify the Target Repository.
10. Controller test commands run after every implementer turn.
11. Failed tests go back to the same Implementer Agent.
12. Reviewer Agent runs fresh only after tests pass.
13. Reviewer rejection goes verbatim back to the Implementer Agent.
14. Reviewer approval commits all current Target Repository changes.
15. One Task produces one commit.
16. Completed Task commit SHA is recorded in state.
17. Tasks run sequentially and stop on failure.
18. `task-control resume RUN-ID` can continue a saved Task Run.
19. Usage-limit messages with suggested retry times sleep until that time and continue.
20. The workflow has unit/integration coverage with fake Codex clients and temporary git repos.

## 27. Deferred Work

- Task Spec authoring helper under `task_specs/<target-branch>/task-spec.yaml`.
- Better human UI for plan rejection and replanning.
- Optional no-op Task mode.
- Optional timeout support for long test commands.
- Optional MLflow integration for other workflows.
- Hyperliquid research workflow migration as a sibling Control-Plane Workflow.
- Shared primitives extracted after the second workflow proves common abstractions.
- Richer command result summaries.
- Optional branch/path convention warnings.
- Optional per-role effort/model if needed.
