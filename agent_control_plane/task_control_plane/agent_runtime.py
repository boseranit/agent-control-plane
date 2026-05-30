from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import jsonschema
from agents import (
    Agent,
    AgentOutputSchemaBase,
    ApplyPatchOperation,
    ApplyPatchResult,
    ApplyPatchTool,
    ModelSettings,
    Runner,
    SQLiteSession,
    ShellCallOutcome,
    ShellCommandOutput,
    ShellResult,
    ShellTool,
    function_tool,
)
from agents.apply_diff import apply_diff
from agents.exceptions import ModelBehaviorError
from openai.types.shared import Reasoning

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


@dataclass(frozen=True)
class AgentTurnResult:
    final_response: Any


class AgentRuntime:
    def __init__(
        self,
        *,
        thread_id_factory: Callable[[AgentRole], str] | None = None,
        session_db_path: str | Path | None = None,
    ) -> None:
        self._thread_id_factory = thread_id_factory or _new_thread_id
        self._session_db_path = Path(session_db_path) if session_db_path else None

    def __enter__(self) -> AgentRuntime:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def open_thread(self, config: AgentRunConfig) -> AgentThread:
        thread_id = config.thread_id or self._thread_id_factory(config.role)
        session_db_path = (
            Path(config.session_db_path)
            if config.session_db_path is not None
            else self._session_db_path or _default_session_db_path()
        )
        return AgentThread(
            thread_id=thread_id,
            role=config.role,
            cwd=Path(config.cwd).resolve(),
            developer_instructions=config.developer_instructions or "",
            model=config.model,
            session_db_path=session_db_path,
        )


class AgentThread:
    def __init__(
        self,
        *,
        thread_id: str,
        role: AgentRole,
        cwd: Path,
        developer_instructions: str,
        model: str | None,
        session_db_path: Path,
    ) -> None:
        self.id = thread_id
        self._role = role
        self._cwd = cwd
        self._developer_instructions = developer_instructions
        self._model = model
        self._session_db_path = session_db_path

    def run(self, input: str, config: AgentRunConfig) -> AgentTurnResult:
        model = config.model or self._model
        session = SQLiteSession(self.id, self._session_db_path)
        agent = Agent(
            name=f"task-control-{config.role}",
            instructions=_instructions(self._developer_instructions, config),
            model=model,
            model_settings=_model_settings(config.effort),
            output_type=(
                _JsonSchemaOutput(config.output_schema)
                if config.output_schema is not None
                else None
            ),
            tools=_tools_for_role(config.role, Path(config.cwd).resolve()),
        )
        result = Runner.run_sync(
            agent,
            input,
            session=session,
            run_config=None,
        )
        close = getattr(session, "close", None)
        if close is not None:
            close()
        return AgentTurnResult(final_response=_final_response(result.final_output))


class _JsonSchemaOutput(AgentOutputSchemaBase):
    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = dict(schema)

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        title = self._schema.get("title")
        return title if isinstance(title, str) and title else "JsonObject"

    def json_schema(self) -> dict[str, Any]:
        return dict(self._schema)

    def is_strict_json_schema(self) -> bool:
        return False

    def validate_json(self, json_str: str) -> Any:
        try:
            parsed = json.loads(json_str)
            jsonschema.Draft202012Validator(self._schema).validate(parsed)
        except Exception as exc:
            raise ModelBehaviorError("Agent returned invalid structured JSON.") from exc
        return parsed


