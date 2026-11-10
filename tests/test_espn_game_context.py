"""tests/test_espn_game_context.py — Verification of ESPN/DraftKings game context ingestion contract."""

from __future__ import annotations

import csv
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from scripts.ingest_espn_game_context import (
    evaluate_pricing_context,
    ingest_week,
    parse_espn_games,
    select_authoritative,
    update_games_csv_week,
    weather_values_ok,
)
from src.features import UnverifiedGameContextError, attach_game_context


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
    del slate["events"][1]
    fetch_time = "2026-11-03T16:00:00+00:00"

    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    kc_nyj = next(r for r in records if r["game_id"] == "2026_09_NYJ_KC")
    assert kc_nyj["spread_line"] == 3.5


def test_spread_sign_uses_signed_home_spread_not_favorite_magnitude():
    """ESPN ``spread`` is already home-relative. Home favorite -7 must become +7.

    The old favorite-flag path treated that signed number as a magnitude and
    stored -7 when ``homeTeamOdds.favorite`` was true. Negating the signed
    value is the mapping that matches nflverse.
    """
    slate = _make_full_slate()
    ev = _make_sample_event(home_team="KC", away_team="NYJ")
    del slate["events"][1]
    ev["competitions"][0]["odds"][0]["pointSpread"] = {}
    ev["competitions"][0]["odds"][0]["spread"] = -7.0
    ev["competitions"][0]["odds"][0]["homeTeamOdds"] = {"favorite": True}
    ev["competitions"][0]["odds"][0]["awayTeamOdds"] = {"favorite": False}
    slate["events"][0] = ev

    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(slate, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    kc = next(r for r in records if r["game_id"] == "2026_09_NYJ_KC")
    assert kc["spread_line"] == 7.0


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


def test_retractable_roof_is_closed_not_dome_and_does_not_invent_temperature():
    """Lucas Oil is retractable. Indoor=true is nflverse ``closed``, wind 0, no 72°F."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(
        venue_name="Lucas Oil Stadium",
        indoor=True,
        home_team="IND",
        away_team="DAL",
    )
    del slate["events"][-1]
    fetch_time = "2026-11-03T16:00:00+00:00"

    def outdoor_forecast(_event_id):
        return {"temp": 54.0, "wind": 18.0, "observed_at": "2026-11-03T16:05:00+00:00", "payload": b"{}"}

    records = parse_espn_games(
        slate, season=2026, week=9, fetch_time_utc=fetch_time,
        fetch_weather=True, weather_fetcher=outdoor_forecast,
    )
    closed = next(r for r in records if r["game_id"] == "2026_09_DAL_IND")
    assert closed["roof"] == "closed"
    assert closed["wind"] == 0.0
    assert closed["temp"] is None
    assert closed["weather_observed_at"] == fetch_time
    assert closed["weather_source"] == "espn_venue_enclosure"


def test_team_abbreviation_mapping_lar_to_la():
    """ESPN abbreviation LAR must map to nflverse LA so games.csv game_id matches."""
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(
        home_team="WAS",
        away_team="LAR",
    )
    del slate["events"][5]
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


def test_historical_week_record_cannot_stamp_week_8(tmp_path, monkeypatch):
    """A capture aimed at a week 1-8 row is refused even if the caller passes it."""
    games_csv = tmp_path / "games.csv"
    fieldnames = [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "away_team", "home_team", "spread_line", "total_line", "roof", "temp", "wind",
    ]
    row = {
        "game_id": "2026_08_BAL_BUF", "season": "2026", "week": "8", "game_type": "REG",
        "gameday": "2026-10-25", "gametime": "13:00", "away_team": "BAL", "home_team": "BUF",
        "spread_line": "2.5", "total_line": "47.5", "roof": "outdoors", "temp": "55.0", "wind": "10.0",
    }
    with games_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    from scripts import ingest_espn_game_context
    monkeypatch.setattr(ingest_espn_game_context, "GAMES_CSV_PATH", games_csv)
    with pytest.raises(ValueError, match="historical"):
        update_games_csv_week([{
            **row,
            "season": 2026,
            "week": 8,
            "spread_line": 9.0,
            "spread_observed_at": "2026-10-20T12:00:00+00:00",
            "total_observed_at": "2026-10-20T12:00:00+00:00",
            "weather_observed_at": "2026-10-20T12:00:00+00:00",
        }], season=2026, week=8)
    with games_csv.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))[0]
    assert saved["spread_line"] == "2.5"
    assert "spread_observed_at" not in saved or saved.get("spread_observed_at", "") == ""


SAVED_SCOREBOARD = (
    Path(__file__).resolve().parents[1]
    / "data/raw_espn_captures/espn_2026_w9_2026-11-04T02-32-10-165584+00-00_9cc6f2d0.json"
)

# Home-relative ESPN lines from that payload, negated into the nflverse sign.
# These match the nflverse 2026 week 9 spread_line column.
REAL_WEEK9_SPREADS = {
    "2026_09_JAX_BAL": -10.0,
    "2026_09_CIN_ATL": -3.0,
    "2026_09_DAL_IND": -6.0,
    "2026_09_NYJ_KC": 9.5,
    "2026_09_DET_MIA": -7.0,
    "2026_09_CLE_NO": 1.5,
    "2026_09_NYG_PHI": -3.5,
    "2026_09_LA_WAS": -5.5,
    "2026_09_DEN_CAR": -2.5,
    "2026_09_HOU_LAC": -4.5,
    "2026_09_GB_NE": 3.0,
    "2026_09_LV_SF": 10.0,
    "2026_09_ARI_SEA": 12.5,
    "2026_09_TB_CHI": 6.0,
    "2026_09_BUF_MIN": -3.5,
}


def test_real_scoreboard_spread_sign_kickoff_and_roofs():
    """The saved ESPN payload, not a hand-built odds object, drives the sign and roofs."""
    payload = json.loads(SAVED_SCOREBOARD.read_text(encoding="utf-8"))
    fetch_time = "2026-11-04T02:32:10+00:00"
    records = parse_espn_games(payload, season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False)
    by_id = {row["game_id"]: row for row in records}
    assert set(by_id) == set(REAL_WEEK9_SPREADS)
    for game_id, spread in REAL_WEEK9_SPREADS.items():
        assert by_id[game_id]["spread_line"] == spread
    ravens = by_id["2026_09_JAX_BAL"]
    assert ravens["gameday"] == "2026-11-05"
    assert ravens["gametime"] == "20:15"
    assert by_id["2026_09_DAL_IND"]["roof"] == "closed"  # Lucas Oil, retractable, indoor
    assert by_id["2026_09_HOU_LAC"]["roof"] == "dome"  # SoFi is a fixed roof in nflverse
    assert by_id["2026_09_CLE_NO"]["roof"] == "dome"
    assert by_id["2026_09_BUF_MIN"]["roof"] == "dome"
    assert by_id["2026_09_CIN_ATL"]["roof"] == "closed"  # Bernabéu roof was indoor
    assert by_id["2026_09_NYJ_KC"]["roof"] == "outdoors"
    for row in records:
        if row["weather_observed_at"] is not None:
            assert weather_values_ok(row)
        else:
            assert row["temp"] is None
            assert row["wind"] is None


def test_in_progress_game_is_absent_from_capture():
    slate = _make_full_slate()
    slate["events"][0]["status"]["type"]["state"] = "in"
    records = parse_espn_games(
        slate, season=2026, week=9, fetch_time_utc="2026-11-03T16:00:00+00:00", fetch_weather=False,
    )
    assert "2026_09_JAX_BAL" not in {row["game_id"] for row in records}


def test_unparsed_pregame_event_is_partial_and_raises():
    slate = _make_full_slate()
    slate["events"][3]["competitions"][0]["competitors"] = []
    with pytest.raises(ValueError, match="partial game list"):
        parse_espn_games(slate, season=2026, week=9, fetch_time_utc="2026-11-03T16:00:00+00:00")


def test_schedule_mismatch_is_partial():
    slate = _make_full_slate()
    expected = {_make_game_id(event) for event in slate["events"]}
    expected.add("2026_09_PIT_CIN")
    with pytest.raises(ValueError, match="partial game list"):
        parse_espn_games(
            slate, season=2026, week=9, fetch_time_utc="2026-11-03T16:00:00+00:00",
            fetch_weather=False, expected_game_ids=expected,
        )


def _make_game_id(event: dict) -> str:
    home = next(c["team"]["abbreviation"] for c in event["competitions"][0]["competitors"] if c["homeAway"] == "home")
    away = next(c["team"]["abbreviation"] for c in event["competitions"][0]["competitors"] if c["homeAway"] == "away")
    from scripts.ingest_espn_game_context import TEAM_MAP
    return f"2026_09_{TEAM_MAP.get(away, away)}_{TEAM_MAP.get(home, home)}"


def test_weather_stamp_requires_both_temp_and_wind_and_uses_summary_time():
    slate = _make_full_slate()
    fetch_time = "2026-11-03T16:00:00+00:00"
    summary_time = "2026-11-03T16:00:04+00:00"

    def temperature_only(_event_id):
        return {"temp": 60.0, "wind": None, "observed_at": summary_time}

    bare = parse_espn_games(
        slate, season=2026, week=9, fetch_time_utc=fetch_time,
        fetch_weather=True, weather_fetcher=temperature_only,
    )
    outdoor = next(row for row in bare if row["roof"] == "outdoors")
    assert outdoor["weather_observed_at"] is None
    assert outdoor["temp"] is None
    assert outdoor["wind"] is None

    def complete(_event_id):
        return {"temp": 61.0, "wind": 8.0, "observed_at": summary_time, "payload": b"{}"}

    full = parse_espn_games(
        slate, season=2026, week=9, fetch_time_utc=fetch_time,
        fetch_weather=True, weather_fetcher=complete,
    )
    outdoor = next(row for row in full if row["roof"] == "outdoors")
    assert outdoor["temp"] == 61.0
    assert outdoor["wind"] == 8.0
    assert outdoor["weather_observed_at"] == summary_time
    assert outdoor["spread_observed_at"] == fetch_time
    assert outdoor["weather_source"] == "espn_summary_gameinfo"


def test_open_retractable_roof_is_not_labeled_dome():
    slate = _make_full_slate()
    slate["events"][0] = _make_sample_event(
        venue_name="State Farm Stadium", indoor=False, home_team="ARI", away_team="SEA",
    )
    del slate["events"][10]
    records = parse_espn_games(
        slate, season=2026, week=9, fetch_time_utc="2026-11-03T16:00:00+00:00", fetch_weather=False,
    )
    card = next(row for row in records if row["game_id"] == "2026_09_SEA_ARI")
    assert card["roof"] == "open"
    assert card["weather_observed_at"] is None
    assert card["wind"] is None


def test_munich_stadium_classified_as_dome_per_nflverse():
    """FC Bayern Munich Stadium follows nflverse roof=dome and leaves weather unobserved."""
    slate = _make_full_slate(kickoff_utc="2026-11-15T14:30:00Z")
    slate["events"][0] = _make_sample_event(
        venue_name="FC Bayern Munich Stadium", indoor=False, home_team="DET", away_team="NE",
        kickoff_utc="2026-11-15T14:30:00Z",
    )
    del slate["events"][2]
    fetch_time = "2026-11-10T12:00:00+00:00"
    records = parse_espn_games(
        slate, season=2026, week=10, fetch_time_utc=fetch_time, fetch_weather=False,
    )
    munich = next(row for row in records if row["game_id"] == "2026_10_NE_DET")
    assert munich["roof"] == "dome"
    assert munich["wind"] is None
    assert munich["temp"] is None
    assert munich["weather_observed_at"] is None
    assert munich["weather_source"] is None


def test_later_post_cutoff_capture_does_not_replace_pregame_line(tmp_path, monkeypatch):
    games_csv = tmp_path / "games.csv"
    fieldnames = [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "away_team", "home_team", "spread_line", "total_line", "roof", "temp", "wind",
        "spread_observed_at", "total_observed_at", "weather_observed_at",
    ]
    early = "2026-11-04T12:00:00+00:00"
    row = {
        "game_id": "2026_09_NYJ_KC", "season": "2026", "week": "9", "game_type": "REG",
        "gameday": "2026-11-08", "gametime": "13:00", "away_team": "NYJ", "home_team": "KC",
        "spread_line": "9.5", "total_line": "47.5", "roof": "outdoors", "temp": "62", "wind": "10",
        "spread_observed_at": early, "total_observed_at": early, "weather_observed_at": early,
    }
    with games_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    from scripts import ingest_espn_game_context
    monkeypatch.setattr(ingest_espn_game_context, "GAMES_CSV_PATH", games_csv)
    late = "2026-11-08T20:00:00+00:00"  # after 13:00 ET kickoff
    update_games_csv_week([{
        "game_id": "2026_09_NYJ_KC", "season": 2026, "week": 9,
        "gameday": "2026-11-08", "gametime": "13:00",
        "away_team": "NYJ", "home_team": "KC",
        "spread_line": -1.0, "total_line": 60.0, "roof": "outdoors",
        "temp": 40.0, "wind": 30.0,
        "spread_observed_at": late, "total_observed_at": late, "weather_observed_at": late,
    }], season=2026, week=9)
    with games_csv.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))[0]
    assert saved["spread_line"] == "9.5"
    assert saved["spread_observed_at"] == early
    assert saved["weather_observed_at"] == early

    newer_pre = "2026-11-07T15:00:00+00:00"
    update_games_csv_week([{
        "game_id": "2026_09_NYJ_KC", "season": 2026, "week": 9,
        "gameday": "2026-11-08", "gametime": "13:00",
        "away_team": "NYJ", "home_team": "KC",
        "spread_line": 10.0, "total_line": 48.0, "roof": "outdoors",
        "temp": 58.0, "wind": 12.0,
        "spread_observed_at": newer_pre, "total_observed_at": newer_pre, "weather_observed_at": newer_pre,
    }], season=2026, week=9)
    with games_csv.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))[0]
    assert saved["spread_line"] == "10.0"
    assert saved["spread_observed_at"] == newer_pre
    assert saved["temp"] == "58.0"


def test_unmapped_journal_id_is_not_inserted_into_the_schedule(tmp_path, monkeypatch):
    """2026_09_LAR_WAS is the pre-mapping duplicate of 2026_09_LA_WAS and must not be added."""
    games_csv = tmp_path / "games.csv"
    fieldnames = [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "away_team", "home_team", "spread_line", "total_line", "roof", "temp", "wind",
    ]
    with games_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "game_id": "2026_09_LA_WAS", "season": "2026", "week": "9", "game_type": "REG",
            "gameday": "2026-11-08", "gametime": "13:00", "away_team": "LA", "home_team": "WAS",
            "spread_line": "", "total_line": "", "roof": "outdoors", "temp": "", "wind": "",
        })
    from scripts import ingest_espn_game_context
    monkeypatch.setattr(ingest_espn_game_context, "GAMES_CSV_PATH", games_csv)
    fetch = "2026-11-04T12:00:00+00:00"
    update_games_csv_week([
        {
            "game_id": "2026_09_LAR_WAS", "season": 2026, "week": 9,
            "gameday": "2026-11-08", "gametime": "13:00",
            "away_team": "LAR", "home_team": "WAS",
            "spread_line": -5.5, "total_line": 47.5, "roof": "outdoors",
            "temp": 59.0, "wind": 10.0,
            "spread_observed_at": fetch, "total_observed_at": fetch, "weather_observed_at": fetch,
        },
        {
            "game_id": "2026_09_LA_WAS", "season": 2026, "week": 9,
            "gameday": "2026-11-08", "gametime": "13:00",
            "away_team": "LA", "home_team": "WAS",
            "spread_line": -5.5, "total_line": 47.5, "roof": "outdoors",
            "temp": 59.0, "wind": 10.0,
            "spread_observed_at": fetch, "total_observed_at": fetch, "weather_observed_at": fetch,
        },
    ], season=2026, week=9)
    with games_csv.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))
    assert [row["game_id"] for row in saved] == ["2026_09_LA_WAS"]
    assert saved[0]["spread_observed_at"] == fetch


def test_authoritative_capture_ignores_empty_weather_stamp_and_inverted_older_line():
    early = "2026-11-03T21:04:34+00:00"
    later = "2026-11-04T02:32:10+00:00"
    chosen = select_authoritative([
        {
            "game_id": "2026_09_NYJ_KC", "season": 2026, "week": 9,
            "gameday": "2026-11-08", "gametime": "13:00",
            "spread_line": -9.5, "total_line": 47.5, "roof": "outdoors",
            "temp": None, "wind": None,
            "spread_observed_at": early, "total_observed_at": early, "weather_observed_at": early,
        },
        {
            "game_id": "2026_09_NYJ_KC", "season": 2026, "week": 9,
            "gameday": "2026-11-08", "gametime": "13:00",
            "spread_line": 9.5, "total_line": 47.5, "roof": "outdoors",
            "temp": 62.0, "wind": 10.0,
            "spread_observed_at": later, "total_observed_at": later, "weather_observed_at": later,
        },
    ])
    assert chosen["2026_09_NYJ_KC"]["spread_line"] == 9.5
    assert chosen["2026_09_NYJ_KC"]["weather_observed_at"] == later


def test_missing_observed_at_blocks_weekly_model_run():
    """A week-9 row without weather provenance cannot enter attach_game_context."""
    import pandas as pd

    fetch_time = "2026-11-03T16:00:00+00:00"
    records = parse_espn_games(
        _make_full_slate(), season=2026, week=9, fetch_time_utc=fetch_time, fetch_weather=False,
    )
    outdoor = next(row for row in records if row["roof"] == "outdoors")
    assert outdoor["weather_observed_at"] is None
    players = pd.DataFrame({
        "game_id": [outdoor["game_id"]],
        "team": [outdoor["away_team"]],
        "pricing_cutoff_timestamp": ["2026-11-08T18:00:00+00:00"],
    })
    games = pd.DataFrame([{
        "game_id": outdoor["game_id"],
        "home_team": outdoor["home_team"],
        "away_team": outdoor["away_team"],
        "spread_line": outdoor["spread_line"],
        "total_line": outdoor["total_line"],
        "roof": outdoor["roof"],
        "temp": outdoor["temp"],
        "wind": outdoor["wind"],
        "spread_observed_at": outdoor["spread_observed_at"],
        "total_observed_at": outdoor["total_observed_at"],
        "weather_observed_at": outdoor["weather_observed_at"],
    }])
    with pytest.raises(UnverifiedGameContextError):
        attach_game_context(players, games)


def test_http_error_writes_neither_journal_nor_games_csv(tmp_path, monkeypatch):
    import urllib.error
    from scripts import ingest_espn_game_context

    csv_path = tmp_path / "games.csv"
    original = "game_id,season,week,game_type\n2026_09_NYJ_KC,2026,9,REG\n"
    csv_path.write_text(original, encoding="utf-8")
    journal = tmp_path / "captures.jsonl"
    report = tmp_path / "report.json"

    def boom(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://site.api.espn.com", 503, "unavailable", hdrs=None, fp=None)

    monkeypatch.setattr(ingest_espn_game_context.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="ESPN API request failed"):
        ingest_week(
            2026, 9,
            games_csv=csv_path,
            journal_path=journal,
            raw_dir=tmp_path / "raw",
            report_path=report,
        )
    assert not journal.exists()
    assert csv_path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "raw").exists() or not any((tmp_path / "raw").iterdir())
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["ready_for_pricing"] is False
    assert body["failed_fetches"]
    assert body["games_ingested"] == 0


def test_provenance_report_blocks_when_pricing_window_lacks_weather():
    now = datetime.fromisoformat("2026-11-04T12:00:00-05:00")
    schedule = [{
        "game_id": "2026_09_NYJ_KC", "season": "2026", "week": "9", "game_type": "REG",
        "gameday": "2026-11-08", "gametime": "13:00",
        "away_team": "NYJ", "home_team": "KC",
        "spread_line": "9.5", "total_line": "47.5", "roof": "outdoors", "temp": "", "wind": "",
    }]
    journal = [{
        "game_id": "2026_09_NYJ_KC", "season": 2026, "week": 9,
        "gameday": "2026-11-08", "gametime": "13:00",
        "spread_line": 9.5, "total_line": 47.5, "roof": "outdoors",
        "temp": None, "wind": None,
        "spread_observed_at": "2026-11-04T15:00:00+00:00",
        "total_observed_at": "2026-11-04T15:00:00+00:00",
        "weather_observed_at": "2026-11-04T15:00:00+00:00",
        "capture_batch_utc": "2026-11-04T15:00:00+00:00",
    }]
    report = evaluate_pricing_context(schedule, journal, now, games_ingested=1)
    assert report["ready_for_pricing"] is False
    assert report["games_ingested"] == 1
    assert report["missing_timestamps"][0]["game_id"] == "2026_09_NYJ_KC"
    assert "weather_values" in report["missing_timestamps"][0]["missing"]

    journal[0]["temp"] = 62.0
    journal[0]["wind"] = 10.0
    ready = evaluate_pricing_context(schedule, journal, now, games_ingested=1)
    assert ready["ready_for_pricing"] is True
    assert ready["stale_captures"] == []

    stale_now = datetime.fromisoformat("2026-11-06T18:00:00-05:00")
    stale = evaluate_pricing_context(schedule, journal, stale_now, games_ingested=1)
    assert stale["ready_for_pricing"] is True
    assert stale["stale_captures"][0]["game_id"] == "2026_09_NYJ_KC"
