#!/usr/bin/env python3
"""fetch_nba_odds.py - The Odds API NBA schedule + player-prop lines for PropWire.

WHAT IT WRITES (per US-Eastern date, viewer/):
  nba_games_<date>.json  bare array, real schedule from the free /events call
  nba_odds_<date>.json   provenance-stamped feed of real sportsbook prop lines

HONESTY RULES (same gate as fetch_nba.py):
  * No ODDS_API_KEY -> exit 2, writes nothing. Nothing is ever synthesised.
  * Every quote is _fixture:false, verified:false. There is no SHA-256 receipt
    path for NBA yet, so the board must keep these in "unverified" state.
  * This script does NOT create nba_slate_<date>.json. Rows on the board come
    from the model projection layer, which does not exist for real NBA players
    yet (box scores need a paid balldontlie tier). Until it does, the autopilot
    manifest will not register these dates as selectable slates.

CREDIT MODEL (free plan = 500 credits/month):
  /events is free. Props are one request per event: cost = markets x regions.
  Default is 1 market (player_points) x 1 region (us) = 1 credit per game.
  A run aborts BEFORE spending anything if the estimate exceeds --max-credits.

USAGE:
  ODDS_API_KEY=... python3 scripts/fetch_nba_odds.py --dates 2026-10-28,2026-10-29,2026-10-30
  python3 scripts/fetch_nba_odds.py --selftest      # offline pure-function checks

EXIT CODES: 0 ok - 2 missing key - 4 credit budget exceeded - 5 network/API error
"""
import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = None

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
VIEWER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer")

# The Odds API market key -> viewer market id + unit (matches nba.js markets).
MARKETS = {"player_points": ("points", "pts")}

TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def et_date_key(iso_utc):
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return (dt.astimezone(ET) if ET else dt).strftime("%Y-%m-%d")


def slug(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def normalize_game(ev):
    away, home = TEAM_ABBR.get(ev["away_team"]), TEAM_ABBR.get(ev["home_team"])
    if not away or not home:
        raise ValueError(f"unmapped team in event {ev.get('id')}: {ev['away_team']} @ {ev['home_team']}")
    day = et_date_key(ev["commence_time"])
    dt = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
    et = dt.astimezone(ET) if ET else dt
    return {
        "game_id": f"nba-{day.replace('-', '')}-{away}-{home}",
        "gameday": day,
        "gametime": et.strftime("%H:%M"),
        "gametime_et": et.strftime("%H:%M"),
        "tipoff_utc": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "away_team": away,
        "home_team": home,
        "odds_event_id": ev["id"],
        "_fixture": False,
    }


def normalize_quotes(game, event_odds, observed_at):
    """Pair Over/Under outcomes per (book, player, line). Skips unpaired sides."""
    quotes = []
    for book in event_odds.get("bookmakers", []):
        for mk in book.get("markets", []):
            if mk["key"] not in MARKETS:
                continue
            market, unit = MARKETS[mk["key"]]
            sides = {}
            for o in mk.get("outcomes", []):
                if o.get("point") is None or not o.get("description"):
                    continue
                sides.setdefault((o["description"], float(o["point"])), {})[o["name"].lower()] = o["price"]
            for (player, line), px in sorted(sides.items()):
                if "over" not in px or "under" not in px:
                    continue
                pid = f"odds-nba-{slug(player)}"
                quotes.append({
                    "quote_id": f"{game['game_id']}_{book['key']}_{slug(player)}_{market}",
                    "provider_quote_id": f"{event_odds['id']}:{book['key']}:{slug(player)}:{mk['key']}",
                    "source_url": f"{BASE_URL}/sports/{SPORT}/events/{event_odds['id']}/odds",
                    "book": book["title"],
                    "player_id": pid,
                    "player_name": player,
                    "game_id": game["game_id"],
                    "market": market,
                    "line": line,
                    "over_odds": px["over"],
                    "under_odds": px["under"],
                    "observed_at": mk.get("last_update") or observed_at,
                    "source": "The Odds API (unverified sportsbook quote)",
                    "verified": False,
                    "_fixture": False,
                    "unit": unit,
                })
    return quotes


def consensus_lines(quotes):
    """Median line per player/market across books - informational only."""
    grouped = {}
    for q in quotes:
        grouped.setdefault((q["player_id"], q["market"]), []).append(q["line"])
    return {f"{pid}:{m}": statistics.median(v) for (pid, m), v in sorted(grouped.items())}


def estimate_credits(n_events, n_markets=len(MARKETS), n_regions=1):
    return n_events * n_markets * n_regions


def api_get(path, params, key):
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode({**params, 'apiKey': key})}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            remaining = resp.headers.get("x-requests-remaining")
            return json.loads(resp.read().decode("utf-8")), remaining
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"[fetch_nba_odds] HTTP {exc.code} from {path}: {exc.read()[:200]!r}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"[fetch_nba_odds] network error: {exc}") from exc


