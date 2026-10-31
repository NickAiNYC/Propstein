#!/usr/bin/env python3
"""Register an NBA market-only slate after a successful real odds fetch.

No model projections or qualification are created here. A zero-row slate is
intentional: the viewer renders observed sportsbook lines in a separate,
unverified market view rather than inventing NBA player predictions.
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from autopilot import VIEWER, write_manifest


def publish(day: str) -> None:
    datetime.strptime(day, "%Y-%m-%d")
    games_path = VIEWER / f"nba_games_{day}.json"
    odds_path = VIEWER / f"nba_odds_{day}.json"
    games = json.loads(games_path.read_text())
    odds = json.loads(odds_path.read_text())
    if not games or not all(g.get("gameday") == day and g.get("_fixture") is False for g in games):
        raise ValueError("No real games for requested NBA date")
    if odds.get("slate") != day or odds.get("_fixture") is not False or odds.get("feed_status") != "live-unverified":
        raise ValueError("NBA odds provenance or date mismatch")
    if not odds.get("quotes") or odds.get("total_quotes") != len(odds["quotes"]):
        raise ValueError("No paired, published player prop quotes")
    game_ids = {g["game_id"] for g in games}
    if any(q.get("game_id") not in game_ids or q.get("verified") is not False for q in odds["quotes"]):
        raise ValueError("NBA odds reference missing game or claim verification")
    (VIEWER / f"nba_slate_{day}.json").write_text("[]\n", encoding="utf-8")
    (VIEWER / f"nba_injuries_{day}.json").write_text(json.dumps({
        "_fixture": False,
        "slate_date": day,
        "as_of": odds["updated_at"],
        "source": "No injury feed configured",
        "injuries": [],
        "impacted_beneficiaries": {},
    }, indent=2) + "\n", encoding="utf-8")
    now = datetime.now(ZoneInfo("America/New_York"))
    write_manifest(now)
    print(f"Registered NBA {day}: {len(games)} games, {len(odds['quotes'])} unverified points quotes; no modeled predictions")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: publish_nba_market_slate.py YYYY-MM-DD")
    publish(sys.argv[1])
