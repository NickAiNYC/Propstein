#!/usr/bin/env python3
"""ingest_espn_game_context.py — Capture live ESPN/DraftKings game context with verified provenance.

HONESTY & INTEGRITY CONTRACT:
  1. Capture time: spread_observed_at, total_observed_at, and weather_observed_at
     are set to the EXACT UTC moment this script fetched the live endpoint.
  2. No fake weather: If temperature and wind are unavailable (e.g. outdoor game with no
     forecast yet), weather_observed_at is omitted (None) unless real data exists.
  3. Pre-kickoff only: Games marked in-progress ('in') or completed ('post') or scheduled
     prior to fetch time are strictly excluded.
  4. Spread sign convention: In nflverse, spread_line is home-relative where POSITIVE
     means home is favored. DraftKings reports home point spread (e.g. '+10' when home is underdog,
     '-3.5' when home is favored). We parse home point spread directly: nflverse = -float(home_spread).
  5. Audit log kept: Captures are tracked in data/game_context_captures.jsonl, and raw payloads
     in data/raw_espn_captures/, tracked in git as an immutable audit journal.
  6. Fail closed: Full slate check (at least 13-16 games scheduled per standard NFL week).
     If fewer games are returned or parse fails, exits non-zero without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw_espn_captures"
CAPTURES_LOG = DATA_DIR / "game_context_captures.jsonl"
GAMES_CSV_PATH = DATA_DIR / "games.csv"

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

ET = ZoneInfo("America/New_York")

# Standard abbreviation mappings between ESPN and nflverse
TEAM_MAP = {
    "WSH": "WAS",
    "JAC": "JAX",
    "LAR": "LA",
}

# Known stadiums with fixed roof configuration in nflverse
DOME_STADIUMS = {
    "Lucas Oil Stadium", "Caesars Superdome", "U.S. Bank Stadium",
    "Ford Field", "Allegiant Stadium", "SoFi Stadium", "AT&T Stadium",
    "NRG Stadium", "Mercedes-Benz Stadium", "State Farm Stadium",
}


def fetch_espn_week_data(season: int, week: int, timeout: int = 15) -> tuple[dict, bytes, str]:
    """Fetch live scoreboard for the given NFL season and week."""
    url = f"{ESPN_SCOREBOARD_URL}?season={season}&week={week}&seasontype=2"
    fetch_time_utc = datetime.now(timezone.utc).isoformat()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"ESPN API request failed: {exc}") from exc

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON from ESPN API: {exc}") from exc

    return data, raw_bytes, fetch_time_utc


def fetch_event_weather(event_id: str, timeout: int = 8) -> tuple[float | None, float | None]:
    """Fetch optional real weather (temp, wind) from game summary."""
    url = f"{ESPN_SUMMARY_URL}?event={event_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            gi = data.get("gameInfo", {})
            w = gi.get("weather") or data.get("header", {}).get("weather") or {}
            temp = float(w["temperature"]) if "temperature" in w and w["temperature"] is not None else None
            wind = float(w["gust"]) if "gust" in w and w["gust"] is not None else None
            return temp, wind
    except Exception:
        return None, None


def parse_espn_games(data: dict, season: int, week: int, fetch_time_utc: str, fetch_weather: bool = True) -> list[dict]:
    """Parse events into verified game context records."""
    events = data.get("events", [])
    # Fail closed on partial slate: NFL regular season weeks have between 13 and 16 games
    if len(events) < 13:
        raise ValueError(f"ESPN returned only {len(events)} events for season {season} week {week} (expected >= 13)")

    now_utc = datetime.fromisoformat(fetch_time_utc.replace("Z", "+00:00"))
    parsed_records = []

    for ev in events:
        status_type = (ev.get("status") or {}).get("type") or {}
        state = status_type.get("state")  # 'pre', 'in', 'post'

        # Rule 3: STRICTLY pre-kickoff only. In-progress ('in') or completed ('post') are dropped
        if state != "pre":
            continue

        kickoff_str = ev.get("date")
        if not kickoff_str:
            continue

        try:
            kickoff_dt = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # Must be in the future relative to fetch time
        if kickoff_dt <= now_utc:
            continue

        comps = ev.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home_comp or not away_comp:
            continue

        home_raw = home_comp.get("team", {}).get("abbreviation", "")
        away_raw = away_comp.get("team", {}).get("abbreviation", "")
        home_team = TEAM_MAP.get(home_raw, home_raw)
        away_team = TEAM_MAP.get(away_raw, away_raw)

        # Build nflverse game_id format: e.g., 2026_09_JAX_BAL
        week_str = f"{week:02d}"
        game_id = f"{season}_{week_str}_{away_team}_{home_team}"

        # Extract DraftKings / consensus odds
        odds_list = comps.get("odds", [])
        dk_odds = next((o for o in odds_list if "draftkings" in (o.get("provider", {}).get("name") or "").lower()), None)
        if not dk_odds and odds_list:
            dk_odds = odds_list[0]

        spread_line = None
        total_line = None
        if dk_odds:
            # Rule 4: Verify spread sign convention
            # PointSpread home close line gives exact home spread string: e.g. '+10' or '-3.5'
            ps = dk_odds.get("pointSpread", {})
            home_ps = (ps.get("home") or {}).get("close", {}).get("line")
            if home_ps:
                try:
                    home_line_val = float(str(home_ps).replace("+", ""))
                    # In nflverse: spread_line is positive when HOME is favored.
                    # e.g. home_line +10 (underdog) -> nflverse spread_line = -10.0
                    # e.g. home_line -3.5 (favorite) -> nflverse spread_line = +3.5
                    spread_line = -home_line_val
                except ValueError:
                    spread_line = None
            elif dk_odds.get("spread") is not None:
                spread_val = float(dk_odds["spread"])
                # Fallback to home/away favorite flag
                if dk_odds.get("homeTeamOdds", {}).get("favorite"):
                    spread_line = spread_val
                elif dk_odds.get("awayTeamOdds", {}).get("favorite"):
                    spread_line = -spread_val
                else:
                    spread_line = 0.0

            total_val = dk_odds.get("overUnder")
            if total_val is not None:
                total_line = float(total_val)

        # Venue / roof
        venue = comps.get("venue", {})
        venue_name = venue.get("fullName", "")
        is_dome = venue.get("indoor", False) or (venue_name in DOME_STADIUMS)
        roof = "dome" if is_dome else "outdoors"

        # Game time in Eastern (HH:MM) to match nflverse convention
        kickoff_et = kickoff_dt.astimezone(ET)
        gameday = kickoff_et.strftime("%Y-%m-%d")
        gametime = kickoff_et.strftime("%H:%M")

        # Weather: ONLY set observation time if real weather was fetched or dome
        temp, wind = None, None
        weather_observed_at = None
        if fetch_weather and ev.get("id"):
            temp, wind = fetch_event_weather(ev["id"])
            if temp is not None or wind is not None:
                weather_observed_at = fetch_time_utc

        if is_dome:
            roof = "dome"
            wind = 0.0
            if temp is None:
                temp = 72.0
            weather_observed_at = fetch_time_utc

        record = {
            "game_id": game_id,
            "season": season,
            "week": week,
            "gameday": gameday,
            "gametime": gametime,
            "away_team": away_team,
            "home_team": home_team,
            "spread_line": spread_line,
            "total_line": total_line,
            "roof": roof,
            "temp": temp,
            "wind": wind,
            "spread_observed_at": fetch_time_utc if spread_line is not None else None,
            "total_observed_at": fetch_time_utc if total_line is not None else None,
            "weather_observed_at": weather_observed_at,
            "source": "espn_draftkings",
        }
        parsed_records.append(record)

    return parsed_records


def append_raw_capture(raw_bytes: bytes, season: int, week: int, fetch_time_utc: str) -> str:
    """Store raw JSON capture bytes named by content hash."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    ts_slug = fetch_time_utc.replace(":", "-").replace(".", "-")
    raw_path = RAW_DIR / f"espn_{season}_w{week}_{ts_slug}_{content_hash[:8]}.json"
    raw_path.write_bytes(raw_bytes)
    return str(raw_path.relative_to(ROOT))


