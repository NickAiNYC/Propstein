"""The live NBA pair is validated before either published artifact changes."""
import json
from pathlib import Path

import pytest

from scripts import fetch_nba


def nba_feeds():
    game = fetch_nba.normalize_game({
        "id": 123, "date": "2026-10-29T23:00:00Z",
        "home_team": {"abbreviation": "NYK"},
        "visitor_team": {"abbreviation": "BOS"},
    })
    row = fetch_nba.normalize_boxscore_row({
        "game": {"id": 123}, "player": {"id": 55, "first_name": "A", "last_name": "B"},
        "team": {"abbreviation": "NYK"}, "pts": 10,
    })
    return {
        "games": {"slate_key": "2026-10-29", "games": [game]},
        "boxscore": {"schema_version": "nba.v1", "_fixture": False,
                     "generated_at": "2026-10-29T12:00:00Z", "source": "balldontlie", "rows": [row]},
    }


def test_nba_valid_pair_publishes_manifests_and_preserves_viewer_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_nba, "VIEWER_DIR", str(tmp_path))
    games, boxscore = map(Path, fetch_nba.write_feeds(nba_feeds()))
    assert json.loads(games.read_text())[0]["_fixture"] is False
    assert json.loads(boxscore.read_text())["rows"][0]["_fixture"] is False
    assert games.with_name("nba_games_2026-10-29.manifest.json").exists()
    assert boxscore.with_name("nba_boxscore_2026-10-29.manifest.json").exists()


def test_nba_invalid_boxscore_leaves_existing_pair_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_nba, "VIEWER_DIR", str(tmp_path))
    games = tmp_path / "nba_games_2026-10-29.json"
    boxscore = tmp_path / "nba_boxscore_2026-10-29.json"
    games.write_text("old games")
    boxscore.write_text("old boxscore")
    feeds = nba_feeds()
    feeds["boxscore"]["rows"][0]["pts"] = -1
    with pytest.raises(ValueError):
        fetch_nba.write_feeds(feeds)
    assert games.read_text() == "old games"
    assert boxscore.read_text() == "old boxscore"
