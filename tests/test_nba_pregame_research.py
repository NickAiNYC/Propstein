"""Pregame bridge must not attach a FanDuel quote to the wrong player/game."""

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_nba_pregame_research.py"
spec = importlib.util.spec_from_file_location("nba_pregame_research", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_quote_identity_requires_current_game_team():
    history = pd.DataFrame([
        {"player_id": "nba-1", "player_display_name": "A. Player", "team": "BOS",
         "game_date": "2026-11-03", "game_id": "old-1", "dnp": False,
         "ppm": 0.5, "position": "G"},
        {"player_id": "nba-2", "player_display_name": "A. Player", "team": "NYK",
         "game_date": "2026-11-03", "game_id": "old-2", "dnp": False,
         "ppm": 0.6, "position": "G"},
    ])
    games = [{"game_id": "today-1", "gameday": "2026-11-04",
              "home_team": "NYK", "away_team": "MIA"}]
    quotes = [{"player_name": "A. Player", "player_id": "odds-name",
               "game_id": "today-1", "market": "points", "line": 12.5}]
    rows, mapped, excluded = bridge.pregame_rows(history, games, quotes, "2026-11-04")
    assert len(rows) == 1
    assert rows.iloc[0]["player_id"] == "nba-2"
    assert mapped[0]["player_id"] == "nba-2"
    assert excluded["ambiguous_identity"] == 0


def test_quote_identity_refuses_unknown_or_ambiguous_players():
    history = pd.DataFrame([
        {"player_id": f"nba-{n}", "player_display_name": "Same Name", "team": "NYK",
         "game_date": "2026-11-03", "game_id": f"old-{n}", "dnp": False,
         "ppm": 0.5, "position": "G"}
        for n in (1, 2)
    ])
    games = [{"game_id": "today-1", "gameday": "2026-11-04",
              "home_team": "NYK", "away_team": "MIA"}]
    quotes = [
        {"player_name": "Same Name", "game_id": "today-1", "market": "points", "line": 12.5},
        {"player_name": "Unknown", "game_id": "today-1", "market": "points", "line": 12.5},
    ]
    rows, mapped, excluded = bridge.pregame_rows(history, games, quotes, "2026-11-04")
    assert rows.empty and not mapped
    assert excluded["ambiguous_identity"] == 1
    assert excluded["unmatched_identity"] == 1
