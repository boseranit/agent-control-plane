from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any, TypeVar

T = TypeVar("T")
UsageLimitClock = Callable[[], datetime]
UsageLimitSleeper = Callable[[float], None]


@dataclass(frozen=True)
class UsageLimitEvent:
    role: str
    detected_at: datetime
    suggested_retry_at: datetime
    sleep_seconds: float
    message: str

    def to_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "detected_at": _format_runtime_timestamp(self.detected_at),
            "suggested_retry_at": _format_runtime_timestamp(self.suggested_retry_at),
            "sleep_seconds": self.sleep_seconds,
            "message": self.message,
        }


class UsageLimitWait(RuntimeError):
    def __init__(self, event: UsageLimitEvent) -> None:
        super().__init__(
            f"Usage limit persisted after retry; wait until "
            f"{_format_runtime_timestamp(event.suggested_retry_at)}."
        )
        self.event = event


def run_with_usage_limit_retry(
    *,
    role: str,
    run: Callable[[], T],
    record_wait: Callable[[UsageLimitEvent], None],
    clock: UsageLimitClock | None = None,
    sleep: UsageLimitSleeper | None = None,
) -> T:
    runtime_clock = clock or _local_runtime_now
    sleeper = sleep or time.sleep

    try:
        return run()
    except Exception as exc:
        now = _runtime_datetime(runtime_clock())
        event = usage_limit_event(role=role, exc=exc, now=now)
        if event is None:
            raise
        record_wait(event)
        sleeper(event.sleep_seconds)

    try:
        return run()
    except Exception as exc:
        now = _runtime_datetime(runtime_clock())
        event = usage_limit_event(role=role, exc=exc, now=now)
        if event is None:
            raise
        raise UsageLimitWait(event) from exc


def usage_limit_event(
    *, role: str, exc: Exception, now: datetime
) -> UsageLimitEvent | None:
    detected_at = _runtime_datetime(now)
    message = exception_message(exc)
    retry_at = usage_limit_retry_at(message, detected_at)
    if retry_at is None:
        return None
    return UsageLimitEvent(
        role=role,
        detected_at=detected_at,
        suggested_retry_at=retry_at,
        sleep_seconds=max((retry_at - detected_at).total_seconds(), 0.0),
        message=message,
    )


def usage_limit_retry_at(
    message_or_exc: str | Exception, now: datetime
) -> datetime | None:
    message = (
        exception_message(message_or_exc)
        if isinstance(message_or_exc, Exception)
        else message_or_exc
    )
    if not looks_like_usage_limit(message):
        return None
    return parse_retry_time(message, _runtime_datetime(now))


def looks_like_usage_limit(message: str) -> bool:
    normalized = message.lower()
    usage_markers = (
        "usage limit",
        "rate limit",
        "quota",
        "too many requests",
        "limit reached",
        "limit exceeded",
    )
    return any(marker in normalized for marker in usage_markers)


def parse_retry_time(message: str, now: datetime) -> datetime | None:
    runtime_now = _runtime_datetime(now)
    return (
        _parse_retry_after(message, runtime_now)
        or _parse_relative_retry_time(message, runtime_now)
        or _parse_absolute_retry_time(message, runtime_now)
        or _parse_time_of_day_retry_time(message, runtime_now)
    )


def exception_message(exc: Exception) -> str:
    message = str(exc)
    if message:
        return message
    if exc.args:
        return " ".join(str(arg) for arg in exc.args)
    return exc.__class__.__name__


def _parse_retry_after(message: str, now: datetime) -> datetime | None:
    retry_after_match = re.search(
        r"\bretry-after\s*[:=]\s*(?P<value>[^\s,;.]+)",
        message,
        flags=re.IGNORECASE,
    )
    if not retry_after_match:
        return None

    value = retry_after_match.group("value")
    try:
        return now + timedelta(seconds=float(value))
    except ValueError:
        return _parse_absolute_retry_time(value, now)


def _parse_relative_retry_time(message: str, now: datetime) -> datetime | None:
    relative_match = re.search(
        r"\b(?:in|after)\s+(?P<duration>(?:\d+(?:\.\d+)?\s*"
        r"(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)"
        r"(?:\s*(?:,|and)?\s*)?)+)",
        message,
        flags=re.IGNORECASE,
    )
    if not relative_match:
        return None

    seconds = 0.0
    for amount, unit in re.findall(
        r"(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)",
        relative_match.group("duration"),
        flags=re.IGNORECASE,
    ):
        seconds += float(amount) * _duration_unit_seconds(unit)

    if seconds <= 0:
        return None
    return now + timedelta(seconds=seconds)


