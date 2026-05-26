# Task Control Plane PRD

Status: ready-for-agent
Label: ready-for-agent

## Problem Statement

The user wants an Agent Control Plane workflow that can coordinate Codex agents through a deterministic, resumable software-task loop. The workflow must let the user provide a branch-scoped Task Spec, then have the Controller run one Task at a time through planning, context-question answering, optional human plan approval, implementation, deterministic tests, fresh independent review, iterative fixes, and a final task commit.

The user does not want a free-form autonomous agent that decides its own outer workflow. They want the outer loop to remain ordinary deterministic Python code, with Codex used behind explicit role boundaries. The Controller should decide which role runs next, what artifact paths are passed, when tests run, when human input is required, when reviewer feedback goes back to the implementer, and when a task may be committed.

The user also wants this workflow to be independent from, but philosophically informed by, the existing Hyperliquid research orchestrator. The existing research orchestrator is not being migrated or fixed in this PRD. It exists as prior art for deterministic orchestration, structured outputs, bounded context packets, command execution, and ledger-like state. The Task Control Plane must be designed as a separate Control-Plane Workflow inside the Agent Control Plane umbrella, leaving room for the Hyperliquid workflow to be migrated later as a sibling workflow with shared primitives extracted only when real duplication exists.

The current repo has a domain glossary, agent docs, and a Pixi environment with the Codex SDK, MLflow, pytest, ruff, YAML, JSON Schema, and small operational utilities. It does not yet contain the Task Control Plane implementation.

The workflow must prevent several failure modes seen in earlier orchestration work:

- Agents should not repeatedly rediscover ambiguity without a structured question-answer path.
- The Controller should not keep retrying every few seconds after usage-limit errors.
- Failed deterministic tests should not waste reviewer turns.
- Reviewer approval must mean "safe to commit all current Target Repository changes for this Task."
- Human-editable inputs must be separate from Controller-owned state.
- Runtime artifacts should be compact, inspectable, and resumable without becoming a directory explosion.
- The Target Repository should remain the execution surface; control-plane runtime state should live in the control-plane repo.

## Solution

Build the first Task Control Plane workflow as a synchronous CLI-driven Python package in the Agent Control Plane repo.

The user writes a Task Spec for a target branch. The Task Spec is explicitly passed to the CLI. It declares the Target Repository, optional run description/context, run-level Codex model and reasoning effort, optional plan approval policy, deterministic test commands, iteration limit, and an ordered list of Tasks. Each Task has a stable Task ID, title, prompt, and optional task-specific context.

When the user starts a Task Run, the Controller snapshots the Task Spec into the run, initializes Controller-owned Task State, requires the Target Repository to be clean before starting a new Task, and then executes Tasks sequentially in Task Spec order. A Task must complete and commit before the next Task starts.

For each Task, the Controller creates a compact task context artifact with paths and minimal known facts. It then creates or resumes a persistent Planner Agent thread and a persistent Context Agent thread. The Planner Agent runs with read-only sandbox and `auto_review`, using the Codex SDK output schema to return either a plan or structured questions. Questions are encouraged but not mandatory. When questions are returned, the Context Agent answers from direct read-only inspection of the Target Repository and available task context. Any unresolved questions are batched for human answers. The answers are recorded in the planning artifact and passed back to the Planner Agent until it returns `status: planned` with `plan_markdown`.

The Controller writes the planner plan into an approved plan Markdown artifact. If plan approval is enabled, the Controller opens the file in the user's editor and requires explicit human approval before continuing. If approval is disabled, the planner's `plan_markdown` becomes the Approved Plan automatically. The Implementer Agent receives only the Task, task context path, and Approved Plan path, not raw planner drafts.

The Controller creates or resumes a persistent Implementer Agent thread for the Task. The Implementer Agent runs with workspace-write sandbox and `auto_review`. After every implementer turn, the Controller runs the Task Spec test commands in the Target Repository, streaming all command output into one command log for the Task. If tests fail, the Controller sends the command log path and Approved Plan path back to the same Implementer Agent, then repeats. Failed tests bypass the Reviewer Agent.

