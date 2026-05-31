from __future__ import annotations

from datetime import datetime

import pytest

from agent_control_plane.control_plane.usage_limit import (
    UsageLimitWait,
    run_with_usage_limit_retry,
    usage_limit_retry_at,
)


def test_usage_limit_runner_records_wait_sleeps_and_retries_once() -> None:
    attempts = 0
    sleeps: list[float] = []
    waits: list[object] = []

    def run() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Rate limit exceeded. retry-after: 2")
        return "ok"

    result = run_with_usage_limit_retry(
        role="strategist",
        run=run,
        record_wait=waits.append,
        clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == [2.0]
    assert attempts == 2
    wait = waits[0]
    assert wait.role == "strategist"
    assert wait.sleep_seconds == 2.0
    assert wait.suggested_retry_at.isoformat() == "2026-05-27T14:00:02+10:00"
    assert "Rate limit" in wait.message


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Usage limit reached. retry-after=90",
            "2026-05-27T14:01:30+10:00",
        ),
        (
            "Quota exhausted. Please retry after 1 hour and 30 minutes.",
            "2026-05-27T15:30:00+10:00",
        ),
        (
            "Too many requests. Please try again at 2026-05-27T14:05:00.",
            "2026-05-27T14:05:00+10:00",
        ),
        (
            "Rate limit hit. Please try again at 2026-05-27 04:05 UTC.",
            "2026-05-27T04:05:00+00:00",
        ),
        (
            "Usage limit reached. Please try again at 2:05 PM.",
            "2026-05-27T14:05:00+10:00",
        ),
    ],
)
def test_usage_limit_parser_handles_retry_forms(
    message: str, expected: str
) -> None:
    retry_at = usage_limit_retry_at(
        message,
        datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
    )

    assert retry_at is not None
    assert retry_at.isoformat() == expected


def test_usage_limit_parser_ignores_non_usage_messages() -> None:
    retry_at = usage_limit_retry_at(
        "Transport failed. Please try again at 2026-05-27T14:05:00+10:00.",
        datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
    )

    assert retry_at is None


def test_usage_limit_runner_never_sleeps_negative_seconds() -> None:
    attempts = 0
    sleeps: list[float] = []
    waits: list[object] = []

    def run() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(
                "Usage limit reached. Please try again at "
                "2026-05-27T13:59:30+10:00."
            )
        return "ok"

    result = run_with_usage_limit_retry(
        role="implementer",
        run=run,
        record_wait=waits.append,
        clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == [0.0]
    assert waits[0].sleep_seconds == 0.0


def test_usage_limit_runner_raises_usage_limit_wait_on_second_limit() -> None:
    attempts = 0
    sleeps: list[float] = []
    waits: list[object] = []

    def run() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Usage limit reached. retry-after: 5")

    with pytest.raises(UsageLimitWait) as exc_info:
        run_with_usage_limit_retry(
            role="critic",
            run=run,
            record_wait=waits.append,
            clock=lambda: datetime.fromisoformat("2026-05-27T14:00:00+10:00"),
            sleep=sleeps.append,
        )

    assert attempts == 2
    assert sleeps == [5.0]
    assert len(waits) == 1
    assert exc_info.value.event.role == "critic"
    assert exc_info.value.event.sleep_seconds == 5.0
