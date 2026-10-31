#!/usr/bin/env python3
"""Fail a scheduled odds job when an active NFL slate has a stale feed."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def check(viewer: Path = VIEWER, now: datetime | None = None,
          max_age_hours: float = 6.0) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("current time has no timezone")
    now = now.astimezone(timezone.utc)
    index = json.loads((viewer / "feeds/slate-index.json").read_text())
    nfl = index["sports"]["nfl"]
    slate = nfl["slates"][nfl["default_slate"]]
    games = json.loads((viewer / slate["games"]).read_text())
    today_et = now.astimezone(ZoneInfo("America/New_York")).date()
    active = any(-1 <= (datetime.fromisoformat(game["gameday"]).date() - today_et).days <= 7
                 for game in games)
    if not active:
        return "No NFL game within the active seven-day window; odds alarm skipped."

    feed_path = viewer / "live_odds_feed.json"
    feed_bytes = feed_path.read_bytes()
    feed = json.loads(feed_bytes)
    manifest = json.loads((viewer / "live_odds_feed.manifest.json").read_text())
    actual_hash = hashlib.sha256(feed_bytes).hexdigest()
    if manifest.get("sha256") != actual_hash or manifest.get("status") != "PASS_ATOMIC_PUBLISHED":
        raise ValueError("odds feed does not match its passing provenance manifest")
    if feed.get("feed_status") != "LIVE_POLYMARKET_CLOB_UNVERIFIED":
        raise ValueError("odds feed has no current Polymarket CLOB status")
    if int(feed.get("polymarket_quotes_count") or 0) < 1:
        raise ValueError("odds feed has no observed Polymarket quotes")
    age_hours = (now - parse_time(feed["updated_at"])).total_seconds() / 3600
    if age_hours < -5 / 60:
        raise ValueError(f"odds feed timestamp is in the future by {-age_hours:.2f} hours")
    if age_hours > max_age_hours:
        raise ValueError(f"odds feed is {age_hours:.2f} hours old (limit {max_age_hours:g} hours)")
    return f"Odds feed age {max(0, age_hours):.2f} hours; manifest hash matches; source remains unverified."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", type=Path, default=VIEWER)
    parser.add_argument("--max-age-hours", type=float, default=6.0)
    args = parser.parse_args()
    try:
        print(check(args.viewer, max_age_hours=args.max_age_hours))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ODDS FRESHNESS ALARM: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
