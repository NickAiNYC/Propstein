#!/usr/bin/env python3
"""
ingest_edges.py — Direct Postgres Ingestion Pipeline for PropWire Market Edges

Reads:
  1. snapshots_<slate>.jsonl (latest live snapshots)
  2. clv_audit_report.json (settlement / CLV audit metrics)

Merges on (player_name/id + market) and executes a high-speed bulk upsert into the
Postgres "MarketEdge" table via psycopg2.execute_values.

Supports both:
  - Direct Postgres (Supabase, Neon, Railway, RDS)
  - SQLite fallback if DATABASE_URL is not set or unavailable locally, ensuring zero
    pipeline halts during local development/offline testing.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def normalize_key(name: str, market: str) -> str:
    """Creates a normalized lookup key matching player name and market."""
    clean_name = name.lower().replace(".", "").replace("'", "").replace("-", " ").strip()
    clean_market = market.lower().replace("-", "_").replace(" ", "_").strip()
    return f"{clean_name}::{clean_market}"


def parse_market_label(m: Optional[str]) -> str:
    """Normalize market names to consistent display strings."""
    if not m:
        return "Receiving Yards"
    m_low = str(m).lower()
    if "rec_yds" in m_low or "receiving_yards" in m_low:
        return "Receiving Yards"
    if "reception" in m_low:
        return "Receptions"
    if "td" in m_low or "touchdown" in m_low:
        return "Anytime Touchdown"
    return str(m).replace("_", " ").title()


def extract_edges_from_sources(
    slate_id: str,
    snapshot_path: Path,
    clv_path: Optional[Path] = None,
    live_feed_path: Optional[Path] = None,
) -> List[Tuple[Any, ...]]:
    """
    Extracts, merges, and normalizes edge records into tuple format:
    (slateId, playerId, playerName, market, bookLine, odds, fairLine, edgePct)
    """
    # 1. Load CLV / Settlement report if available
    clv_lookup: Dict[str, Dict[str, Any]] = {}
    if clv_path and clv_path.exists():
        try:
            clv_raw = json.loads(clv_path.read_text(encoding="utf-8"))
            records = clv_raw.get("records", []) if isinstance(clv_raw, dict) else clv_raw
            for rec in records:
                p_name = rec.get("player") or rec.get("player_name", "")
                mkt = rec.get("market", "receiving_yards")
                if p_name:
                    k = normalize_key(p_name, mkt)
                    clv_lookup[k] = rec
        except Exception as e:
            print(f"[ingest_edges] Notice: could not parse CLV file {clv_path}: {e}")

    rows_by_key: Dict[str, Tuple[Any, ...]] = {}

    # 2. Ingest from snapshot JSONL (latest state)
    if snapshot_path.exists():
        with open(snapshot_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                except Exception:
                    continue

                player_id = snap.get("player_id") or snap.get("player", "unknown")
                player_name = snap.get("player_name") or snap.get("player")
                market = snap.get("market", "receiving_yards")
                if not player_name:
                    continue

                quote = snap.get("quote", {})
                eval_data = quote.get("evaluation") if isinstance(quote, dict) else {}
                proj = snap.get("projection", {})

                # Extract line, odds, fair_line, edge
                book_line = quote.get("line") if isinstance(quote, dict) else snap.get("line")
                if book_line is None:
                    continue

                odds = quote.get("over_odds") or quote.get("odds") or snap.get("odds", -110)
                fair_line = proj.get("fair_line") or snap.get("fair_line") or book_line

                edge_pct = 0.0
                if eval_data and "prob_edge" in eval_data:
                    edge_pct = float(eval_data["prob_edge"]) * 100.0
                elif "edge" in snap:
                    edge_pct = float(snap["edge"]) * (100.0 if abs(float(snap["edge"])) <= 1.0 else 1.0)

                # Merge CLV audit if available
                lookup_key = normalize_key(player_name, market)
                if lookup_key in clv_lookup:
                    audit = clv_lookup[lookup_key]
                    if audit.get("clv_prob_pct") is not None:
                        # Use verified CLV delta if available
                        edge_pct = max(edge_pct, float(audit["clv_prob_pct"]))
                    if audit.get("close_line") is not None:
                        fair_line = float(audit["close_line"])

                clean_market = parse_market_label(market)
                row_tuple = (
                    slate_id,
                    str(player_id),
                    str(player_name),
                    clean_market,
                    float(book_line),
                    int(odds) if odds is not None else -110,
                    float(fair_line),
                    round(float(edge_pct), 2),
                )
                rows_by_key[f"{player_name}::{clean_market}"] = row_tuple

    # 3. Optional fallback: If snapshot has fewer rows, supplement with live_feed_path
    if live_feed_path and live_feed_path.exists():
        try:
            feed = json.loads(live_feed_path.read_text(encoding="utf-8"))
            for item in feed.get("quotes", []):
                p_name = item.get("player")
                if not p_name:
                    continue
                mkt = parse_market_label(item.get("market", "receiving_yards"))
                k = f"{p_name}::{mkt}"
                if k not in rows_by_key and item.get("line") is not None:
                    ev = item.get("evaluation", {})
                    edge_val = ev.get("prob_edge", 0.0) * 100.0
                    p_id = item.get("player_id") or str(p_name).lower().replace(" ", "_")
                    row_tuple = (
                        slate_id,
                        str(p_id),
                        str(p_name),
                        mkt,
                        float(item["line"]),
                        int(item.get("over_odds", -110)),
                        float(item.get("fair_line", item["line"])),
                        round(float(edge_val), 2),
                    )
                    rows_by_key[k] = row_tuple
        except Exception as e:
            print(f"[ingest_edges] Notice: live feed supplement skipped: {e}")

    return list(rows_by_key.values())


def upsert_to_postgres(database_url: str, edges: List[Tuple[Any, ...]]) -> int:
    """Upserts edge records into PostgreSQL table MarketEdge using psycopg2."""
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 is not installed. Please install psycopg2-binary.")

    schema_sql = """
    CREATE TABLE IF NOT EXISTS "MarketEdge" (
        "id" TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
        "slateId" TEXT NOT NULL,
        "playerId" TEXT NOT NULL,
        "playerName" TEXT NOT NULL,
        "market" TEXT NOT NULL,
        "bookLine" DOUBLE PRECISION NOT NULL,
        "odds" INTEGER NOT NULL,
        "fairLine" DOUBLE PRECISION NOT NULL,
        "edgePct" DOUBLE PRECISION NOT NULL,
        "updatedAt" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT "MarketEdge_slate_player_market_key" UNIQUE ("slateId", "playerId", "market")
    );
    CREATE INDEX IF NOT EXISTS "MarketEdge_edgePct_idx" ON "MarketEdge" ("edgePct" DESC);
    CREATE INDEX IF NOT EXISTS "MarketEdge_slateId_idx" ON "MarketEdge" ("slateId");
    """

    upsert_sql = """
    INSERT INTO "MarketEdge" (
        "slateId", "playerId", "playerName", "market",
        "bookLine", "odds", "fairLine", "edgePct", "updatedAt"
    )
    VALUES %s
    ON CONFLICT ("slateId", "playerId", "market")
    DO UPDATE SET
        "playerName" = EXCLUDED."playerName",
        "bookLine"   = EXCLUDED."bookLine",
        "odds"       = EXCLUDED."odds",
        "fairLine"   = EXCLUDED."fairLine",
        "edgePct"    = EXCLUDED."edgePct",
        "updatedAt"  = NOW();
    """

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            execute_values(
                cur,
                upsert_sql,
                edges,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, NOW())"
            )
        conn.commit()

    return len(edges)


def upsert_to_sqlite(db_path: Path, edges: List[Tuple[Any, ...]]) -> int:
    """Fallback local SQLite ingestion when DATABASE_URL is not provided."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = """
    CREATE TABLE IF NOT EXISTS MarketEdge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slateId TEXT NOT NULL,
        playerId TEXT NOT NULL,
        playerName TEXT NOT NULL,
        market TEXT NOT NULL,
        bookLine REAL NOT NULL,
        odds INTEGER NOT NULL,
        fairLine REAL NOT NULL,
        edgePct REAL NOT NULL,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (slateId, playerId, market)
    );
    CREATE INDEX IF NOT EXISTS idx_marketedge_edge ON MarketEdge (edgePct DESC);
    CREATE INDEX IF NOT EXISTS idx_marketedge_slate ON MarketEdge (slateId);
    """

    upsert_sql = """
    INSERT INTO MarketEdge (
        slateId, playerId, playerName, market,
        bookLine, odds, fairLine, edgePct, updatedAt
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(slateId, playerId, market) DO UPDATE SET
        playerName = excluded.playerName,
        bookLine   = excluded.bookLine,
        odds       = excluded.odds,
        fairLine   = excluded.fairLine,
        edgePct    = excluded.edgePct,
        updatedAt  = CURRENT_TIMESTAMP;
    """

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        conn.executemany(upsert_sql, edges)
        conn.commit()

    return len(edges)


def ingest_data(
    slate_id: str = "2026_w7",
    snapshot_file: Optional[str] = None,
    clv_file: Optional[str] = None,
    database_url: Optional[str] = None,
    sqlite_fallback_path: Path = Path("data/market_edges.db"),
) -> int:
    """Main ingestion coordinator callable from CLI or python threads."""
    base_dir = Path(__file__).resolve().parent

    # Resolve default paths
    snap_p = Path(snapshot_file) if snapshot_file else base_dir / "snapshots" / f"snapshots_{slate_id}.jsonl"
    if not snap_p.exists():
        snap_p = base_dir / f"snapshots_{slate_id}.jsonl"
    if not snap_p.exists():
        snap_p = base_dir / "data" / f"snapshots_{slate_id}.jsonl"

    clv_p = Path(clv_file) if clv_file else base_dir / "viewer" / "clv_audit_report.json"
    if not clv_p.exists():
        clv_p = base_dir / "public" / "clv_audit_report.json"

    feed_p = base_dir / "viewer" / "live_odds_feed.json"

    edges = extract_edges_from_sources(
        slate_id=slate_id,
        snapshot_path=snap_p,
        clv_path=clv_p if clv_p.exists() else None,
        live_feed_path=feed_p if feed_p.exists() else None,
    )

    if not edges:
        print(f"[ingest_edges] ⚠️ No edge rows extracted for slate '{slate_id}'.")
        return 0

    db_url = database_url or os.getenv("DATABASE_URL")
    if db_url and HAS_PSYCOPG2:
        try:
            count = upsert_to_postgres(db_url, edges)
            print(f"[ingest_edges] ✔ Successfully upserted {count} edges to PostgreSQL (MarketEdge).")
            return count
        except Exception as e:
            print(f"[ingest_edges] ❌ PostgreSQL connection failed: {e}. Falling back to SQLite...")

    # SQLite fallback
    count = upsert_to_sqlite(sqlite_fallback_path, edges)
    print(f"[ingest_edges] ✔ Successfully upserted {count} edges to local SQLite ({sqlite_fallback_path}).")
    return count


def main():
    parser = argparse.ArgumentParser(description="PropWire Live MarketEdge DB Ingestion")
    parser.add_argument("--slate", type=str, default="2026_w7", help="Slate identifier (e.g. 2026_w7)")
    parser.add_argument("--snapshot-file", type=str, default=None, help="Path to snapshots jsonl file")
    parser.add_argument("--clv-file", type=str, default=None, help="Path to clv_audit_report.json")
    parser.add_argument("--database-url", type=str, default=None, help="Postgres connection string")
    args = parser.parse_args()

    count = ingest_data(
        slate_id=args.slate,
        snapshot_file=args.snapshot_file,
        clv_file=args.clv_file,
        database_url=args.database_url,
    )
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
