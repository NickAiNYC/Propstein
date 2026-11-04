"""Timestamp checks. Naive and missing values are rejected, not coerced."""

from __future__ import annotations

from datetime import datetime, timezone


class TimestampRejected(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse_timestamp(value: object, *, now: datetime, allow_future: bool) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TimestampRejected("missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimestampRejected("malformed") from exc
    if parsed.tzinfo is None:
        raise TimestampRejected("naive")
    parsed = parsed.astimezone(timezone.utc)
    if not allow_future and parsed > now:
        raise TimestampRejected("future")
    return parsed