When tests pass, the Controller creates a fresh Reviewer Agent thread for that review attempt. The Reviewer Agent runs with read-only sandbox and `deny_all`. It receives the Task, task context path, Approved Plan path, command log path, and review log path. It is not handed a precomputed diff packet; it may inspect the Target Repository directly, run git inspection commands, read the command log, and evaluate the current changes. The reviewer returns structured output through the Codex SDK output schema:

- `status: approved` means the Controller will commit all current Target Repository changes for the Task.
- `status: rejected` means the Controller appends the review to the review log and sends the full reviewer JSON verbatim to the same Implementer Agent.
- `blocking_issues` and `requested_changes` are commit-blocking.
- `non_blocking_issues` are advisory and do not prevent commit if `status` is `approved`.

The implementer-review loop continues until the Reviewer Agent approves or the Task reaches the maximum iteration count. The default maximum is 10, counting both test-fix and review-fix cycles. If the maximum is reached, the Controller marks the Task failed, stops the Task Run, and leaves the Target Repository dirty for inspection. It does not revert changes.

After approval, the Controller commits all current Target Repository changes with a commit message beginning with the Task ID and task title. It records the commit SHA in Task State, marks the Task complete, and moves to the next Task. It does not run a redundant final test after reviewer approval and does not perform a post-review drift check in v1, because reviewer runs read-only and the latest tests already passed before review.

The Controller uses one long-lived synchronous `Codex` client per `run` or `resume` process. It persists thread IDs in Task State. On restart, `resume` loads the saved Task Spec snapshot and Task State, resumes the right Codex threads, and continues from the current phase. Usage-limit errors are handled by parsing the suggested retry time, sleeping until then, and continuing automatically rather than spinning every few seconds or stopping immediately.

## User Stories

