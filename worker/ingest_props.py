"""Propstein 2.0 — props ingest from the v1 snapshot live-odds feed.

Reads the v1 viewer snapshot (Polymarket quotes, real players/odds;
synthetic demo fixtures are skipped with a warning), computes the model
edge (prob / fair odds / EV / Kelly / lean) and upserts Prop rows.
Game stubs for snapshot slates are created as snap-{game_id}.

    DATABASE_URL=... python worker/ingest_props.py [--snapshot worker/data/live_odds_feed.json]

Exit codes: 0 ok, 2 no DATABASE_URL, 3 snapshot/upstream, 5 db.
"""

import argparse
import json
import os
import re
import sys
import unicodedata

from upsert import EXIT_OK, EXIT_UPSTREAM, EXIT_DB, connect, finish, jsonb, upsert_rows
from ev import compute_edge

DEFAULT_SNAPSHOT = os.path.join(os.path.dirname(__file__), "data", "live_odds_feed.json")


def name_key(name: str) -> str:
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def prop_id(slate: str, player_id: str, market: str, book: str, line: float) -> str:
    return f"{slate}|{player_id}|{market}|{book}|{line}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    args = ap.parse_args()

    try:
        snap = json.load(open(args.snapshot, encoding="utf-8"))
    except FileNotFoundError:
        print(f"FATAL: snapshot not found: {args.snapshot}", file=sys.stderr)
        return EXIT_UPSTREAM
    except json.JSONDecodeError as e:
        print(f"FATAL: snapshot is not valid JSON: {e}", file=sys.stderr)
        return EXIT_UPSTREAM

    quotes = snap.get("quotes") or []
    slate = snap.get("slate") or "UNDATED"
    print(f"  snapshot: {len(quotes)} quotes, slate {slate}")

    players: dict[str, dict] = {}
    games: dict[str, dict] = {}
    props: list[dict] = []
    skipped = 0
    for q in quotes:
        book = str(q.get("book") or "?")
        if book.startswith("Synthetic") or q.get("player_name", "").startswith("Player "):
            skipped += 1
            continue  # demo fixture — never a real player/book
        nk = name_key(q["player_name"])
        pid = f"nfl-{nk}"
        players[pid] = {
            "id": pid,
            "league": "NFL",
            "name": q["player_name"],
            "name_key": nk,
            "team": q.get("team"),
            "position": q.get("position"),
            "jersey": None, "height_cm": None, "weight_kg": None, "headshot": None,
            "espn_id": None, "nba_stats_id": None,
            "source": "snapshot_v1",
            "form_summary": None, "stats_summary": None,
        }
        gid = None
        if q.get("game_id"):
            gid = f"snap-{q['game_id']}"
            parts = str(q["game_id"]).split("_")  # 2026_07_NE_CHI
            games[gid] = {
                "id": gid,
                "league": "NFL",
                "season": int(parts[0]) if parts and parts[0].isdigit() else 2026,
                "week": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                "slug": q["game_id"],
                "start_time": q.get("observed_at"),
                "state": "post",
                "detail": "v1 snapshot slate",
                "home_team": parts[3] if len(parts) > 3 else "—",
                "home_score": None,
                "away_team": parts[2] if len(parts) > 2 else "—",
                "away_score": None,
                "venue": None, "broadcast": None, "odds_line": None,
                "raw_payload": jsonb({"snapshot": True}),
            }
        edge = compute_edge(
            q["fair_line"], q["line"], q["market"], q.get("over_odds"), q.get("under_odds")
        )
        props.append({
            "id": prop_id(slate, pid, q["market"], book, q["line"]),
            "player_id": pid,
            "game_id": gid,
            "league": "NFL",
            "slate": slate,
            "market": q["market"],
            "line": q["line"],
            "fair_line": q["fair_line"],
            "over_odds": q.get("over_odds"),
            "under_odds": q.get("under_odds"),
            "book": book,
            "best_side": edge["best_side"],
            "prob_win": edge["prob_win"],
            "fair_odds": edge["fair_odds"],
            "ev": edge["ev"],
            "kelly": edge["kelly"],
            "lean": edge["lean"],
            "verified": bool(q.get("verified")),  # upstream flag only — OBSERVED ≠ verified (audit fix 2026-11-03)
            "observed_at": q.get("observed_at"),
            "raw_payload": jsonb({"quote_id": q.get("quote_id"), "evaluation": q.get("evaluation")}),
        })
    verified_count = sum(1 for p in props if p["verified"])
    print(
        f"  real quotes: {len(props)} (skipped {skipped} synthetic fixtures) "
        f"[verified: {verified_count} — receipt-matched/OBSERVED rows stay unverified]"
    )

    if not props:
        print("FATAL: no usable quotes in snapshot", file=sys.stderr)
        return EXIT_UPSTREAM

    conn = None
    try:
        conn = connect()
        with conn.cursor() as cur:
            upsert_rows(cur, '"Player"', list(players.values()), ["id"],
                        ["name", "name_key", "team", "position", "source"])
            upsert_rows(cur, '"Game"', list(games.values()), ["id"])
            n = upsert_rows(cur, '"Prop"', props, ["id"],
                            ["line", "fair_line", "over_odds", "under_odds", "book",
                             "best_side", "prob_win", "fair_odds", "ev", "kelly", "lean",
                             "verified", "observed_at", "raw_payload"])
        finish(conn, True)
        conn = None
        print(f"OK: upserted {n} props, {len(players)} players, {len(games)} game stubs")
        return EXIT_OK
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: db write failed: {e}", file=sys.stderr)
        if conn:
            finish(conn, False)
        return EXIT_DB


if __name__ == "__main__":
    sys.exit(main())
