from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_control_plane.control_plane.json_artifacts import append_jsonl, read_jsonl


def append_ledger_event(
    path: str | Path,
    *,
    event_type: str,
    research_run_id: str,
    **fields: Any,
) -> None:
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("Ledger event_type is required.")
    if not isinstance(research_run_id, str) or not research_run_id.strip():
        raise ValueError("Ledger research_run_id is required.")

    append_jsonl(
        path,
        {
            "event_type": event_type,
            "research_run_id": research_run_id,
            **fields,
        },
    )


def read_ledger_events(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(path)