1. As the user, I want to define a Task Spec with an explicit Target Repository, so that the Controller knows exactly which repo to modify and commit.
2. As the user, I want every Task to have a stable Task ID, so that task state, artifacts, threads, and commits remain tied to the same work item.
3. As the user, I want Tasks to run sequentially in Task Spec order, so that each commit establishes a stable base for the next Task.
4. As the user, I want one Task to produce one final commit, so that reviewing history and reverting work remain straightforward.
5. As the user, I want the Controller to require a clean Target Repository before starting a new Task, so that unrelated human edits are not accidentally committed.
6. As the user, I want a dirty Target Repository to be allowed only when resuming an active Task, so that interrupted implementation work can continue safely.
7. As the user, I want the Controller to snapshot the Task Spec into the Task Run, so that resume behavior is based on the exact input that started the run.
8. As the user, I want Controller-owned Task State to be separate from the Task Spec, so that humans edit inputs and the Controller manages runtime progress.
9. As the user, I want Task State to be the authoritative resume source, so that the Controller does not infer workflow state by guessing from artifact files.
10. As the user, I want top-level run artifacts in a simple runtime root, so that generated state is easy to find without an extra hidden control-plane folder.
11. As the user, I want generated Task Runs to be gitignored, so that logs, thread IDs, and runtime context are not committed by default.
12. As the user, I want a compact task artifact set, so that each Task is inspectable without dozens of phase files.
13. As the user, I want a single command log per Task, so that test output is streamed live but remains easy to inspect.
14. As the user, I want command output to stream while commands run, so that long-running tests or commands do not appear stuck.
15. As the user, I want deterministic test commands to be declared as named argv commands, so that subprocess execution avoids shell quoting ambiguity.
16. As the user, I want multiple test commands to be supported, so that lint, unit tests, and targeted checks can run in order.
17. As the user, I want tests to run after every Implementer Agent turn, so that failures are caught before review.
18. As the user, I want failed tests to go directly back to the Implementer Agent, so that the Reviewer Agent is not used for obvious red test output.
19. As the user, I want the Reviewer Agent to run only after deterministic tests pass, so that review focuses on task completion and code quality.
20. As the user, I want a fresh Reviewer Agent for each review attempt, so that each review pass remains independent.
21. As the user, I want the Implementer Agent thread to persist across review iterations, so that it remembers its own implementation choices and prior feedback.
22. As the user, I want the Planner Agent thread to persist across planner question-answer turns, so that planning has continuity.
23. As the user, I want the Context Agent thread to persist during planning, so that answers build on the same task context.
24. As the user, I want Reviewer Agent threads not to persist across attempts, so that review does not become anchored to earlier opinions.
25. As the user, I want all role threads to run with the Target Repository as their working directory, so that agents can inspect the actual repo they are operating on.
26. As the user, I want Planner Agent and Context Agent to run read-only, so that planning cannot mutate the Target Repository.
27. As the user, I want Reviewer Agent to run read-only with deny-all approvals, so that review cannot accidentally modify the Target Repository.
28. As the user, I want Implementer Agent to run workspace-write with auto-review approvals, so that it can perform coding work with reasonable friction.
29. As the user, I want all role prompts to be stable developer instructions, so that turn inputs stay focused on task-specific data and artifact paths.
30. As the user, I want Codex output schemas passed through the SDK, so that role outputs are structured without adding a separate hard validation layer.
31. As the user, I want only minimal routing checks after structured output, so that the Controller remains deterministic without over-hardening agent contracts.
32. As the user, I want Planner Agent questions to be highly encouraged but not mandatory, so that planning can ask when uncertainty matters without inventing low-value questions.
33. As the user, I want planner questions to be structured, so that the Context Agent and human answer path can route them deterministically.
34. As the user, I want the Context Agent to answer planner questions from repo inspection when possible, so that the human is not asked questions the repo can answer.
35. As the user, I want unresolved planner questions batched for human input, so that planning does not become a slow one-question-at-a-time loop.
36. As the user, I want human answers recorded with Context Agent answers, so that planning history remains inspectable.
37. As the user, I want plan approval to be optional, so that some Task Runs can be fully automated after planning.
38. As the user, I want plan approval enabled by default, so that significant work normally passes through human review before implementation.
39. As the user, I want approved plans edited in Markdown through my editor, so that I do not need to hand-edit JSON.
40. As the user, I want the Approved Plan Markdown artifact to be authoritative, so that the Implementer Agent receives one clear plan.
41. As the user, I want raw planner outputs retained as planning history, so that I can inspect how the Approved Plan was reached.
42. As the user, I want the Implementer Agent to receive only the Approved Plan, so that raw planner drafts or human-edited changes do not conflict.
43. As the user, I want the Reviewer Agent to know approval commits all current Target Repository changes, so that it reviews the complete commit boundary.
44. As the user, I want reviewer feedback passed verbatim to the Implementer Agent, so that the Controller does not distort or reinterpret feedback.
45. As the user, I want non-blocking review issues recorded but not commit-blocking, so that advisory feedback does not stall approved work.
46. As the user, I want the Controller to commit all tracked and untracked non-ignored Target Repository changes after approval, so that each Task produces a complete commit.
47. As the user, I want commit messages to start with the Task ID and title, so that git history maps back to Task Spec entries.
48. As the user, I want the commit SHA recorded in Task State, so that the Task Run can prove where each Task landed.
49. As the user, I want the Controller to stop the run on Task failure, so that later Tasks do not build on unapproved dirty state.
50. As the user, I want failure after max iterations to leave the Target Repository dirty, so that I can inspect and recover the attempted work.
51. As the user, I do not want automatic branch creation in v1, so that the Controller operates in the branch I intentionally checked out.
52. As the user, I do not want automatic worktree creation in v1, so that all work stays in the same Target Repository checkout.
53. As the user, I do not want automatic reverts in v1, so that the Controller never destroys useful failed work.
54. As the user, I want usage-limit messages handled intelligently, so that the Controller sleeps until the suggested retry time instead of hammering retries.
55. As the user, I want the Controller to continue automatically after the usage-limit sleep, so that long Task Runs can complete without manual babysitting.
56. As the user, I want one long-lived Codex client per process, so that thread handling is efficient and simple.
57. As the user, I want resume to use saved Task State and the snapshotted Task Spec, so that restarting does not depend on a mutable external spec.
58. As the user, I want separate `run` and `resume` commands, so that starting new work and continuing old work are explicit operations.
59. As the user, I want `resume` to identify the Task Run by run ID, so that it does not accidentally load a different Task Spec.
60. As the user, I want the CLI run command to require an explicit Task Spec path, so that the Controller does not guess which branch-scoped spec to use.
61. As the user, I want Task Spec authoring to be separate from running, so that a helper can create branch-scoped specs without making the Controller rewrite its own inputs.
62. As the user, I want Task Specs authored under a branch-scoped convention, so that work for different target branches remains organized.
63. As the user, I do not want the Controller to validate branch/spec path matching in v1, so that explicit spec path selection remains the user's responsibility.
64. As the user, I want the Task Spec to include the Target Repository path, so that the run snapshot is self-contained.
65. As the user, I do not want target branch metadata in the Task Spec, so that the spec stays small and avoids unused validation fields.
66. As the user, I want optional run-level description and context fields, so that I can give all agents shared background.
67. As the user, I want optional per-task context, so that each Task can have supporting details separate from its prompt.
68. As the user, I do not want Task dependencies in v1, so that Task Spec order remains the execution order.
69. As the user, I do not want environment variable support in v1, so that tests do not depend on hidden run-specific environment.
70. As the user, I want Codex model and effort configurable in the Task Spec, so that a Task Run records the intended model configuration.
71. As the user, I do not want service tier in the Task Spec in v1, so that Codex config stays minimal.
72. As the user, I want Codex effort to be run-level only in v1, so that role configuration remains simple.
73. As the user, I want role prompts in Markdown files, so that I can review and edit the role behavior easily.
74. As the user, I want role output schemas source-controlled with the workflow, so that structure is explicit and versioned.
75. As the user, I do not want schemas pasted into prompts, so that the SDK output schema mechanism owns structure.
76. As the user, I want the task context artifact to be generated once per Task, so that agents share stable path references and minimal facts.
77. As the user, I do not want repo markdown docs automatically embedded into context packets, so that prompts stay lean and agents inspect docs directly when needed.
78. As the user, I want agents to receive absolute artifact paths, so that control-plane artifacts stay outside the Target Repository but remain readable.
79. As the user, I do not want every prompt input written to files in v1, so that artifact count stays minimal.
80. As the user, I want Planner, Context, and Reviewer Agents allowed to inspect the Target Repository directly, so that they can answer context questions and review actual changes.
81. As the user, I want the Reviewer Agent to inspect git status and diffs itself, so that the Controller does not need to construct a diff packet.
82. As the user, I want the Reviewer Agent told where command logs and review logs are, so that it can read them as needed without bloating the prompt.
83. As the user, I want MLflow installed in the environment but not integrated into Task Control Plane v1, so that future workflows can use it without delaying this loop.
84. As the user, I want Hyperliquid research workflow migration out of scope, so that this PRD focuses on the new Task Control Plane.
85. As the user, I want future shared modules extracted only after a second workflow exists, so that v1 does not over-abstract before there is real duplication.
86. As the user, I want robust state transitions, so that a Task Run can resume after interruption without duplicating completed phases.
87. As the user, I want artifact writes to be deterministic and compact, so that each Task Run can be inspected and debugged by reading a small set of files.
88. As the user, I want command failures, reviewer rejections, and usage-limit sleeps recorded in state/logs, so that I can understand why a run is waiting, retrying, or failed.
89. As the user, I want no extra command-runner agent in this workflow, so that the Controller remains the only deterministic executor of test commands.
90. As the user, I want implementer-recommended commands to be non-authoritative, so that the manifest test commands remain the gate before review.

