from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"Expected JSON object for {Path(path)}")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {source}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {source}")
    return data


def append_jsonl(path: str | Path, data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"Expected JSON object for {Path(path)}")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []

    events: list[dict[str, Any]] = []
    with source.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed JSON in {source} line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(event, dict):
                raise ValueError(f"Expected JSON object in {source} line {line_number}")
            events.append(event)
    return events


def write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_hash_manifest(paths: Iterable[str | Path]) -> dict[str, str]:
    return {
        str(path.resolve()): file_sha256(path)
        for path in sorted(
            (Path(item) for item in paths), key=lambda item: str(item.resolve())
        )
    }


def verify_hash_manifest(manifest: Mapping[str, str]) -> None:
    for path_string, expected_hash in manifest.items():
        path = Path(path_string)
        if not path.exists():
            raise ValueError(f"Missing file in hash manifest: {path}")
        actual_hash = file_sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Hash mismatch for {path}: expected {expected_hash}, got {actual_hash}"
            )