def _duration_unit_seconds(unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"s", "sec", "secs", "second", "seconds"}:
        return 1.0
    if normalized in {"m", "min", "mins", "minute", "minutes"}:
        return 60.0
    if normalized in {"h", "hr", "hrs", "hour", "hours"}:
        return 60.0 * 60.0
    if normalized in {"d", "day", "days"}:
        return 60.0 * 60.0 * 24.0
    raise ValueError(f"Unknown usage-limit retry duration unit: {unit!r}.")


def _parse_absolute_retry_time(message: str, now: datetime) -> datetime | None:
    iso_match = re.search(
        r"\b(?P<date>\d{4}-\d{2}-\d{2})[ T]"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
        r"(?P<zone>\s*(?:Z|UTC|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if iso_match:
        zone = _normalized_datetime_zone(iso_match.group("zone"))
        timestamp = f"{iso_match.group('date')}T{iso_match.group('time')}{zone}"
        try:
            return _runtime_datetime(
                datetime.fromisoformat(timestamp),
                fallback_timezone=now.tzinfo,
            )
        except ValueError:
            return None

    month_match = re.search(
        r"\b(?P<timestamp>[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
        r"(?:,|\s+at)?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))\b",
        message,
        flags=re.IGNORECASE,
    )
    if not month_match:
        return None

    timestamp = re.sub(
        r"\s+at\s+",
        " ",
        month_match.group("timestamp").replace(",", ""),
        flags=re.IGNORECASE,
    )
    for format_string in (
        "%B %d %Y %I:%M:%S %p",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M:%S %p",
        "%b %d %Y %I:%M %p",
    ):
        try:
            parsed = datetime.strptime(timestamp, format_string)
        except ValueError:
            continue
        return parsed.replace(tzinfo=now.tzinfo)
    return None


def _parse_time_of_day_retry_time(message: str, now: datetime) -> datetime | None:
    time_match = re.search(
        r"\b(?:at|after)\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)"
        r"(?:\s*(?P<zone>UTC|Z|[+-]\d{2}:?\d{2}))?",
        message,
        flags=re.IGNORECASE,
    )
    if not time_match:
        return None

    time_text = _normalized_time_of_day(time_match.group("time"))
    for format_string in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(time_text, format_string)
        except ValueError:
            continue
        tz = _timezone_from_retry_suffix(time_match.group("zone"), now.tzinfo)
        retry_at = datetime.combine(now.date(), parsed.time(), tzinfo=tz)
        if retry_at <= now:
            retry_at += timedelta(days=1)
        return retry_at
    return None


def _normalized_datetime_zone(zone: str | None) -> str:
    if zone is None or not zone.strip():
        return ""
    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return "+00:00"
    if re.fullmatch(r"[+-]\d{4}", normalized):
        return f"{normalized[:3]}:{normalized[3:]}"
    return normalized


def _normalized_time_of_day(time_text: str) -> str:
    normalized = time_text.strip().upper().replace(".", "")
    return re.sub(r"(?<=\d)(AM|PM)$", r" \1", normalized)


def _timezone_from_retry_suffix(
    zone: str | None, fallback_timezone: tzinfo | None
) -> tzinfo:
    if zone is None or not zone.strip():
        return fallback_timezone or _local_runtime_now().tzinfo or UTC

    normalized = zone.strip().upper()
    if normalized in {"Z", "UTC"}:
        return UTC
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", normalized):
        offset = normalized.replace(":", "")
        sign = 1 if offset[0] == "+" else -1
        hours = int(offset[1:3])
        minutes = int(offset[3:5])
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return fallback_timezone or _local_runtime_now().tzinfo or UTC


def _runtime_datetime(
    value: datetime, *, fallback_timezone: tzinfo | None = None
) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    return value.replace(tzinfo=fallback_timezone or _local_runtime_now().tzinfo or UTC)


def _format_runtime_timestamp(value: datetime) -> str:
    return _runtime_datetime(value).isoformat()


def _local_runtime_now() -> datetime:
    return datetime.now().astimezone()