## Implementation Decisions

- The workflow is a Control-Plane Workflow named Task Control Plane inside the Agent Control Plane umbrella. It should be implemented as a workflow-first package, not as a prematurely generalized shared framework.
- The first implementation should build a cohesive Task Control Plane package with internal modules for Task Spec handling, Task Run state, Codex thread management, role prompts and schemas, command execution, git operations, human approval, usage-limit sleeping, and the Controller state machine.
- Shared modules should not be extracted until at least one additional Control-Plane Workflow, such as the future Hyperliquid research workflow, is migrated and real duplication exists.
- The Task Spec is the human-managed input. It must include the Target Repository and ordered Tasks. It may include run-level description, run-level context, plan approval policy, maximum iterations, Codex model and effort, and named test commands.
- Each Task must include an explicit stable Task ID. The Controller should not silently generate Task IDs for execution. A separate helper may create Task Specs from rough notes later.
- Task Spec authoring is conventionally branch-scoped, but the Controller does not infer a Task Spec path. The run CLI requires an explicit Task Spec path.
- The Controller snapshots the Task Spec into the Task Run and resumes only from that snapshot plus Controller-owned Task State.
- Task State is Controller-owned and authoritative for resume. Humans should not be expected to edit it.
- A Task Run uses a top-level runtime root named `runs`, and that runtime root should be ignored by git.
- The Task artifact set should be compact: one stable context artifact, one planning metadata/history artifact, one authoritative Approved Plan Markdown artifact, one latest implementation result artifact, one append-only review log, and one append-only command log.
- The Approved Plan Markdown artifact is authoritative. Planning metadata may reference it and retain raw planner outputs and answer history, but it must not duplicate authoritative plan text as another source of truth.
- The context artifact is generated once per Task before planning. It should contain minimal controller-known facts and absolute paths to relevant artifacts. It should not embed repo markdown docs or histories that agents can inspect directly.
- The Controller should not write every prompt input as a file in v1.
- The Controller uses synchronous `openai_codex.Codex`, one long-lived client per `run` or `resume` process.
- Role behavior is supplied through SDK developer instructions when starting or resuming threads. Turn inputs carry task-specific context and artifact paths.
- Persistent role threads per Task:
  - Planner Agent: persistent for planning and follow-up turns.
  - Context Agent: persistent for planning question answering only.
  - Implementer Agent: persistent across implementation, failed tests, and reviewer feedback.
