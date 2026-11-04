"""B1 Line-History Capture Engine (spec: docs/B1-LINE-HISTORY-SPEC.md).

Maintains timestamped, cross-book historical record of player prop lines in SQLite.
Enforces forward-only audit integrity:
- Observations are sacred: stored with UTC observation timestamp and verification state.
- Deduplication: only records a row on change (line or price) vs that book's last observation.
- Zero synthetic backfill: gaps remain honest gaps.
- Schema is SQLite-native and PostgreSQL-portable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "line_history.db"

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS events (
  event_id     TEXT PRIMARY KEY,
  league       TEXT NOT NULL DEFAULT 'nfl',
  season       INTEGER NOT NULL,
  week         INTEGER NOT NULL,
  home_team    TEXT NOT NULL,
  away_team    TEXT NOT NULL,
  kickoff_utc  TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE TABLE IF NOT EXISTS players (
  player_id    TEXT PRIMARY KEY,
  full_name    TEXT NOT NULL,
  team         TEXT,
  position     TEXT,
  aliases      TEXT
);

CREATE TABLE IF NOT EXISTS books (
  book_id      TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS lines (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id      TEXT NOT NULL REFERENCES books(book_id),
  event_id     TEXT NOT NULL REFERENCES events(event_id),
  player_id    TEXT REFERENCES players(player_id),
  market       TEXT NOT NULL,
  line         REAL NOT NULL,
  over_price   INTEGER,
  under_price  INTEGER,
  captured_at  TEXT NOT NULL,
  source       TEXT NOT NULL,
  verified     INTEGER NOT NULL DEFAULT 0,
  raw_hash     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_lines_dedupe
  ON lines(book_id, event_id, IFNULL(player_id,''), market, line,
           over_price, under_price, captured_at);

CREATE INDEX IF NOT EXISTS idx_lines_series
  ON lines(event_id, player_id, market, captured_at);

CREATE INDEX IF NOT EXISTS idx_lines_steam
  ON lines(event_id, market, line, captured_at);
"""


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize line history database schema."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    return conn


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class LineHistoryStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.conn = init_db(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def upsert_book(self, book_id: str, display_name: str | None = None, active: int = 1):
        clean_id = _slug(book_id)
        name = display_name or book_id
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO books (book_id, display_name, active)
                VALUES (?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                  display_name = excluded.display_name,
                  active = excluded.active
                """,
                (clean_id, name, active),
            )
        return clean_id

    def upsert_event(
        self,
        event_id: str,
        home_team: str,
        away_team: str,
        kickoff_utc: str,
        season: int = 2026,
        week: int = 7,
        league: str = "nfl",
        status: str = "scheduled",
    ):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO events (event_id, league, season, week, home_team, away_team, kickoff_utc, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                  kickoff_utc = excluded.kickoff_utc,
                  status = excluded.status
                """,
                (event_id, league, season, week, home_team, away_team, kickoff_utc, status),
            )

    def upsert_player(
        self,
        player_id: str,
        full_name: str,
        team: str | None = None,
        position: str | None = None,
        aliases: list[str] | None = None,
    ):
        aliases_json = json.dumps(aliases or [])
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO players (player_id, full_name, team, position, aliases)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                  full_name = excluded.full_name,
                  team = COALESCE(excluded.team, players.team),
                  position = COALESCE(excluded.position, players.position),
                  aliases = excluded.aliases
                """,
                (player_id, full_name, team, position, aliases_json),
            )

    def record_line(
        self,
        book_id: str,
        event_id: str,
        player_id: str | None,
        market: str,
        line: float,
        over_price: int | None,
        under_price: int | None,
        captured_at: str,
        source: str = "api",
        verified: bool = False,
        raw_hash: str | None = None,
    ) -> bool:
        """Record line observation. Only writes if line or prices changed vs last row for this book.

        Returns True if a new row was inserted, False if skipped (unchanged).
        """
        clean_book = _slug(book_id)

        # Auto-ensure foreign key entities exist if not explicitly inserted
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO books (book_id, display_name) VALUES (?, ?)",
                (clean_book, book_id),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO events (event_id, home_team, away_team, kickoff_utc, season, week) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, "HOM", "AWY", captured_at, 2026, 7),
            )
            if player_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO players (player_id, full_name) VALUES (?, ?)",
                    (player_id, player_id),
                )

        # Check latest recorded line for this specific (book, event, player, market)
        cursor = self.conn.execute(
            """
            SELECT line, over_price, under_price
            FROM lines
            WHERE book_id = ? AND event_id = ? AND IFNULL(player_id, '') = IFNULL(?, '') AND market = ?
            ORDER BY id DESC LIMIT 1
            """,
            (clean_book, event_id, player_id, market),
        )
        prev = cursor.fetchone()
        if prev:
            prev_line = float(prev["line"])
            prev_over = prev["over_price"]
            prev_under = prev["under_price"]
            if (
                abs(prev_line - float(line)) < 1e-6
                and prev_over == over_price
                and prev_under == under_price
            ):
                return False  # Unchanged quote: drop duplicate

        # If raw_hash is missing, compute deterministic hash
        if not raw_hash:
            h_input = f"{clean_book}:{event_id}:{player_id}:{market}:{line}:{over_price}:{under_price}:{captured_at}"
            raw_hash = hashlib.sha256(h_input.encode("utf-8")).hexdigest()

        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO lines (
                  book_id, event_id, player_id, market, line, over_price, under_price,
                  captured_at, source, verified, raw_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_book,
                    event_id,
                    player_id,
                    market,
                    float(line),
                    over_price,
                    under_price,
                    captured_at,
                    source,
                    1 if verified else 0,
                    raw_hash,
                ),
            )
        return True

    def ingest_quotes(
        self,
        quotes: list[dict[str, Any]],
        default_source: str = "api",
    ) -> dict[str, int]:
        """Bulk ingest quote dicts from live odds feeds or provider sweeps."""
        recorded = 0
        skipped = 0

        now_utc = datetime.now(timezone.utc).isoformat()

        for q in quotes:
            book_name = q.get("book") or "unknown"
            clean_book = self.upsert_book(book_name, display_name=book_name)

            game_id = q.get("game_id") or "event_unknown"
            self.upsert_event(
                event_id=game_id,
                home_team=q.get("team") or "HOM",
                away_team=q.get("opponent") or "AWY",
                kickoff_utc=now_utc,
            )

            pid = q.get("player_id")
            pname = q.get("player_name")
            if pid and pname:
                self.upsert_player(
                    player_id=pid,
                    full_name=pname,
                    team=q.get("team"),
                    position=q.get("position"),
                )

            line_val = q.get("line")
            if line_val is None:
                skipped += 1
                continue

            captured = q.get("observed_at") or now_utc
            over_px = q.get("over_odds") if q.get("over_odds") is not None else q.get("odds")
            under_px = q.get("under_odds")
            market = q.get("market") or "receiving_yards"
            verified = bool(q.get("verified", False))
            raw_hash = q.get("content_hash")

            inserted = self.record_line(
                book_id=clean_book,
                event_id=game_id,
                player_id=pid,
                market=market,
                line=float(line_val),
                over_price=int(over_px) if over_px is not None else None,
                under_price=int(under_px) if under_px is not None else None,
                captured_at=captured,
                source=q.get("source") or default_source,
                verified=verified,
                raw_hash=raw_hash,
            )
            if inserted:
                recorded += 1
            else:
                skipped += 1

        return {"recorded": recorded, "skipped": skipped, "total": len(quotes)}

    def get_series(
        self,
        player_id: str,
        market: str,
        book_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch chronological line series grouped by book."""
        params: list[Any] = [player_id, market]
        book_clause = ""
        if book_id:
            book_clause = " AND book_id = ?"
            params.append(_slug(book_id))

        sql = f"""
            SELECT book_id, line, over_price, under_price, captured_at, verified
            FROM lines
            WHERE player_id = ? AND market = ? {book_clause}
            ORDER BY captured_at ASC
        """
        rows = self.conn.execute(sql, params).fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            b = r["book_id"]
            result.setdefault(b, []).append({
                "t": r["captured_at"],
                "line": float(r["line"]),
                "over": r["over_price"],
                "under": r["under_price"],
                "verified": bool(r["verified"]),
            })
        return result

    def detect_steam(
        self,
        event_id: str,
        market: str,
        window_minutes: int = 15,
        min_books: int = 2,
        min_line_delta: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Detect rapid coordinated line moves across multiple books."""
        sql = """
            SELECT book_id, player_id, line, over_price, under_price, captured_at
            FROM lines
            WHERE event_id = ? AND market = ?
            ORDER BY captured_at DESC
        """
        rows = self.conn.execute(sql, (event_id, market)).fetchall()
        by_player: dict[str, list[dict]] = {}
        for r in rows:
            by_player.setdefault(r["player_id"], []).append(dict(r))

        signals = []
        for pid, player_rows in by_player.items():
            books = set(r["book_id"] for r in player_rows)
            if len(books) < min_books:
                continue
            lines_seen = [r["line"] for r in player_rows]
            if max(lines_seen) - min(lines_seen) >= min_line_delta:
                signals.append({
                    "player_id": pid,
                    "event_id": event_id,
                    "market": market,
                    "books": list(books),
                    "min_line": min(lines_seen),
                    "max_line": max(lines_seen),
                    "delta": max(lines_seen) - min(lines_seen),
                })
        return signals

    def export_static_series(self, out_dir: Path | str = ROOT / "viewer" / "api" / "lines"):
        """Generate static JSON line series per (player, market) for public pages."""
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        sql = "SELECT DISTINCT player_id, market FROM lines WHERE player_id IS NOT NULL"
        pairs = self.conn.execute(sql).fetchall()
        exported = 0
        now_utc = datetime.now(timezone.utc).isoformat()

        for p in pairs:
            pid = p["player_id"]
            mkt = p["market"]
            series = self.get_series(pid, mkt)
            if not series:
                continue

            slug_pair_dir = out_path / _slug(pid)
            slug_pair_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "player_id": pid,
                "market": mkt,
                "generated_at": now_utc,
                "series": series,
            }
            target_file = slug_pair_dir / f"{_slug(mkt)}.json"
            target_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            exported += 1

        return exported

    def stats(self) -> dict[str, Any]:
        with self.conn:
            ev_count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            pl_count = self.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
            bk_count = self.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            ln_count = self.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
            ver_count = self.conn.execute("SELECT COUNT(*) FROM lines WHERE verified = 1").fetchone()[0]
        return {
            "events": ev_count,
            "players": pl_count,
            "books": bk_count,
            "lines": ln_count,
            "verified_lines": ver_count,
            "db_path": str(self.db_path),
        }


def main():
    parser = argparse.ArgumentParser(description="PropStein B1 Line-History Capture")
    parser.add_argument("--init", action="store_true", help="Initialize database schema")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Database path")
    parser.add_argument("--ingest-feed", type=str, help="Ingest JSON odds feed")
    parser.add_argument("--export-static", action="store_true", help="Export static JSON series for public pages")
    parser.add_argument("--stats", action="store_true", help="Print line history statistics")
    args = parser.parse_args()

    store = LineHistoryStore(args.db)

    if args.ingest_feed:
        feed_p = Path(args.ingest_feed)
        if not feed_p.exists():
            print(f"Feed file not found: {feed_p}")
            sys.exit(1)
        data = json.loads(feed_p.read_text(encoding="utf-8"))
        quotes = data.get("quotes", [])
        res = store.ingest_quotes(quotes, default_source=feed_p.name)
        print(f"Ingested {feed_p.name}: {res['recorded']} recorded, {res['skipped']} unchanged duplicates.")

    if args.export_static:
        exported = store.export_static_series()
        print(f"Exported static line series for {exported} player-market pairs.")

    if args.stats or args.init:
        st = store.stats()
        print(f"Line History Store [{st['db_path']}]:")
        print(f"  Events: {st['events']} | Players: {st['players']} | Books: {st['books']}")
        print(f"  Total Lines: {st['lines']} (Verified: {st['verified_lines']})")

    store.close()


if __name__ == "__main__":
    main()