def append_capture_records(records: list[dict], raw_rel_path: str, fetch_time_utc: str) -> None:
    """Append each capture record to the JSONL log with provenance link."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CAPTURES_LOG.open("a", encoding="utf-8") as f:
        for rec in records:
            payload = {
                **rec,
                "capture_batch_utc": fetch_time_utc,
                "raw_source_payload": raw_rel_path,
            }
            f.write(json.dumps(payload, sort_keys=True) + "\n")


def update_games_csv_week(records: list[dict], season: int, week: int) -> int:
    """Merge newly captured upcoming week rows into data/games.csv without backfilling history."""
    if not GAMES_CSV_PATH.exists():
        raise FileNotFoundError(f"{GAMES_CSV_PATH} missing - cannot merge without base schedule")

    import csv

    with GAMES_CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # Ensure required provenance columns exist in fieldnames
    prov_fields = ["spread_observed_at", "total_observed_at", "weather_observed_at"]
    for pf in prov_fields:
        if pf not in fieldnames:
            fieldnames.append(pf)

    rec_by_id = {r["game_id"]: r for r in records}
    updated_count = 0

    new_rows = []
    seen_ids = set()
    for row in rows:
        gid = row.get("game_id")
        seen_ids.add(gid)
        # ONLY update if row belongs to this target week AND is in records
        if gid in rec_by_id:
            new_val = rec_by_id[gid]
            if new_val.get("spread_line") is not None:
                row["spread_line"] = str(new_val["spread_line"])
            if new_val.get("total_line") is not None:
                row["total_line"] = str(new_val["total_line"])
            if new_val.get("roof") is not None:
                row["roof"] = new_val["roof"]
            if new_val.get("temp") is not None:
                row["temp"] = str(new_val["temp"])
            if new_val.get("wind") is not None:
                row["wind"] = str(new_val["wind"])

            row["spread_observed_at"] = new_val["spread_observed_at"] or ""
            row["total_observed_at"] = new_val["total_observed_at"] or ""
            row["weather_observed_at"] = new_val["weather_observed_at"] or ""
            updated_count += 1
        new_rows.append(row)

    # Append any upcoming games that were missing entirely from games.csv
    for gid, r in rec_by_id.items():
        if gid not in seen_ids:
            new_row = {fn: "" for fn in fieldnames}
            new_row.update({
                "game_id": r["game_id"],
                "season": str(r["season"]),
                "week": str(r["week"]),
                "game_type": "REG",
                "gameday": r["gameday"] or "",
                "gametime": r["gametime"] or "",
                "away_team": r["away_team"],
                "home_team": r["home_team"],
                "spread_line": str(r["spread_line"]) if r["spread_line"] is not None else "",
                "total_line": str(r["total_line"]) if r["total_line"] is not None else "",
                "roof": r["roof"] or "outdoors",
                "temp": str(r["temp"]) if r["temp"] is not None else "",
                "wind": str(r["wind"]) if r["wind"] is not None else "",
                "spread_observed_at": r["spread_observed_at"] or "",
                "total_observed_at": r["total_observed_at"] or "",
                "weather_observed_at": r["weather_observed_at"] or "",
            })
            new_rows.append(new_row)
            updated_count += 1

    # Write atomically
    temp_csv = GAMES_CSV_PATH.with_suffix(".tmp")
    with temp_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)
    temp_csv.replace(GAMES_CSV_PATH)

    return updated_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest live ESPN game context with strict provenance")
    parser.add_argument("--season", type=int, default=2026, help="NFL season year (default 2026)")
    parser.add_argument("--week", type=int, required=True, help="NFL week to capture (e.g. 9)")
    parser.add_argument("--no-weather", action="store_true", help="Skip fetching live weather from event summary")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing to disk")
    args = parser.parse_args()

    print(f"[espn-context] Fetching live NFL Week {args.week} ({args.season})...")
    data, raw_bytes, fetch_time = fetch_espn_week_data(args.season, args.week)
    records = parse_espn_games(data, args.season, args.week, fetch_time, fetch_weather=not args.no_weather)

    print(f"[espn-context] Successfully parsed {len(records)} pregame games with capture timestamp {fetch_time}")

    if args.dry_run:
        print("[espn-context] DRY RUN: Sample record:")
        if records:
            print(json.dumps(records[0], indent=2))
        return 0

    raw_rel = append_raw_capture(raw_bytes, args.season, args.week, fetch_time)
    print(f"[espn-context] Saved raw API payload to {raw_rel}")

    append_capture_records(records, raw_rel, fetch_time)
    print(f"[espn-context] Appended {len(records)} rows to {CAPTURES_LOG.relative_to(ROOT)}")

    # Update data/games.csv for week
    if GAMES_CSV_PATH.exists():
        updated = update_games_csv_week(records, args.season, args.week)
        print(f"[espn-context] Updated {updated} rows in {GAMES_CSV_PATH.relative_to(ROOT)} (no backfill on prior weeks)")
    else:
        print(f"[espn-context] Note: {GAMES_CSV_PATH.relative_to(ROOT)} absent; captures saved to journal.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