- Fresh role threads per attempt:
  - Reviewer Agent: fresh for every review attempt.
- Thread IDs must be persisted in Task State. On resume, the Controller uses SDK thread resume rather than creating new persistent Planner, Context, or Implementer threads.
- The Controller uses SDK `Thread.run(..., output_schema=...)` for structured outputs. It should not paste schemas into prompts.
- The Controller should do only minimal post-output routing checks, such as checking `status`, required routing fields, and parseability. It should not implement a hard second validation layer that rejects discretionary agent fields.
- Prompt and schema artifacts should be workflow-specific to Task Control Plane. They should be source-controlled, editable, and versioned with the workflow.
- Role configuration defaults:
  - Planner Agent: `auto_review`, read-only sandbox.
  - Context Agent: `auto_review`, read-only sandbox.
  - Implementer Agent: `auto_review`, workspace-write sandbox.
  - Reviewer Agent: `deny_all`, read-only sandbox.
- The Task Spec may set run-level Codex model and effort. It should not include service tier in v1. Effort is run-level only in v1.
- Planner output should support at least:
  - `status: needs_answers` with structured questions.
  - `status: planned` with `plan_markdown`.
- Planner questions are highly encouraged when uncertainty affects implementation, but not mandatory for clear Tasks.
- Planner question objects should be structured enough to identify question IDs, context, question text, and type.
- Context Agent output should answer questions where possible and mark unresolved questions for human input. It does not need formal evidence arrays; a concise reason string is sufficient.
- Unresolved planner questions should be batched for human input. Human answers and Context Agent answers should be recorded in the planning artifact.
- Plan approval is controlled by `require_plan_approval`, defaulting to true.
- If plan approval is enabled, the Controller writes the pending plan to the Approved Plan Markdown artifact, opens it in `$EDITOR`, then requires explicit human approval.
- If plan approval is disabled, the Controller writes the Planner Agent `plan_markdown` directly as the Approved Plan.
- The Implementer Agent receives only the authoritative Approved Plan, the Task, and the task context path. It does not receive raw planner drafts by default.
- The Controller runs deterministic test commands after each Implementer Agent turn.
- Test commands are named argv commands. Shell strings are not part of v1.
- The Controller streams all test command output into a single command log per Task.
- Failed deterministic tests bypass the Reviewer Agent. The command log path and Approved Plan path are sent back to the same Implementer Agent.
- The Reviewer Agent receives the Task, context path, Approved Plan path, command log path, and review log path. It is not handed an embedded diff or log body by default.
- The Reviewer Agent may inspect the Target Repository directly, including git status, diffs, commits, and files.
- Reviewer output should support:
  - `status: approved` or `status: rejected`.
  - `blocking_issues`.
  - `requested_changes`.
  - `non_blocking_issues`.
