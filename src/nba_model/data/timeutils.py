"""Timezone helpers — ET slate keying mirrors viewer/js/sports/nba.js etDateKey().

The US Eastern calendar date is the single source of truth for slate keying
(user-approved Phase 2 default). DST handled via the IANA tz database.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — zoneinfo is stdlib on 3.9+
    ET = None


def et_date_key(iso_utc) -> str | None:
    """Calendar date (YYYY-MM-DD) of an ISO-8601 timestamp, in US Eastern time."""
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ET is None:  # pragma: no cover
        return dt.astimezone(timezone.utc).date().isoformat()
    return dt.astimezone(ET).date().isoformat()


def parse_iso_utc(iso_utc) -> datetime | None:
    """ISO-8601 string -> aware UTC datetime, else None."""
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
