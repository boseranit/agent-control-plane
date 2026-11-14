from pathlib import Path

import pytest

from agent_control_plane.control_plane import systemd_scope as systemd_scope_module
from agent_control_plane.control_plane.systemd_scope import (
    ResourceBoundaryUnavailable,
    SystemdMemoryScope,
)


@pytest.mark.parametrize("maximum_memory_bytes", [0, -1, True, 1.5])
def test_scope_rejects_invalid_memory_limits(maximum_memory_bytes: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        SystemdMemoryScope.create(
            maximum_memory_bytes,  # type: ignore[arg-type]
            purpose="test",
        )


def test_scope_command_applies_one_aggregate_hard_limit() -> None:
    scope = SystemdMemoryScope(
        unit_name="acp-test.scope",
        maximum_memory_bytes=123456,
        systemd_run_path=Path("/usr/bin/systemd-run"),
        systemctl_path=Path("/usr/bin/systemctl"),
    )

    assert scope.command_argv(("python", "experiment.py")) == (
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--unit=acp-test.scope",
        "--property",
        "MemoryMax=123456",
        "--property",
        "MemorySwapMax=0",
        "--property",
        "OOMPolicy=kill",
        "--",
        "python",
        "experiment.py",
    )


def test_requested_scope_fails_closed_without_systemd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(systemd_scope_module.shutil, "which", lambda name: None)

    with pytest.raises(ResourceBoundaryUnavailable, match="require"):
        SystemdMemoryScope.create(123456, purpose="test")


def test_scope_stop_uses_bounded_control_group_kill_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = SystemdMemoryScope(
        unit_name="acp-test.scope",
        maximum_memory_bytes=123456,
        systemd_run_path=Path("/usr/bin/systemd-run"),
        systemctl_path=Path("/usr/bin/systemctl"),
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> object:
        calls.append((argv, kwargs))
        if "stop" in argv:
            raise systemd_scope_module.subprocess.TimeoutExpired(argv, timeout=5)
        return systemd_scope_module.subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(systemd_scope_module.subprocess, "run", fake_run)

    scope.stop()
    scope.cleanup()

    assert [call[0][2] for call in calls] == ["stop", "kill", "reset-failed"]
    assert calls[1][0][2:] == [
        "kill",
        "--kill-whom=all",
        "--signal=KILL",
        "acp-test.scope",
    ]
    assert all(call[1]["timeout"] == 5.0 for call in calls)