- Reviewer prompt semantics must explicitly state that `approved` means the Controller will commit all current Target Repository changes for the Task.
- Reviewer prompt semantics must explicitly state that non-blocking issues do not prevent commit.
- On reviewer rejection, the Controller appends the full review to the review log and passes the reviewer JSON verbatim to the Implementer Agent. There is no feedback-conversion agent and no semantic rewrite.
- The iteration counter covers both failed-test repair cycles and reviewer-rejection repair cycles. Default maximum is 10.
- If maximum iterations are reached, the Controller marks the Task failed, stops the Task Run, and leaves the Target Repository dirty for inspection.
- The Controller should not automatically create branches in v1.
- The Controller should not create or manage worktrees in v1.
- The Controller should not automatically revert task changes in v1.
- The Controller should not skip failed Tasks in v1.
- The Controller should commit all current non-ignored Target Repository changes after latest tests pass and the Reviewer Agent returns `approved`.
- Commit messages should begin with the Task ID and task title. If the title is unavailable, the Controller may fall back to a concise prompt-derived summary.
- The Controller records the commit SHA in Task State and proceeds to the next Task.
- The Controller does not run another test command after reviewer approval in v1.
- The Controller does not perform a post-review drift check in v1.
- The Controller should parse Codex usage-limit errors when they include a suggested retry time, sleep until the suggested time, and continue automatically. It should not retry every few seconds.
- The Controller should record usage-limit sleeps in state or logs so the user can understand why the process is waiting.
- The CLI should have separate `run` and `resume` commands.
- `run` starts a new Task Run from an explicit Task Spec path.
- `resume` continues an existing Task Run from saved Task Spec snapshot and Task State.
- The Controller should require the Target Repository to be clean before starting a new Task. When resuming an active Task, dirty state may be accepted as the Task's in-progress implementation.
- The Task Spec should not include environment variables in v1.
- The Task Spec should not include target branch metadata in v1.
- The Task Spec should not include dependency graph fields in v1.
- MLflow remains an environment dependency but is not part of Task Control Plane runtime behavior in v1.
- The current Pixi environment is sufficient for v1 development: Codex SDK, MLflow dependency for future workflows, pytest, ruff, YAML/JSON tooling, and small operational libraries are present.

The main Controller loop should follow this state-machine shape from the user's prototype, trimmed to decision-rich steps:

