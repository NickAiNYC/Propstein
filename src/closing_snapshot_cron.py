"""
closing_snapshot_cron.py — Pre-Kickoff Stage A Closing Line Lock Engine

Identifies upcoming games approaching kickoff (within T-5 minutes),
freezes the market closing line (both Over and Under odds for proper de-vigging),
computes deterministic RFC-8785 hashes, and records immutable closing snapshots.
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.crypto_utils import canonical_json_sha256
from src.settlement_engine import compute_entry_clv, devig_two_way_market
KICKOFF_LOCK_WINDOW_SEC = 300   # T-5 minutes before kickoff
MAX_QUOTE_STALENESS_SEC = 90    # Maximum age of quote to be accepted as close


def ensure_closing_schema(db_conn, is_postgres: bool = True):
    """Ensures closing_snapshots table exists."""
    with db_conn.cursor() if is_postgres else db_conn as cur:
        if is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS closing_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    event_id VARCHAR(255) NOT NULL,
                    player_id VARCHAR(255) NOT NULL,
                    book VARCHAR(100) NOT NULL,
                    market VARCHAR(100) NOT NULL,
                    closing_line DOUBLE PRECISION NOT NULL,
                    closing_over_odds INT NOT NULL,
                    closing_under_odds INT NOT NULL,
                    closing_de_vig_over_prob DOUBLE PRECISION NOT NULL,
                    closing_de_vig_under_prob DOUBLE PRECISION NOT NULL,
                    closing_fair_line DOUBLE PRECISION NOT NULL,
                    provider_event_id VARCHAR(255) NOT NULL,
                    provider_update_ts BIGINT NOT NULL,
                    raw_provider_payload_sha256 CHAR(64) NOT NULL,
                    closing_snapshot_sha256 CHAR(64) NOT NULL,
                    kickoff_at TIMESTAMPTZ,
                    captured_at TIMESTAMPTZ,
                    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (event_id, player_id, book, market)
                );
                CREATE INDEX IF NOT EXISTS idx_closing_lookup ON closing_snapshots(event_id, player_id, book, market);
            """)
            # These two fields exist so a later reader can prove captured_at < kickoff_at.
            # New locks only. Do not backfill existing rows.
            cur.execute("""
                ALTER TABLE closing_snapshots
                    ADD COLUMN IF NOT EXISTS kickoff_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ;
            """)
        else:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS closing_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    book TEXT NOT NULL,
                    market TEXT NOT NULL,
                    closing_line REAL NOT NULL,
                    closing_over_odds INTEGER NOT NULL,
                    closing_under_odds INTEGER NOT NULL,
                    closing_de_vig_over_prob REAL NOT NULL,
                    closing_de_vig_under_prob REAL NOT NULL,
                    closing_fair_line REAL NOT NULL,
                    provider_event_id TEXT NOT NULL,
                    provider_update_ts INTEGER NOT NULL,
                    raw_provider_payload_sha256 TEXT NOT NULL,
                    closing_snapshot_sha256 TEXT NOT NULL,
                    kickoff_at TEXT,
                    captured_at TEXT,
                    locked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (event_id, player_id, book, market)
                );
                CREATE INDEX IF NOT EXISTS idx_closing_lookup ON closing_snapshots(event_id, player_id, book, market);
            """)


def utc_z(value: datetime) -> str:
    """Second-precision UTC. Naive datetimes are not a proof."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def prove_close_times(
    game_kickoff_ts: int,
    provider_update_ts: int,
    locked_at: datetime,
) -> Optional[tuple[datetime, datetime]]:
    """These two fields exist so a later reader can prove captured_at < kickoff_at."""
    kickoff_at = datetime.fromtimestamp(int(game_kickoff_ts), tz=timezone.utc).replace(microsecond=0)
    locked_at = locked_at.astimezone(timezone.utc).replace(microsecond=0)
    provider_at = datetime.fromtimestamp(int(provider_update_ts) / 1000.0, tz=timezone.utc).replace(microsecond=0)
    earliest = locked_at - timedelta(seconds=MAX_QUOTE_STALENESS_SEC)
    if earliest <= provider_at < locked_at and provider_at < kickoff_at:
        captured_at = provider_at
    elif locked_at < kickoff_at:
        captured_at = locked_at
    else:
        return None
    if not captured_at < kickoff_at:
        return None
    return captured_at, kickoff_at


def closing_receipt_payload(row: Dict[str, Any], captured_at: str, kickoff_at: str) -> Dict[str, Any]:
    """Hash input for a new lock. Both timestamps are inside the receipt."""
    line = row["closing_line"] if "closing_line" in row else row["book_line"]
    over = row["closing_over_odds"] if "closing_over_odds" in row else row["over_odds"]
    under = row["closing_under_odds"] if "closing_under_odds" in row else row["under_odds"]
    fair = row["closing_fair_line"] if "closing_fair_line" in row else row["fair_line"]
    raw = row["raw_provider_payload_sha256"] if "raw_provider_payload_sha256" in row else row["raw_payload_sha256"]
    return {
        "schema": "propwire.closing_snapshot.v1",
        "event_id": row["event_id"],
        "player_id": row["player_id"],
        "book": row["book"],
        "market": row["market"],
        "closing_line": float(line),
        "closing_over_odds": int(over),
        "closing_under_odds": int(under),
        "closing_fair_line": float(fair),
        "provider_event_id": row["provider_event_id"],
        "provider_update_ts": int(row["provider_update_ts"]),
        "raw_provider_payload_sha256": raw,
        "captured_at": captured_at,
        "kickoff_at": kickoff_at,
    }


