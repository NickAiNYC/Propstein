#!/usr/bin/env python3
"""fetch_nba.py — balldontlie NBA ingest gate for PropWire (Phase 2).

DATA-SOURCE GATE (Phase 0.5, user-approved):
  The only documented, ToS-clean NBA source is the balldontlie NBA API
  (https://docs.balldontlie.io). Free tier (5 req/min) covers teams/
  players/games; BOX SCORES (/v1/stats) require the ALL-STAR tier or
  higher. Scraping nba.stats.com / ESPN endpoints / ufcstats-style
  scraping is FORBIDDEN by the project ToS rule.

BEHAVIOUR:
  • No BALLDONTLIE_API_KEY in the environment → exit 2, writes nothing.
    The viewer keeps loading the committed research fixtures
    (every row carries _fixture: true) until real feeds are committed.
  • With a key: fetches teams + games for --date (free tier), then box
    scores (/v1/stats) — on a tier without stats access the API answers
    402/403 (legacy gateway) or 401 (unified gateway, verified live
    2026-11-03: "Unauthorized - ... your account tier does not have
    access to the endpoint") and the script exits 3 with the exact tier
    requirement.
  • Rate limit: hard-capped at 5 req/min (13s sleep between calls);
    429 responses honour Retry-After.
  • Output files are provenance-stamped: _fixture: false, schema_version
    "nba.v1", source "balldontlie", generated_at UTC ISO-8601. The viewer
    schema for slate/games stays a BARE ARRAY (parity guard), so fixture
    provenance flags live per row/game and real provenance lives here.

SCOPE NOTE (v1): this script proves the pipeline (auth, rate limits,
schema, provenance) and lands games + box-score evidence. Turning raw
box scores into model projections is a modeling pass, not an ingest
concern — the committed fixture slate remains the viewer's NBA slate
until that pass retires it.

USAGE:
  BALLDONTLIE_API_KEY=... python3 scripts/fetch_nba.py --date 2026-10-22
  python3 scripts/fetch_nba.py --selftest        # offline pure-function checks

EXIT CODES: 0 ok · 2 missing key · 3 tier lacks box scores ·
            4 rate-limit exhausted · 5 network/protocol error
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    ET = None

BASE_URL = "https://api.balldontlie.io/v1"
REQUEST_SPACING_SECONDS = 13  # 5 req/min documented free-tier cap
VIEWER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer")

FIXTURE_DATE = "2026-10-22"  # committed fixture slate this script can retire


def et_date_key(iso_utc):
    """Calendar date of an ISO-8601 UTC timestamp in US Eastern time.

    Mirrors viewer/js/sports/nba.js etDateKey() — the single source of
    truth for slate keying (DST-safe via the IANA tz database).
    """
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ET is None:  # pragma: no cover
        return dt.astimezone(timezone.utc).date().isoformat()
    return dt.astimezone(ET).date().isoformat()


def normalize_game(game):
    """balldontlie game object → viewer nba_games_* row (provenance-stamped)."""
    tipoff = game.get("date") or game.get("datetime")
    return {
        "game_id": f"bdl-{game.get('id')}",
        "gameday": et_date_key(tipoff),
        "gametime": (game.get("time") or None),
        "gametime_et": (game.get("time") or None),
        "tipoff_utc": tipoff,
        "away_team": (game.get("visitor_team") or {}).get("abbreviation"),
        "home_team": (game.get("home_team") or {}).get("abbreviation"),
        "venue": game.get("arena") or None,
        "status": game.get("status"),
        "bdl_home_team_id": (game.get("home_team") or {}).get("id"),
        "bdl_visitor_team_id": (game.get("visitor_team") or {}).get("id"),
        "_fixture": False,
        "source": "balldontlie",
    }


def stats_error_is_tier_block(code):
    """True when balldontlie's gateway blocks /v1/stats for the account tier.

    Live behavior (verified 2026-11-03 against api.balldontlie.io/v1): the
    unified gateway answers HTTP 401 "Unauthorized - You either need an API
    key or your account tier does not have access to the endpoint" for
    plan-gated endpoints; 402/403 are the older tier codes. A 401 at the
    stats stage cannot mean a bad key — the same key authenticated the
    /v1/games call moments earlier (a bad key exits 2 there) — so it is a
    tier block, and must be reported as exit 3, not a network error.
    """
    return code in (401, 402, 403)


def normalize_boxscore_row(stat):
    """balldontlie /v1/stats row → normalized box-score evidence row."""
    player = stat.get("player") or {}
    team = stat.get("team") or {}
    game = stat.get("game") or {}
    return {
        "bdl_game_id": game.get("id"),
        "game_id": f"bdl-{game.get('id')}",
        "player_id": f"bdl-{player.get('id')}",
        "player_display_name": player.get("first_name", "") + " " + player.get("last_name", ""),
        "team": team.get("abbreviation"),
        "position": player.get("position"),
        "minutes": stat.get("min"),
        "pts": stat.get("pts"),
        "rebounds": stat.get("reb"),
        "assists": stat.get("ast"),
        "fg3m": stat.get("fg3m"),
        "_fixture": False,
        "source": "balldontlie",
    }


def request_json(url, api_key, sleep_between):
    """GET JSON with Authorization header; honours 429 Retry-After once."""
    req = urllib.request.Request(url, headers={"Authorization": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        time.sleep(sleep_between)
        return payload, None
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry_after = float(exc.headers.get("Retry-After") or 60)
            time.sleep(retry_after)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                time.sleep(sleep_between)
                return payload, None
            except urllib.error.HTTPError as retry_exc:
                return None, retry_exc
            except Exception as retry_exc:  # pragma: no cover
                return None, retry_exc
        return None, exc
    except Exception as exc:  # pragma: no cover - network layer
        return None, exc


def fetch_day(date_str, api_key, sleep_between=REQUEST_SPACING_SECONDS):
    """Fetch teams (cache-free) + games + box scores for one ET date.

    Returns (feeds, error) where feeds is a dict that may be partially
    filled when a tier lacks box scores (error code 3).
    """
    games_payload, err = request_json(f"{BASE_URL}/games?dates[]={date_str}", api_key, sleep_between)
    if err is not None:
        code = getattr(err, "code", None)
        if code in (402, 403):
            return None, {
                "exit": 3,
                "message": "balldontlie rejected the games/stats request (HTTP %s). "
                           "Games are free-tier; box scores (/v1/stats) need the ALL-STAR tier "
                           "or higher. The viewer keeps loading committed research fixtures." % code,
            }
        if code == 401:
            return None, {"exit": 2, "message": "balldontlie rejected the API key (HTTP 401)."}
        return None, {"exit": 5, "message": f"network error fetching games: {err}"}

    games = (games_payload or {}).get("data") or []
    normalized_games = [normalize_game(g) for g in games]

    box_rows = []
    tier_block = None
    for game in normalized_games:
        bdl_id = game["game_id"].replace("bdl-", "")
        stats_payload, err = request_json(
            f"{BASE_URL}/stats?game_ids[]={bdl_id}&season={date_str[:4]}&per_page=100",
            api_key,
            sleep_between,
        )
        if err is not None:
            code = getattr(err, "code", None)
            if stats_error_is_tier_block(code):
                tier_block = {
                    "exit": 3,
                    "message": "Box scores (/v1/stats) need a paid balldontlie tier "
                               "(ALL-STAR or GOAT per the Phase 0.5 gate; the gateway "
                               "answers HTTP %s until then). No live feed was published." % code,
                }
                break
            return None, {"exit": 5, "message": f"network error fetching stats for {bdl_id}: {err}"}
        box_rows.extend(normalize_boxscore_row(s) for s in ((stats_payload or {}).get("data") or []))

    feeds = {
        "games": {
            "schema_version": "nba.v1",
            "slate_key": et_date_key(normalized_games[0]["tipoff_utc"]) if normalized_games else date_str,
            "timezone": "America/New_York",
            "_fixture": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "balldontlie",
            "games": normalized_games,
        },
        "boxscore": {
            "schema_version": "nba.v1",
            "_fixture": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "balldontlie",
            "rows": box_rows,
        },
    }
    return (feeds, tier_block), None


def write_feeds(feeds):
    # Import only at publish time; --selftest and the no-key gate stay stdlib-only.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.contracts.gate import validate_and_publish
    from src.contracts.nba import NbaBoxscoreFeed, NbaGame

    # Validate the entire pair before either target is replaced.
    game_rows = feeds["games"]["games"]
    box_feed = feeds["boxscore"]
    for row in game_rows:
        NbaGame.model_validate(row)
    NbaBoxscoreFeed.model_validate(box_feed)
    game_ids = {row["game_id"] for row in game_rows}
    if any(row["game_id"] not in game_ids for row in box_feed["rows"]):
        raise ValueError("boxscore references a game outside the published slate")

    slate_key = feeds["games"]["slate_key"]
    games_path = os.path.join(VIEWER_DIR, f"nba_games_{slate_key}.json")
    box_path = os.path.join(VIEWER_DIR, f"nba_boxscore_{slate_key}.json")
    ok_games, _ = validate_and_publish(NbaGame, game_rows, games_path,
                                       source_feed="balldontlie_games", min_rows=0)
    if not ok_games:
        raise ValueError("NBA games contract rejected payload")
    ok_box, _ = validate_and_publish(NbaBoxscoreFeed, box_feed, box_path,
                                     source_feed="balldontlie_stats", min_rows=0)
    if not ok_box:
        raise ValueError("NBA boxscore contract rejected payload")
    return games_path, box_path


def selftest():
    """Offline pure-function assertions (zero network, zero deps)."""
    # ET date keying incl. DST boundaries (must mirror nba.js etDateKey).
    assert et_date_key("2026-10-22T23:30:00Z") == "2026-10-22"
    assert et_date_key("2026-10-23T02:00:00Z") == "2026-10-22", "10pm EDT tipoff stays on the ET slate date"
    assert et_date_key("2026-11-01T03:30:00Z") == "2026-10-31", "23:30 EDT Oct 31"
    assert et_date_key("2026-11-01T05:30:00Z") == "2026-11-01", "01:30 EDT before fallback"
    assert et_date_key("2026-11-01T06:30:00Z") == "2026-11-01", "01:30 EST after fallback"
    assert et_date_key("2026-03-08T07:30:00Z") == "2026-03-08", "03:30 EDT after spring-forward"
    assert et_date_key(None) is None
    assert et_date_key("not-a-date") is None

    # Game normalization shape + provenance.
    game = normalize_game({
        "id": 12345,
        "date": "2026-10-22T23:30:00Z",
        "time": "7:30",
        "status": "Scheduled",
        "arena": "Madison Square Garden",
        "home_team": {"id": 20, "abbreviation": "NYK"},
        "visitor_team": {"id": 2, "abbreviation": "BOS"},
    })
    assert game["game_id"] == "bdl-12345"
    assert game["gameday"] == "2026-10-22"
    assert game["away_team"] == "BOS" and game["home_team"] == "NYK"
    assert game["_fixture"] is False and game["source"] == "balldontlie"

    # Box-score normalization shape + provenance.
    row = normalize_boxscore_row({
        "player": {"id": 999, "first_name": "Test", "last_name": "Player", "position": "SF"},
        "team": {"abbreviation": "BOS"},
        "game": {"id": 12345},
        "min": "36:12", "pts": 31, "reb": 8, "ast": 5, "fg3m": 4,
    })
    assert row["player_id"] == "bdl-999"
    assert row["player_display_name"] == "Test Player"
    assert row["pts"] == 31 and row["fg3m"] == 4
    assert row["_fixture"] is False and row["source"] == "balldontlie"

    # Stats tier-gate classification: the unified balldontlie gateway returns
    # 401 for plan-gated /v1/stats (verified live 2026-11-03); 402/403 are the
    # legacy codes. A 401 here is a tier block, not a bad key (games auth ran
    # first) and not a network error (exit 5 would mislabel it in autopilot).
    assert stats_error_is_tier_block(401)
    assert stats_error_is_tier_block(402)
    assert stats_error_is_tier_block(403)
    assert not stats_error_is_tier_block(429)
    assert not stats_error_is_tier_block(500)
    assert not stats_error_is_tier_block(None)

    # Committed fixture feeds stay untouched by ingest semantics: the script
    # writes bdl-* ids / _fixture:false, never mutating fx-* fixture rows.
    print("selftest OK: ET keying (DST), game + box-score normalization, provenance flags, "
          "stats tier-gate classification (401/402/403)")


def main():
    parser = argparse.ArgumentParser(description="PropWire balldontlie NBA ingest gate")
    parser.add_argument("--date", help="Slate date (YYYY-MM-DD, US Eastern calendar date)")
    parser.add_argument("--selftest", action="store_true", help="Run offline pure-function checks and exit")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        return 0

    api_key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    if not api_key:
        print(
            "GATE: BALLDONTLIE_API_KEY is not set — nothing fetched, nothing written.\n"
            "The viewer keeps loading the committed research fixtures\n"
            "(viewer/nba_*_2026-10-22.json, _fixture: true).\n"
            "Real data requires a balldontlie NBA key (docs.balldontlie.io); box scores\n"
            "need the ALL-STAR tier or higher per the Phase 0.5 data-source gate."
        )
        return 2

    if not args.date:
        print("--date is required (e.g. --date 2026-10-22, the US Eastern slate date)")
        return 5

    result, error = fetch_day(args.date, api_key)
    if error is not None:
        print(error["message"])
        return error["exit"]

    feeds, tier_block = result
    if tier_block is not None:
        print(tier_block["message"])
        return tier_block["exit"]
    try:
        games_path, box_path = write_feeds(feeds)
    except Exception as exc:
        print(f"NBA contract/publish failure: {exc}")
        return 5
    print(f"wrote {games_path} ({len(feeds['games']['games'])} games, _fixture:false, source:balldontlie)")
    print(f"wrote {box_path} ({len(feeds['boxscore']['rows'])} box-score rows, _fixture:false, source:balldontlie)")
    print("NEXT: box scores are raw evidence — a modeling pass must produce projections and "
          f"retire the committed fixture slate ({FIXTURE_DATE}) before the viewer renders this date as live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