```text
for each remaining Task:
  require clean Target Repository unless resuming active Task
  create or resume Task State
  write task context once

  run Planner Agent
  while planner needs answers:
    run Context Agent
    ask human for unresolved answers
    run Planner Agent follow-up

  write Approved Plan candidate
  optionally open editor and require human approval

  run Implementer Agent
  while not approved:
    stop if max iterations reached
    run test commands into command log
    if tests fail:
      send command log path back to Implementer Agent
      continue

    run fresh Reviewer Agent
    if approved:
      commit all Target Repository changes
    else:
      send reviewer JSON verbatim to Implementer Agent
```

## Testing Decisions

- Tests should verify external behavior of modules and workflow transitions, not private implementation details.
- The deepest testable modules should be built around stable interfaces:
  - Task Spec loading and normalization.
  - Task Run and Task State persistence.
  - Codex thread gateway.
  - Usage-limit sleep policy.
  - Streaming command runner.
  - Git cleanliness and commit operations.
  - Human plan approval flow.
  - Controller state machine.
- Task Spec tests should cover required Target Repository, explicit Task IDs, ordered Tasks, default values, multiple named argv test commands, invalid duplicate Task IDs, missing task prompts, missing test command argv, and rejected unsupported fields where the implementation chooses to reject them.
- Task State tests should cover creation, persistence, resume loading, thread ID recording, phase updates, iteration count updates, test status recording, review attempt recording, failed task recording, completed task recording, and commit SHA recording.
- Controller tests should use fake Codex clients and fake threads rather than real SDK calls. The fake should expose thread IDs, capture developer instructions, capture role configuration, return queued structured outputs, and assert resume behavior.
- Controller tests should cover the happy path:
  - Planner returns planned immediately.
  - Plan approval disabled.
  - Implementer returns result.
  - Tests pass.
  - Reviewer approves.
  - Git commit operation is invoked once.
  - Task State records completion.
- Controller tests should cover the human approval path:
  - Planner returns planned.
  - Approved Plan Markdown is written.
  - Editor hook is invoked.
  - Human approval gate is required.
  - Implementer receives Approved Plan path only.
- Controller tests should cover planner questions:
  - Planner returns `needs_answers`.
  - Context Agent answers some questions.
  - Human answers unresolved questions.
  - Planner follow-up returns planned.
  - Planning artifact records planner output history and answer history.
- Controller tests should cover repeated planner question loops, not just a single question-answer cycle.
- Controller tests should cover failed deterministic tests:
  - Implementer runs.
  - Test command fails.
  - Reviewer is not created.
  - Same Implementer Agent thread receives failed test input.
  - Iteration count increments.
- Controller tests should cover reviewer rejection:
  - Tests pass.
  - Fresh Reviewer Agent returns rejected.
  - Review JSON is appended.
  - Same Implementer Agent thread receives the reviewer JSON verbatim.
- Controller tests should cover reviewer approval:
  - Tests pass.
  - Fresh Reviewer Agent returns approved with optional non-blocking issues.
  - Controller commits all Target Repository changes.
  - Non-blocking issues do not prevent commit.
- Controller tests should cover maximum iterations:
  - Combined failed-test and reviewer-rejection attempts reach the cap.
  - Task is marked failed.
  - Run stops.
  - No revert is attempted.
  - No later Task starts.
- Controller tests should cover clean repo enforcement:
  - New Task refuses dirty Target Repository.
  - Resume of active Task can proceed with dirty Target Repository.
- Git module tests should use temporary repositories to verify:
  - Clean and dirty status detection.
  - Commit-all behavior includes tracked changes and untracked non-ignored files.
  - Ignored files are not committed.
  - Commit message begins with Task ID and title.
  - Commit SHA is returned.
- Command runner tests should use small subprocess commands to verify:
  - Named argv commands run in order.
  - Output streams into one command log.
  - Exit codes are recorded.
  - A failing command marks the test result failed.
  - Later commands behavior is explicit and tested, whether the implementation stops on first failure or runs all commands.