def lock_imminent_closing_snapshots_postgres(db_conn) -> Dict[str, int]:
    """Locks T-0 closing snapshots in Postgres. Does not update existing rows."""
    ensure_closing_schema(db_conn, is_postgres=True)
    locked_count = 0

    with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT q.event_id, q.player_id, q.book, q.market, q.book_line,
                   q.over_odds, q.under_odds, q.fair_line, q.provider_event_id,
                   q.provider_update_ts, q.raw_payload_sha256, q.game_kickoff_ts
            FROM latest_market_quotes q
            LEFT JOIN closing_snapshots c
              ON q.event_id = c.event_id
             AND q.player_id = c.player_id
             AND q.book = c.book
             AND q.market = c.market
            WHERE c.id IS NULL
              AND q.game_status = 'upcoming'
              AND q.line_type = 'main'
              AND q.edge_pct <= 12.0
              AND q.game_kickoff_ts <= (EXTRACT(EPOCH FROM NOW())::BIGINT + %s)
              AND q.game_kickoff_ts > EXTRACT(EPOCH FROM NOW())::BIGINT
              AND (EXTRACT(EPOCH FROM NOW())::BIGINT - (q.provider_update_ts / 1000)) <= %s;
        """, (KICKOFF_LOCK_WINDOW_SEC, MAX_QUOTE_STALENESS_SEC))
        candidates = cur.fetchall()

        for row in candidates:
            proved = prove_close_times(
                int(row["game_kickoff_ts"]),
                int(row["provider_update_ts"]),
                datetime.now(timezone.utc),
            )
            if proved is None:
                continue
            captured_at, kickoff_at = proved
            captured_text = utc_z(captured_at)
            kickoff_text = utc_z(kickoff_at)
            devig = devig_two_way_market(row["over_odds"], row["under_odds"])
            canonical_close_payload = closing_receipt_payload(row, captured_text, kickoff_text)
            snapshot_hash = canonical_json_sha256(canonical_close_payload)

            cur.execute("SAVEPOINT sp_closing_lock;")
            try:
                cur.execute("""
                    INSERT INTO closing_snapshots (
                        event_id, player_id, book, market, closing_line,
                        closing_over_odds, closing_under_odds,
                        closing_de_vig_over_prob, closing_de_vig_under_prob,
                        closing_fair_line, provider_event_id, provider_update_ts,
                        raw_provider_payload_sha256, closing_snapshot_sha256,
                        kickoff_at, captured_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id, player_id, book, market) DO NOTHING;
                """, (
                    row["event_id"], row["player_id"], row["book"], row["market"],
                    row["book_line"], row["over_odds"], row["under_odds"],
                    devig["over_prob"], devig["under_prob"], row["fair_line"],
                    row["provider_event_id"], row["provider_update_ts"],
                    row["raw_payload_sha256"], snapshot_hash,
                    kickoff_at, captured_at,
                ))
                locked_count += 1
                cur.execute("RELEASE SAVEPOINT sp_closing_lock;")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_closing_lock;")
                continue

        db_conn.commit()

    return {"locked_snapshots": locked_count}


def lock_imminent_closing_snapshots_sqlite(conn) -> Dict[str, int]:
    """Locks T-0 closing snapshots in local SQLite fallback."""
    ensure_closing_schema(conn, is_postgres=False)
    # No game_kickoff_ts on this path. Do not invent kickoff_at or captured_at.
    locked_count = 0
    cur = conn.cursor()
    # Check if we have sample market edges to snapshot
    cur.execute("SELECT slateId, playerId, playerName, market, bookLine, odds, fairLine FROM MarketEdge LIMIT 20")
    rows = cur.fetchall()
    now_ms = int(time.time() * 1000)

    for r in rows:
        slate_id, p_id, p_name, mkt, b_line, odds, f_line = r
        devig = devig_two_way_market(int(odds), -115)
        raw_hash = canonical_json_sha256({"raw": f"{slate_id}_{p_id}_{b_line}_{now_ms}"})
        canonical_close = {
            "schema": "propwire.closing_snapshot.v1",
            "event_id": f"evt_{slate_id}",
            "player_id": str(p_id),
            "book": "Bovada",
            "market": str(mkt),
            "closing_line": float(b_line),
            "closing_over_odds": int(odds),
            "closing_under_odds": -115,
            "closing_fair_line": float(f_line),
            "provider_event_id": f"pvd_{slate_id}",
            "provider_update_ts": now_ms,
            "raw_provider_payload_sha256": raw_hash,
        }
        snap_hash = canonical_json_sha256(canonical_close)
        try:
            cur.execute("""
                INSERT OR IGNORE INTO closing_snapshots (
                    event_id, player_id, book, market, closing_line,
                    closing_over_odds, closing_under_odds,
                    closing_de_vig_over_prob, closing_de_vig_under_prob,
                    closing_fair_line, provider_event_id, provider_update_ts,
                    raw_provider_payload_sha256, closing_snapshot_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"evt_{slate_id}", str(p_id), "Bovada", str(mkt),
                float(b_line), int(odds), -115,
                devig["over_prob"], devig["under_prob"], float(f_line),
                f"pvd_{slate_id}", now_ms, raw_hash, snap_hash
            ))
            locked_count += 1
        except Exception:
            continue

    conn.commit()
    return {"locked_snapshots": locked_count}


def run_stage_a_lock() -> Dict[str, int]:
    """Single-pass Stage A lock execution."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required to lock observed closing quotes")
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 is required to lock observed closing quotes")
    with psycopg2.connect(db_url) as conn:
        result = lock_imminent_closing_snapshots_postgres(conn)
    print(f"[Stage A Cron] Locked {result['locked_snapshots']} closing snapshots in Postgres.")
    return result


if __name__ == "__main__":
    run_stage_a_lock()