def write_json(name, payload):
    target = os.path.join(VIEWER_DIR, name)
    if name.startswith("nba_odds_"):
        try:
            from src.contracts.odds import LiveOddsFeed
            from src.contracts.gate import validate_and_publish
            ok, manifest = validate_and_publish(
                schema_cls=LiveOddsFeed,
                raw_data=payload,
                target_path=target,
                source_feed="the_odds_api_nba",
            )
            if not ok:
                print(f"[fetch_nba_odds] FAIL-CLOSED: payload failed contract validation. Target {name} preserved.", file=sys.stderr)
            return ok
        except Exception as exc:
            print(f"[fetch_nba_odds] Contract error: {exc}", file=sys.stderr)
            return False

    temp_path = target + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(temp_path, target)
    return True


def run(dates, max_credits, key):
    events, _ = api_get(f"/sports/{SPORT}/events", {"dateFormat": "iso"}, key)  # free
    by_day = {d: [] for d in dates}
    for ev in events:
        day = et_date_key(ev["commence_time"])
        if day in by_day:
            by_day[day].append(ev)
    total = sum(len(v) for v in by_day.values())
    cost = estimate_credits(total)
    print(f"[fetch_nba_odds] {total} games across {dates}; estimated cost {cost} credits (cap {max_credits})")
    if cost > max_credits:
        print("[fetch_nba_odds] estimate exceeds --max-credits; nothing spent", file=sys.stderr)
        return 4
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    remaining = None
    for day, evs in by_day.items():
        if not evs:
            print(f"[fetch_nba_odds] {day}: no games listed; nothing written")
            continue
        games = [normalize_game(e) for e in evs]
        quotes = []
        for g in games:
            eo, remaining = api_get(
                f"/sports/{SPORT}/events/{g['odds_event_id']}/odds",
                {"regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american", "dateFormat": "iso"},
                key,
            )
            quotes += normalize_quotes(g, eo, now)
        odds_published = write_json(f"nba_odds_{day}.json", {
            "schema_version": "nba.v1",
            "feed_status": "live-unverified",
            "_fixture": False,
            "updated_at": now,
            "slate": day,
            "source": "the-odds-api",
            "verified_books_count": 0,
            "verified_quotes_count": 0,
            "monitored_books": sorted({q["book"] for q in quotes}),
            "unverified_books": sorted({q["book"] for q in quotes}),
            "total_quotes": len(quotes),
            "qualified_count": 0,
            "consensus_lines": consensus_lines(quotes),
            "quotes": quotes,
        })
        if not odds_published:
            return 5
        write_json(f"nba_games_{day}.json", games)
        print(f"[fetch_nba_odds] {day}: {len(games)} games, {len(quotes)} quotes")
    print(f"[fetch_nba_odds] credits remaining this month: {remaining}")
    return 0


def selftest():
    # Payload SHAPED per the documented Odds API schema. Synthetic test input,
    # exercised only to check parsing; it is never written to viewer/.
    ev = {"id": "e1", "commence_time": "2026-10-29T02:00:00Z",
          "away_team": "Boston Celtics", "home_team": "Los Angeles Lakers"}
    game = normalize_game(ev)
    assert game["gameday"] == "2026-10-28", game  # 02:00Z is 22:00 EDT the prior night
    assert game["game_id"] == "nba-20261028-BOS-LAL"
    assert et_date_key("2026-11-02T04:30:00Z") == "2026-11-01"  # post-DST-fallback EST
    eo = {"id": "e1", "bookmakers": [
        {"key": "a", "title": "Book A", "markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Test Player", "price": -110, "point": 24.5},
            {"name": "Under", "description": "Test Player", "price": -110, "point": 24.5},
            {"name": "Over", "description": "Lonely Player", "price": -120, "point": 10.5}]}]},
        {"key": "b", "title": "Book B", "markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Test Player", "price": 100, "point": 25.5},
            {"name": "Under", "description": "Test Player", "price": -120, "point": 25.5}]}]}]}
    qs = normalize_quotes(game, eo, "2026-10-28T12:00:00Z")
    assert len(qs) == 2, qs  # unpaired side dropped
    assert all(q["verified"] is False and q["_fixture"] is False for q in qs)
    assert consensus_lines(qs) == {"odds-nba-test-player:points": 25.0}
    assert estimate_credits(18) == 18
    try:
        normalize_game({**ev, "home_team": "Nowhere Nobodies"})
        raise AssertionError("unmapped team must raise")
    except ValueError:
        pass
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", help="comma-separated ET dates, e.g. 2026-10-28,2026-10-29")
    ap.add_argument("--max-credits", type=int, default=40)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("[fetch_nba_odds] ODDS_API_KEY not set; writing nothing (no synthetic lines).", file=sys.stderr)
        return 2
    if not args.dates:
        ap.error("--dates is required")
    return run([d.strip() for d in args.dates.split(",") if d.strip()], args.max_credits, key)


if __name__ == "__main__":
    sys.exit(main())
