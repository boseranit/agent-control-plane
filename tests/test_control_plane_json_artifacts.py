from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.control_plane.json_artifacts import (
    append_jsonl,
    build_hash_manifest,
    file_sha256,
    read_json_object,
    read_jsonl,
    verify_hash_manifest,
    write_json,
    write_text,
)


def test_write_and_read_json_object(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "artifact.json"

    write_json(path, {"b": 2, "a": 1})

    assert path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
    assert read_json_object(path) == {"a": 1, "b": 2}


def test_json_object_helpers_reject_invalid_payloads(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected JSON object"):
        write_json(tmp_path / "list.json", [1])  # type: ignore[arg-type]

    list_path = tmp_path / "list.json"
    list_path.write_text("[1]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected JSON object"):
        read_json_object(list_path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match=f"Malformed JSON.*{malformed_path}"):
        read_json_object(malformed_path)


def test_append_and_read_jsonl_events(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ledger.jsonl"

    assert read_jsonl(path) == []

    append_jsonl(path, {"b": 2, "a": 1})
    append_jsonl(path, {"event": "done"})
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == ('{"a":1,"b":2}\n{"event":"done"}\n\n')
    assert read_jsonl(path) == [{"a": 1, "b": 2}, {"event": "done"}]


def test_jsonl_rejects_invalid_events_with_line_context(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"

    with pytest.raises(ValueError, match="Expected JSON object"):
        append_jsonl(path, [1])  # type: ignore[arg-type]

    path.write_text('{"ok":true}\n[1]\n', encoding="utf-8")

    with pytest.raises(ValueError, match=f"Expected JSON object.*{path}.*line 2"):
        read_jsonl(path)

    path.write_text('{"ok":true}\n{\n', encoding="utf-8")

    with pytest.raises(ValueError, match=f"Malformed JSON.*{path}.*line 2"):
        read_jsonl(path)


def test_write_text_and_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "artifact.txt"

    write_text(path, "hello\n")

    assert path.read_text(encoding="utf-8") == "hello\n"
    assert file_sha256(path) == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


def test_hash_manifest_helpers_verify_locked_files(tmp_path: Path) -> None:
    first = tmp_path / "b.txt"
    second = tmp_path / "nested" / "a.txt"
    write_text(first, "first\n")
    write_text(second, "second\n")

    manifest = build_hash_manifest([first, second])

    assert manifest == {
        str(first.resolve()): file_sha256(first),
        str(second.resolve()): file_sha256(second),
    }
    verify_hash_manifest(manifest)

    write_text(first, "changed\n")

    with pytest.raises(ValueError, match=f"Hash mismatch.*{first.resolve()}"):
        verify_hash_manifest(manifest)

    first.unlink()

    with pytest.raises(ValueError, match=f"Missing file.*{first.resolve()}"):
        verify_hash_manifest(manifest)
