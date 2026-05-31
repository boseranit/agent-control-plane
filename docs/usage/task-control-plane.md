# Task Control Plane Usage

Use this when a Target Repository has a prepared Task Source and you want the
Controller to plan, implement, review, and commit Tasks one at a time.

## Inputs

The `run` command accepts either:

- a Task Spec YAML file;
- an Issue Directory containing local markdown issue files.

An Issue Directory uses `README.md` as PRD/run context. Every other `*.md`
file becomes one Task in lexical order. The file stem is the Task ID, the first
`#` heading is the title, and the full markdown body is the Task prompt.

If an untracked Issue Directory lives inside the Target Repository, the
Controller ignores it for clean checks and commit staging. Tracked or staged
Issue Directory changes still count as dirty Target Repository changes.

If the Issue Directory is outside the Target Repository, pass `--repo
/path/to/target-repo` to `run`.

## Start From An Issue Directory

Prepare the Target Repository:

```bash
cd /path/to/target-repo
git switch -c feature/my-task-run
git status --short
```

Only the untracked Issue Directory should be dirty. Then start the Task Run from
this repo:

```bash
cd /home/boser/agent-control-plane
export EDITOR=nvim

pixi run task-control-run \
  /path/to/target-repo/.planning/issues/my-task-run
```

The command prints:

```text
Started Task Run: RUN-...
Run directory: /home/boser/agent-control-plane/runs/RUN-...
Task State: /home/boser/agent-control-plane/runs/RUN-.../task-state.json
First task context: /home/boser/agent-control-plane/runs/RUN-.../tasks/.../context.json
```

Resume with that run ID:

```bash
pixi run task-control-resume RUN-...
```

`resume` advances the active Task through planning, optional human answers, plan
approval, implementation, deterministic tests, review, repair loops, and commit.
Run the same command again after interruptions or plan-approval waits.

## Start From YAML

Use YAML when you need explicit test commands or run policy:

```yaml
target_repository: /path/to/target-repo
require_plan_approval: true
max_iterations: 10
codex:
  model: gpt-5
  effort: high
test_commands:
  - name: unit tests
    argv: ["pytest"]
tasks:
  - id: task-001
    title: Add batch runtime
    prompt: |
      Implement the batch runtime entrypoint.
```

Start it:

```bash
cd /home/boser/agent-control-plane
pixi run task-control-run path/to/task-spec.yaml
pixi run task-control-resume RUN-...
```

## Operational Rules

- Run commands from `/home/boser/agent-control-plane` so runtime state lands in
  this repo's gitignored `runs/` directory.
- Start from a clean Target Repository, except for an untracked Issue Directory
  used as the Task Source.
- The Controller creates one commit per completed Task in the Target Repository.
- Before each next Task, the Target Repository must be clean.
- The default Issue Directory import has no `test_commands`; use YAML for
  controller-run verification.
- Plan approval uses `$VISUAL` or `$EDITOR`; set one before `resume`.
- Do not edit `runs/<run-id>/task-state.json` by hand.

## Example

```bash
cd /home/boser/HyperliquidMomentum
git switch -c cross-sectional-samples-collapse
git status --short

cd /home/boser/agent-control-plane
export EDITOR=nvim

pixi run task-control-run \
  /home/boser/HyperliquidMomentum/.planning/issues/cross-sectional-samples-collapse

pixi run task-control-resume RUN-...
```