class _WorkspacePatchEditor:
    def __init__(self, root: Path) -> None:
        self._root = root

    def create_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        path = self._path(operation.path)
        if operation.diff is None:
            return ApplyPatchResult(status="failed", output="Missing diff.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(apply_diff("", operation.diff, mode="create"), encoding="utf-8")
        return ApplyPatchResult(status="completed", output=f"Created {operation.path}")

    def update_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        path = self._path(operation.path)
        if operation.diff is None:
            return ApplyPatchResult(status="failed", output="Missing diff.")
        original = path.read_text(encoding="utf-8")
        updated = apply_diff(original, operation.diff)
        if operation.move_to:
            destination = self._path(operation.move_to)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(updated, encoding="utf-8")
            if destination != path:
                path.unlink()
            return ApplyPatchResult(
                status="completed",
                output=f"Moved {operation.path} to {operation.move_to}",
            )
        path.write_text(updated, encoding="utf-8")
        return ApplyPatchResult(status="completed", output=f"Updated {operation.path}")

    def delete_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        path = self._path(operation.path)
        path.unlink()
        return ApplyPatchResult(status="completed", output=f"Deleted {operation.path}")

    def _path(self, path: str) -> Path:
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc
        return resolved


def _tools_for_role(role: AgentRole, cwd: Path) -> list[Any]:
    tools: list[Any] = _read_tools(cwd)
    if role == "implementer":
        tools.extend(
            [
                ShellTool(
                    executor=_shell_executor(cwd),
                    environment={"type": "local"},
                    needs_approval=False,
                ),
                ApplyPatchTool(
                    editor=_WorkspacePatchEditor(cwd),
                    needs_approval=False,
                ),
            ]
        )
    return tools


def _read_tools(cwd: Path) -> list[Any]:
    root = cwd.resolve()

    def workspace_path(path: str) -> Path:
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc
        return resolved

    @function_tool
    def read_file(
        path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        """Read a UTF-8 text file from the target repository."""
        lines = workspace_path(path).read_text(encoding="utf-8").splitlines()
        start = max((start_line or 1) - 1, 0)
        end = end_line if end_line is not None else len(lines)
        return "\n".join(lines[start:end])

    @function_tool
    def list_files() -> str:
        """List files tracked or visible under the target repository."""
        result = subprocess.run(
            ["rg", "--files"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return "\n".join(
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )

    @function_tool
    def search_text(
        pattern: str, path: str | None = None, max_matches: int = 100
    ) -> str:
        """Search target repository text with ripgrep."""
        args = ["rg", "-n", "--", pattern]
        if path:
            args.append(str(workspace_path(path).relative_to(root)))
        result = subprocess.run(
            args,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        output = result.stdout if result.stdout else result.stderr
        return "\n".join(output.splitlines()[:max_matches])

    return [read_file, list_files, search_text]


def _shell_executor(cwd: Path) -> Callable[[Any], ShellResult]:
    def run(request: Any) -> ShellResult:
        outputs: list[ShellCommandOutput] = []
        action = request.data.action
        timeout = (action.timeout_ms or 120_000) / 1000
        max_output_length = action.max_output_length
        for command in action.commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                outputs.append(
                    ShellCommandOutput(
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        command=command,
                        outcome=ShellCallOutcome(
                            type="exit",
                            exit_code=completed.returncode,
                        ),
                    )
                )
            except subprocess.TimeoutExpired as exc:
                outputs.append(
                    ShellCommandOutput(
                        stdout=exc.stdout or "",
                        stderr=exc.stderr or "",
                        command=command,
                        outcome=ShellCallOutcome(type="timeout", exit_code=None),
                    )
                )
        return ShellResult(output=outputs, max_output_length=max_output_length)

    return run


def _instructions(developer_instructions: str, config: AgentRunConfig) -> str:
    schema_note = ""
    if config.output_schema is not None:
        schema_note = "\n\nReturn only JSON matching this schema:\n" + json.dumps(
            config.output_schema,
            indent=2,
            sort_keys=True,
        )
    role_note = (
        "\n\nRepository tools are constrained by role. "
        "Planner, context, and reviewer tools are read-only. "
        "Implementer tools may edit files under the target repository."
    )
    return f"{developer_instructions}{role_note}{schema_note}"


def _model_settings(effort: str | None) -> ModelSettings:
    if effort is None:
        return ModelSettings()
    return ModelSettings(reasoning=cast(Reasoning, {"effort": effort}))


def _final_response(final_output: Any) -> Any:
    if isinstance(final_output, str):
        return final_output
    return json.dumps(final_output)


def _new_thread_id(role: AgentRole) -> str:
    return f"{role}-{uuid.uuid4().hex}"


def _default_session_db_path() -> Path:
    return Path(tempfile.gettempdir()) / "agent-control-plane-agent-sessions.sqlite3"
