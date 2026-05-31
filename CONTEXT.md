# Agent Control Plane

This context defines the language for an umbrella project that hosts deterministic control-plane workflows for AI agents.

## Language

**Control-Plane Workflow**:
A deterministic orchestration pattern hosted by the Agent Control Plane. Each **Control-Plane Workflow** defines its own work unit, agents, artifacts, and completion boundary.
_Avoid_: Global Orchestrator

**Task**:
A single work item from the control plane input that proceeds through planning, implementation, review, and final commit. One **Task** has one approved plan, durable agent conversations for planning and implementation, zero or more review passes, and exactly one final commit when completed.
_Avoid_: Loop, cycle, experiment

**Task Control Plane**:
The **Control-Plane Workflow** whose canonical work unit is a **Task**.
_Avoid_: Agent Control Plane

**Research Experiment Controller**:
The workflow-specific **Controller** for research-oriented control-plane runs. A **Research Experiment Controller** produces inspectable research outcomes rather than final **Task** commits.
_Avoid_: Research Orchestrator, Global Orchestrator

**Research Run**:
One execution of a **Research Run Spec** by a **Research Experiment Controller**. A **Research Run** may produce one or more bounded **Research Experiments**.
_Avoid_: Task Run, Session, Loop

**Research Experiment**:
The canonical work unit coordinated by a **Research Experiment Controller**. One **Research Experiment** has one selected plan, one locked spec and design, one implementation/evaluation path, and one terminal **Research Outcome**; it does not imply a final commit.
_Avoid_: Task, Loop, Cycle

**Research Outcome**:
The terminal result assigned to a **Research Experiment**. Valid **Research Outcomes** are `no_op`, `blocked`, `prerequisites_failed`, `invalid`, `run_failed`, `completed_rejected`, `completed_inconclusive`, and `completed_candidate`; audit detail belongs in reason and failure-classification fields, not a second status axis.
_Avoid_: Evidence Status, Experiment Status

**Experiment Worktree**:
The preserved git worktree for one selected **Research Experiment**. An **Experiment Worktree** is an inspection boundary for research changes; it is not automatically committed, cleaned, or promoted.
_Avoid_: Task Commit, Scratch Checkout

**Evaluator Workspace**:
The isolated writable directory inside a **Research Experiment** run directory where the **Research Evaluator Agent** may create scripts, scratch files, plots, tables, and evaluation outputs.
_Avoid_: Experiment Worktree, Eval Input Copy

**Evaluation Boundary Audit**:
The controller-owned check that verifies an evaluation did not modify the **Experiment Worktree** or locked research artifacts named in the evaluation manifest. An **Evaluation Boundary Audit** can fail a **Research Experiment** even when evaluation commands appeared to run.
_Avoid_: Evaluator Self-Check

**Implementation Repair Loop**:
The bounded controller-owned loop that returns verification failures to the same **Research Implementer Agent** without changing research semantics. An **Implementation Repair Loop** repairs execution, not the selected research design.
_Avoid_: Evaluation Repair Loop, Research Redesign

**Outcome Classification Policy**:
The configurable rules a **Research Experiment Controller** uses to assign a **Research Outcome** from controller evidence, command results, audit findings, and evaluation artifacts.
_Avoid_: Hard-coded Outcome Mapping

**Research Run Stop Policy**:
The configurable rule a **Research Experiment Controller** uses to decide whether `prerequisites_failed` stops the enclosing **Research Run**. The default is to stop after `prerequisites_failed`.
_Avoid_: Hidden Stop Condition

**Material Revision Policy**:
The controller-owned rules that decide whether a research-design revision requires a fresh **Research Critic Agent** pass. Agents may declare a revision material, but they do not decide that a revision is non-material.
_Avoid_: Agent-Owned Materiality

**Research Artifact**:
A canonical JSON artifact produced or consumed at a **Research Experiment** controller-agent boundary. **Research Artifacts** are validated contracts; controller internals and ledgers are not research artifacts.
_Avoid_: Internal State Object

**Research Run Mirror**:
A provider-neutral, end-of-experiment best-effort copy of selected **Research Run** and **Research Experiment** facts into an external browsing/comparison surface such as MLflow. A **Research Run Mirror** is a review surface only; the run directory and ledger remain canonical. Code uses `research_run_mirror` for this boundary.
_Avoid_: Shell-terminal language, MLflow State, Trace Log

**Research Run Spec**:
The human-managed input document for a **Research Run**. A **Research Run Spec** contains both the human research direction and the operational run controls for one or more bounded **Research Experiments**.
_Avoid_: Separate Research Brief file, Loop Spec

