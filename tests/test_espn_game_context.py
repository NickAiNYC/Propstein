"""tests/test_espn_game_context.py — Verification of ESPN/DraftKings game context ingestion contract."""

from __future__ import annotations

import csv
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from scripts.ingest_espn_game_context import (
    parse_espn_games,
    update_games_csv_week,
)


def _make_sample_event(
    event_id: str = "401873037",
    name: str = "Jacksonville Jaguars at Baltimore Ravens",
    state: str = "pre",
    kickoff_utc: str = "2026-11-06T01:15Z",
    home_team: str = "BAL",
    away_team: str = "JAC",
    home_spread_line: str = "+10",
    over_under: float = 40.5,
    venue_name: str = "M&T Bank Stadium",
    indoor: bool = False,
) -> dict:
    return {
        "id": event_id,
        "name": name,
        "date": kickoff_utc,
        "status": {"type": {"state": state, "name": f"STATUS_{state.upper()}"}},
        "competitions": [
            {
                "venue": {"fullName": venue_name, "indoor": indoor},
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home_team}},
                    {"homeAway": "away", "team": {"abbreviation": away_team}},
                ],
                "odds": [
                    {
                        "provider": {"name": "DraftKings"},
                        "spread": abs(float(home_spread_line.replace("+", ""))),
                        "overUnder": over_under,
                        "pointSpread": {
                            "home": {"close": {"line": home_spread_line}},
                            "away": {"close": {"line": f"-{home_spread_line.replace('+', '')}"}},
                        },
                    }
                ],
            }
        ],
    }


def _make_full_slate(events_count: int = 14, kickoff_utc: str = "2026-11-06T01:15Z") -> dict:
    teams = [
        ("BAL", "JAC"), ("KC", "NYJ"), ("MIA", "DET"), ("NO", "CLE"),
        ("PHI", "NYG"), ("WAS", "LAR"), ("CAR", "DEN"), ("LAC", "HOU"),
        ("NE", "GB"), ("SF", "LV"), ("SEA", "ARI"), ("CHI", "TB"),
        ("MIN", "BUF"), ("IND", "DAL"),
    ]
    events = []
    for i, (home, away) in enumerate(teams[:events_count]):
        events.append(
            _make_sample_event(
                event_id=f"100{i:03d}",
                name=f"{away} at {home}",
                kickoff_utc=kickoff_utc,
                home_team=home,
                away_team=away,
            )
        )
    return {"events": events}


def test_spread_sign_conversion_home_underdog():
    """DraftKings +10 for home team means home is underdog -> nflverse spread_line is -10.0."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(home_spread_line="+10", home_team="BAL", away_team="JAX")
    fetch_time = "2026-11-03T16:00:00+00:00"

    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    bal_jax = next(r for r in records if r["game_id"] == "2026_09_JAX_BAL")
    assert bal_jax["spread_line"] == -10.0
    assert bal_jax["total_line"] == 40.5
    assert bal_jax["spread_observed_at"] == fetch_time
    assert bal_jax["total_observed_at"] == fetch_time


def test_spread_sign_conversion_home_favorite():
    """DraftKings -3.5 for home team means home is favored -> nflverse spread_line is +3.5."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(home_spread_line="-3.5", home_team="KC", away_team="NYJ")
    fetch_time = "2026-11-03T16:00:00+00:00"

    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    kc_nyj = next(r for r in records if r["game_id"] == "2026_09_NYJ_KC")
    assert kc_nyj["spread_line"] == 3.5


def test_spread_sign_conversion_fallback_favorite_flags():
    """Fallback when pointSpread home close is missing: uses awayTeamOdds.favorite."""
    slate = _make_full_slate()
    ev = _make_sample_event(home_team="BAL", away_team="JAC")
    # Strip pointSpread object
    ev["competitions"][0]["odds"][0]["pointSpread"] = {}
    ev["competitions"][0]["odds"][0]["spread"] = 7.0
    ev["competitions"][0]["odds"][0]["awayTeamOdds"] = {"favorite": True}
    slate["events"][0] = ev

    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    bal_jax = next(r for r in records if r["game_id"] == "2026_09_JAX_BAL")
    assert bal_jax["spread_line"] == -7.0


def test_pre_kickoff_filtering_drops_in_progress_and_completed():
    """Games in 'in' or 'post' state or already past kickoff are excluded."""
    slate = _make_full_slate()
    slate["events"][0]["status"]["type"]["state"] = "in"
    slate["events"][1]["status"]["type"]["state"] = "post"
    slate["events"][2]["date"] = "2026-11-01T12:00:00Z"  # Past kickoff

    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)

    record_ids = {r["game_id"] for r in records}
    assert slate["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] not in [r["home_team"] for r in records if r["game_id"].endswith("BAL")]
    assert len(records) == 11  # 14 minus 3 excluded games


def test_fail_closed_on_partial_slate():
    """If ESPN returns fewer than 13 events, raise ValueError and write nothing."""
    small_slate = _make_full_slate(events_count=10)
    with pytest.raises(ValueError, match="expected >= 13"):
        parse_espn_games(small_slate, season=2026, week=9, fetch_time_utc="2026-11-03T16:00:00+00:00")


def test_weather_provenance_honesty_outdoors_no_weather():
    """Outdoor games with no weather data must have None weather_observed_at (never fabricated)."""
    slate = _make_full_slate()
    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)

    outdoor = next(r for r in records if r["roof"] == "outdoors")
    assert outdoor["weather_observed_at"] is None
    assert outdoor["temp"] is None
    assert outdoor["wind"] is None


