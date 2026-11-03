"""Propstein 2.0 — ESPN scoreboard ingest (NBA / NFL / NHL).

Zero-cost, no auth: site.api.espn.com public JSON.

    DATABASE_URL=... python worker/ingest_games.py [--leagues NBA,NFL,NHL] [--days 2]

Upserts Game rows (id espn-{league}-{eventId}). Exit codes: 0 ok,
2 no DATABASE_URL, 3 upstream fetch failed, 5 db write failed.
"""

import argparse
import os
import json
import sys
import urllib.request
from datetime import date, timedelta

from upsert import EXIT_OK, EXIT_NO_DB, EXIT_UPSTREAM, EXIT_DB, connect, finish, jsonb, upsert_rows

UA = {"User-Agent": "propstein-ingest/2.0"}
PATHS = {"NBA": "basketball/nba", "NFL": "football/nfl", "NHL": "hockey/nhl"}


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def map_event(league: str, ev: dict) -> dict:
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    odds = (comp.get("odds") or [{}])[0] if comp.get("odds") else {}
    odds_line = " ".join(
        x for x in [odds.get("details"), f"O/U {odds['overUnder']}" if odds.get("overUnder") else ""]
        if x
    ).strip() or None
    status = ev.get("status", {}).get("type", {})
    return {
        "id": f"espn-{league.lower()}-{ev['id']}",
        "league": league,
        "season": (ev.get("season") or {}).get("year") or date.today().year,
        "week": (ev.get("week") or {}).get("number"),
        "slug": None,
        "start_time": ev["date"],
        "state": status.get("state") or "pre",
        "detail": status.get("shortDetail"),
        "home_team": (home.get("team") or {}).get("abbreviation") or "—",
        "home_score": int(home["score"]) if home.get("score") is not None else None,
        "away_team": (away.get("team") or {}).get("abbreviation") or "—",
        "away_score": int(away["score"]) if away.get("score") is not None else None,
        "venue": (comp.get("venue") or {}).get("fullName"),
        "broadcast": ", ".join((comp.get("broadcasts") or [{}])[0].get("names", [])) if comp.get("broadcasts") else None,
        "odds_line": odds_line,
        "raw_payload": jsonb({"espnEventId": ev["id"], "name": ev.get("shortName")}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="NBA,NFL,NHL")
    ap.add_argument("--days", type=int, default=2, help="lookback days incl. today")
    args = ap.parse_args()
    leagues = [l.strip().upper() for l in args.leagues.split(",") if l.strip().upper() in PATHS]

    if not os.environ.get("DATABASE_URL"):
        print("FATAL: DATABASE_URL is not set (fail-closed)", file=sys.stderr)
        return EXIT_NO_DB

    rows = []
    today = date.today()
    for league in leagues:
        for back in range(args.days):
            d = (today - timedelta(days=back)).strftime("%Y%m%d")
            url = f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[league]}/scoreboard?dates={d}"
            try:
                data = fetch_json(url)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: {league} {d} scoreboard failed: {e}", file=sys.stderr)
                continue
            for ev in data.get("events") or []:
                rows.append(map_event(league, ev))
            print(f"  {league} {d}: {len(data.get('events') or [])} events")

    if not rows:
        print("FATAL: no events fetched from any league", file=sys.stderr)
        return EXIT_UPSTREAM

    deduped = {r["id"]: r for r in rows}
    conn = None
    try:
        conn = connect()
        with conn.cursor() as cur:
            n = upsert_rows(cur, '"Game"', list(deduped.values()), ["id"])
        finish(conn, True)
        conn = None
        print(f"OK: upserted {n} games ({len(leagues)} leagues, {args.days}d)")
        return EXIT_OK
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: db write failed: {e}", file=sys.stderr)
        if conn:
            finish(conn, False)
        return EXIT_DB


if __name__ == "__main__":
    sys.exit(main())