- Usage-limit policy tests should avoid real sleeping by injecting a clock/sleeper. They should verify:
  - Suggested retry time is parsed from representative Codex messages.
  - The computed sleep duration is non-negative.
  - The wrapped Codex call is retried after sleep.
  - Non-usage errors propagate normally.
- Human approval tests should inject editor and confirmation callbacks so tests do not open a real editor.
- Prompt/schema tests should verify schemas are loadable and minimal sample outputs for planner, context answers, implementer result, and reviewer output are accepted by the SDK-facing gateway or schema loader.
- The Codex SDK adapter should have unit tests around argument construction:
  - Uses one Codex client supplied by the caller.
  - Starts new threads with role developer instructions.
  - Resumes existing threads with the saved thread ID.
  - Passes `output_schema` to `Thread.run`.
  - Stores returned `Thread.id` in Task State.
- The CLI should have tests for:
  - `run` requires an explicit Task Spec path.
  - `run` snapshots the Task Spec and initializes a Task Run.
  - `resume` requires a run ID.
  - `resume` loads saved state and does not accept a replacement Task Spec.
  - Errors are clear when Task Spec, Target Repository, or Task Run state is missing.
- Integration tests should run without real Codex by using fake Codex threads and temporary Target Repositories.
- Tests should not depend on MLflow because MLflow is not part of Task Control Plane v1 runtime behavior.
- Tests should not depend on real usage-limit sleeps, real editors, or network access.
- Prior art from the Hyperliquid orchestrator is useful for testing patterns:
  - fake Codex clients returning sequenced structured outputs.
  - deterministic context artifact generation.
  - subprocess command execution tests.
  - JSON artifact writing.
  - git cleanliness and branch/SHA capture.

## Out of Scope

- Migrating the Hyperliquid research orchestrator into this repo.
- Fixing Hyperliquid research orchestrator issues such as no-op cycle behavior, worktree reuse, data-root assumptions, MLflow metrics flattening, experiment output contracts, or prior experiment synthesis.
- Extracting shared control-plane modules before a second workflow exists.
- Building a general multi-agent framework or scheduler.
- Supporting multiple Target Repositories in one Task Run.
- Supporting per-task Target Repository overrides.
- Supporting task dependency graphs or parallel task execution.
- Supporting automatic branch creation.
- Supporting automatic worktree creation.
- Supporting automatic push, pull request creation, or remote repository mutation.
- Supporting automatic revert or cleanup after failure.
- Supporting final post-review test reruns.
- Supporting post-review drift checks.
- Supporting MLflow logging for Task Control Plane v1.
- Supporting environment variable injection in Task Spec v1.
- Supporting service tier configuration in Task Spec v1.
- Supporting target branch metadata validation in Task Spec v1.
- Supporting shell-string commands in Task Spec v1.
- Building a separate command-runner agent.
- Automatically embedding all target repo markdown docs into context packets.
- Writing every prompt input to disk.
- Hard-validating all agent discretionary output fields beyond routing needs.
- Creating a web UI.
- Creating a daemon or background service.
- Creating a Task Spec authoring skill or helper as part of this PRD, although the design should leave room for one.

## Further Notes

- The glossary in the repo should remain the source of canonical vocabulary. In particular, use Task, Task Spec, Task Run, Task State, Controller, Target Repository, Planner Agent, Context Agent, Implementer Agent, Reviewer Agent, Approved Plan, and Review Approval consistently.
- The Controller should avoid the term "orchestrator" in user-facing Task Control Plane language because the glossary reserves Controller for deterministic coordination.
- The Task Control Plane should be designed to feel small, inspectable, and conservative. Most complexity should live inside deep modules with stable interfaces rather than in ad hoc controller branches.
- The user prefers minimal files and minimal validations. The implementation should respect that preference while still preserving deterministic routing and reliable resume behavior.
- The user explicitly wants usage-limit handling to sleep until the suggested retry time and continue automatically, even if that means sleeping for hours.
- The user explicitly wants no additional questions before this PRD. This PRD synthesizes the grilling session and current repo state.
