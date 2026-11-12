#!/usr/bin/env python3
"""Emit one proved close-tape line, or refuse.

Required object: player_id, market, book, line, captured_at, kickoff_at,
receipt_sha256. captured_at must be strictly before kickoff_at. The receipt
is the stored closing_snapshot_sha256 and must match the canonical payload
that includes both timestamps.

No DATABASE_URL, missing columns, an empty table, or no matching receipt:
print the refusal and exit 0. Never invents a timestamp. Does not update
historical rows and does not write snapshots/close_tape.jsonl.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MESSAGE = "No close tape source that can prove captured_at < kickoff_at"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
COLUMNS = (
    "event_id", "player_id", "book", "market", "closing_line",
    "closing_over_odds", "closing_under_odds", "closing_fair_line",
    "provider_event_id", "provider_update_ts", "raw_provider_payload_sha256",
    "closing_snapshot_sha256", "captured_at", "kickoff_at",
)


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_line(conn) -> str | None:
    from src.closing_snapshot_cron import closing_receipt_payload
    from src.crypto_utils import canonical_json_sha256

    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'closing_snapshots'
              AND column_name IN ('kickoff_at', 'captured_at')
        """)
        found = {row[0] for row in cur.fetchall()}
        if found != {"kickoff_at", "captured_at"}:
            return None
        cur.execute("""
            SELECT event_id, player_id, book, market, closing_line,
                   closing_over_odds, closing_under_odds, closing_fair_line,
                   provider_event_id, provider_update_ts, raw_provider_payload_sha256,
                   closing_snapshot_sha256, captured_at, kickoff_at
            FROM closing_snapshots
            WHERE captured_at IS NOT NULL
              AND kickoff_at IS NOT NULL
              AND captured_at < kickoff_at
            ORDER BY captured_at DESC
        """)
        rows = cur.fetchall()
    for raw in rows:
        row = dict(zip(COLUMNS, raw))
        captured = _iso(row["captured_at"])
        kickoff = _iso(row["kickoff_at"])
        receipt = row["closing_snapshot_sha256"]
        if not captured or not kickoff or not (captured < kickoff):
            continue
        if not isinstance(receipt, str) or HEX64.match(receipt) is None:
            continue
        payload = closing_receipt_payload(row, captured, kickoff)
        if canonical_json_sha256(payload) != receipt:
            continue
        return json.dumps({
            "player_id": row["player_id"],
            "market": row["market"],
            "book": row["book"],
            "line": float(row["closing_line"]),
            "captured_at": captured,
            "kickoff_at": kickoff,
            "receipt_sha256": receipt,
        }, separators=(",", ":"))
    return None


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print(MESSAGE)
        return 0
    try:
        import psycopg2
    except ImportError:
        print(MESSAGE)
        return 0
    try:
        with psycopg2.connect(url) as conn:
            conn.set_session(readonly=True, autocommit=True)
            line = _one_line(conn)
    except Exception:
        print(MESSAGE)
        return 0
    print(line if line else MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
