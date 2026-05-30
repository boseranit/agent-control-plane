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

**Research Experiment**:
The canonical work unit coordinated by a **Research Experiment Controller**. One **Research Experiment** has a selected research direction, agent-produced artifacts, deterministic command evidence, and a terminal research outcome; it does not imply a final commit.
_Avoid_: Task, Loop, Cycle

**Research Brief**:
The human-authored research direction used by a **Research Experiment Controller**. A **Research Brief** states the research focus, current plan, constraints, available evidence, and preferred success signals.
_Avoid_: Loop Spec, Theme, Research Plan

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

Domain Expert: "Put the direction in the Research Brief and the run controls in the Research Run Spec."