**Research Budget**:
A named execution profile in a **Research Run Spec** that constrains pipeline and backfill command scope for the whole **Research Run**. A **Research Budget** can define data windows and runtime limits, but it is not an experiment outcome gate.
_Avoid_: Per-Experiment Budget, Success Gate

**Research Brief**:
The research-direction section inside a **Research Run Spec**. A **Research Brief** states the research focus, current plan, constraints, available evidence, and preferred success signals, but is not managed as a separate file.
_Avoid_: Standalone Research Brief file, Theme, Research Plan


**Task ID**:
A stable human-supplied identifier for one **Task**. The **Task ID** is the durable key for task state, agent conversations, artifacts, resume behavior, and final commit messages.
_Avoid_: Auto-number, Generated ID

**Task State**:
Controller-owned runtime state for a **Task**. Humans provide the initial manifest and approval input, but they do not manage **Task State** directly.
_Avoid_: Task Config, Manifest

**Task Spec**:
The human-managed input document for a **Task Control Plane** run. A **Task Spec** names the **Target Repository**, declares **Tasks**, provides run-level policy, and is scoped to the target branch it is intended to advance.
_Avoid_: Task Manifest, Task State

**Task Run**:
One execution of a **Task Spec** by the **Controller**. A **Task Run** stores an immutable copy of the **Task Spec**, controller-owned state, and task artifacts under the control-plane runtime root.
_Avoid_: Session, Batch

**Controller**:
The deterministic coordinator for a **Control-Plane Workflow**. Each **Controller** owns workflow ordering, gates, agent handoffs, command execution, state recording, and the workflow's completion boundary.
_Avoid_: Orchestrator

**Durable Execution Shell**:
The resumable outer execution mechanism for a **Control-Plane Workflow**. A **Durable Execution Shell** may expose generic run metadata for inspection, but the **Controller** remains authoritative for workflow meaning and state.
_Avoid_: Workflow Brain, Agent Orchestrator

**Controller Run Metadata**:
Generic inspection metadata exposed by a **Durable Execution Shell** for a **Research Run** or **Task Run**. **Controller Run Metadata** summarizes identifiers, phase, version, and status without owning workflow decisions.
_Avoid_: Controller State, Research Artifact

**Target Repository**:
The single repository that a control-plane run inspects, modifies, tests, reviews, and commits for its **Tasks**.
_Avoid_: Working Repo, Execution Target

**Context Agent**:
An AI agent that answers structured **Planner Agent** questions for one **Task** from available project context and direct read-only inspection of the **Target Repository**. In the first version, the **Context Agent** participates only in planning.
_Avoid_: Context Resolver, Orchestrator Agent

**Planner Agent**:
An AI agent that turns one **Task** and its context into either an approved-ready plan or structured questions. Questions are encouraged when uncertainty affects the plan, but a planner may return a plan without questions when the task is already clear.
_Avoid_: Planner, Planning Subagent

**Approved Plan**:
The authoritative plan artifact for a **Task**. It may be the **Planner Agent** output as-is or a human-edited version, depending on the configured approval policy.
_Avoid_: Final Plan, Selected Plan

**Implementer Agent**:
An AI agent that carries out the approved plan for one **Task** and continues across reviewer feedback iterations for that **Task**.
_Avoid_: Coder, Builder

**Reviewer Agent**:
An AI agent that evaluates the current implementation of one **Task** and returns structured approval or requested changes. Each review pass uses a fresh **Reviewer Agent** conversation.
_Avoid_: Critic, Review Subagent

**Review Approval**:
The **Reviewer Agent** decision that a **Task** is ready for its final commit. A **Review Approval** applies to the complete target repository changes that the **Controller** will commit for that **Task**.
_Avoid_: LGTM, Non-blocking Review

## Example Dialogue

Developer: "Does this run contain three tasks?"

Domain Expert: "Yes. Each task gets its own planner conversation, implementation thread, reviewer passes, and final commit before the next task begins."

Developer: "Can I fix a stuck task by editing the state file?"

Domain Expert: "No. Task state is owned by the controller; change the manifest or respond at an approval gate instead."

Developer: "Should a research run become a Task before it writes MLflow artifacts?"

Domain Expert: "No. A Research Experiment is a separate work unit; it records research outcomes and evidence without implying a final Task commit."

Developer: "Where do I put the research direction versus the run controls?"

Domain Expert: "Put both in the Research Run Spec; the direction lives in the Research Brief section."