def test_weather_provenance_honesty_indoor_dome():
    """Indoor dome stadiums have roof='dome', wind=0.0, and verified weather_observed_at."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(
        venue_name="Lucas Oil Stadium",
        indoor=True,
        home_team="IND",
        away_team="DAL",
    )
    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)

    dome = next(r for r in records if r["game_id"] == "2026_09_DAL_IND")
    assert dome["roof"] == "dome"
    assert dome["wind"] == 0.0
    assert dome["temp"] == 72.0
    assert dome["weather_observed_at"] == fetch_time


def test_team_abbreviation_mapping_lar_to_la():
    """ESPN abbreviation LAR must map to nflverse LA so games.csv game_id matches."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(
        home_team="WAS",
        away_team="LAR",
    )
    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)

    la_was = next(r for r in records if r["game_id"] == "2026_09_LA_WAS")
    assert la_was["away_team"] == "LA"
    assert la_was["home_team"] == "WAS"


def test_timezone_conversion_to_eastern():
    """Kickoff 2026-11-06T01:15Z translates to Thursday 2026-11-05 at 20:15 Eastern."""
    slate = _make_full_slate()
    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)

    rec = records[0]
    assert rec["gameday"] == "2026-11-05"
    assert rec["gametime"] == "20:15"


def test_no_backfill_historical_weeks(tmp_path, monkeypatch):
    """update_games_csv_week must leave historical weeks (1-8) completely un-timestamped."""
    games_csv = tmp_path / "games.csv"
    fieldnames = [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "away_team", "home_team", "spread_line", "total_line", "roof", "temp", "wind",
        "spread_observed_at", "total_observed_at", "weather_observed_at",
    ]

    initial_rows = [
        # Historical Week 8 game (must remain untouched)
        {
            "game_id": "2026_08_BAL_BUF", "season": "2026", "week": "8", "game_type": "REG",
            "gameday": "2026-10-25", "gametime": "13:00", "away_team": "BAL", "home_team": "BUF",
            "spread_line": "2.5", "total_line": "47.5", "roof": "outdoors", "temp": "55.0", "wind": "10.0",
            "spread_observed_at": "", "total_observed_at": "", "weather_observed_at": "",
        },
        # Upcoming Week 9 game (should be updated)
        {
            "game_id": "2026_09_JAX_BAL", "season": "2026", "week": "9", "game_type": "REG",
            "gameday": "2026-11-05", "gametime": "20:15", "away_team": "JAC", "home_team": "BAL",
            "spread_line": "", "total_line": "", "roof": "outdoors", "temp": "", "wind": "",
            "spread_observed_at": "", "total_observed_at": "", "weather_observed_at": "",
        },
    ]

    with games_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(initial_rows)

    from scripts import ingest_espn_game_context
    monkeypatch.setattr(ingest_espn_game_context, "GAMES_CSV_PATH", games_csv)

    fetch_time = "2026-11-03T16:00:00+00:00"
    records = [
        {
            "game_id": "2026_09_JAX_BAL",
            "season": 2026,
            "week": 9,
            "gameday": "2026-11-05",
            "gametime": "20:15",
            "away_team": "JAC",
            "home_team": "BAL",
            "spread_line": -10.0,
            "total_line": 40.5,
            "roof": "outdoors",
            "temp": 66.0,
            "wind": 7.0,
            "spread_observed_at": fetch_time,
            "total_observed_at": fetch_time,
            "weather_observed_at": fetch_time,
        }
    ]

    updated = update_games_csv_week(records, season=2026, week=9)
    assert updated == 1

    with games_csv.open("r", newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    w8 = reader[0]
    assert w8["game_id"] == "2026_08_BAL_BUF"
    # Zero backfill verification: historical timestamps MUST remain empty
    assert w8["spread_observed_at"] == ""
    assert w8["total_observed_at"] == ""
    assert w8["weather_observed_at"] == ""

    w9 = reader[1]
    assert w9["game_id"] == "2026_09_JAX_BAL"
    assert w9["spread_line"] == "-10.0"
    assert w9["total_line"] == "40.5"
    assert w9["spread_observed_at"] == fetch_time
    assert w9["total_observed_at"] == fetch_time
    assert w9["weather_observed_at"] == fetch_time
