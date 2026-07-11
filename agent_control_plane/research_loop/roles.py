from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .runtime import ApprovalPolicy, RoleConfig, SandboxPolicy

ROLE_STRATEGIST = "strategist"
ROLE_IMPLEMENTER = "implementer"
ROLE_ADVERSARY = "adversary"

AGENTS_DIRNAME = "agents"


@dataclass(frozen=True)
class _RoleDefinition:
    prompt_file: str
    sandbox: SandboxPolicy
    approval: ApprovalPolicy


_ROLE_DEFINITIONS = {
    ROLE_STRATEGIST: _RoleDefinition(
        prompt_file="loop-strategist.md",
        sandbox=SandboxPolicy.READ_ONLY,
        approval=ApprovalPolicy.DENY_ALL,
    ),
    ROLE_IMPLEMENTER: _RoleDefinition(
        prompt_file="loop-implementer.md",
        sandbox=SandboxPolicy.WORKSPACE_WRITE,
        approval=ApprovalPolicy.AUTO_REVIEW,
    ),
    ROLE_ADVERSARY: _RoleDefinition(
        prompt_file="loop-adversary.md",
        sandbox=SandboxPolicy.READ_ONLY,
        approval=ApprovalPolicy.DENY_ALL,
    ),
}


def default_agents_dir() -> Path:
    return Path(__file__).resolve().parent / AGENTS_DIRNAME


def load_role_instructions(role: str, *, agents_dir: Optional[Path] = None) -> str:
    definition = _ROLE_DEFINITIONS[role]
    root = Path(agents_dir if agents_dir is not None else default_agents_dir())
    text = (root / definition.prompt_file).read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def role_config(
    role: str,
    *,
    cwd: str,
    model: str,
    reasoning_effort: str,
    output_schema: Optional[dict[str, Any]] = None,
    agents_dir: Optional[Path] = None,
) -> RoleConfig:
    definition = _ROLE_DEFINITIONS[role]
    return RoleConfig(
        role=role,
        cwd=cwd,
        developer_instructions=load_role_instructions(role, agents_dir=agents_dir),
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema=output_schema,
        sandbox=definition.sandbox,
        approval=definition.approval,
    )


def strategist_role_config(**kwargs) -> RoleConfig:
    return role_config(ROLE_STRATEGIST, **kwargs)


def implementer_role_config(**kwargs) -> RoleConfig:
    return role_config(ROLE_IMPLEMENTER, **kwargs)


def adversary_role_config(**kwargs) -> RoleConfig:
    return role_config(ROLE_ADVERSARY, **kwargs)
