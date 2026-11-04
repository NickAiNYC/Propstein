"""Historical game context cannot enter pricing without as-of evidence."""

from __future__ import annotations

import pandas as pd
import pytest
import sys
from types import SimpleNamespace

from scripts import autopilot
from scripts import build_player_photos
from src.features import (
    UnverifiedGameContextError,
    _prior_week_position_median,
    assert_context_known_at_cutoff,
    assert_inactive_timestamp_before_cutoff,
    attach_game_context,
)


def _player(cutoff: str = "2026-11-01T16:00:00Z") -> pd.DataFrame:
    return pd.DataFrame({
        "game_id": ["2026_08_BAL_BUF"],
        "team": ["BAL"],
        "pricing_cutoff_timestamp": [cutoff],
    })


def _game(observed: str = "2026-11-01T15:00:00Z") -> pd.DataFrame:
    return pd.DataFrame({
        "game_id": ["2026_08_BAL_BUF"],
        "home_team": ["BUF"],
        "away_team": ["BAL"],
        "spread_line": [2.5],
        "total_line": [47.5],
        "roof": ["outdoors"],
        "temp": [51.0],
        "wind": [8.0],
        "spread_observed_at": [observed],
        "total_observed_at": [observed],
        "weather_observed_at": [observed],
    })


def test_untimestamped_games_feed_cannot_prove_pregame_context() -> None:
    games = _game().drop(columns=["spread_observed_at", "total_observed_at", "weather_observed_at"])
    with pytest.raises(UnverifiedGameContextError, match="pricing_cutoff_timestamp"):
        attach_game_context(_player().drop(columns="pricing_cutoff_timestamp"), games)
    with pytest.raises(UnverifiedGameContextError, match="observed-at provenance"):
        attach_game_context(_player(), games)


def test_context_is_allowed_only_when_every_source_precedes_cutoff() -> None:
    result = attach_game_context(_player(), _game())
    assert result.loc[0, "implied_team_total"] == pytest.approx(22.5)
    assert result.loc[0, "wind"] == 8.0


@pytest.mark.parametrize("field", ["spread_observed_at", "total_observed_at", "weather_observed_at"])
def test_late_source_blocks_all_context(field: str) -> None:
    games = _game()
    games.loc[0, field] = "2026-11-01T16:00:01Z"
    with pytest.raises(UnverifiedGameContextError, match="after pricing cutoff"):
        assert_context_known_at_cutoff(_player(), games)


def test_naive_or_missing_source_time_blocks_context() -> None:
    for value in (None, "2026-11-01T15:00:00"):
        games = _game()
        games.loc[0, "weather_observed_at"] = value
        with pytest.raises(UnverifiedGameContextError):
            assert_context_known_at_cutoff(_player(), games)


def test_position_fallback_never_sees_same_week_or_future_values() -> None:
    rows = pd.DataFrame({
        "position": ["WR", "WR", "WR", "WR"],
        "season": [2026, 2026, 2026, 2026],
        "week": [1, 2, 2, 3],
        "f_adot": [8.0, 100.0, 200.0, 10.0],
    })
    medians = _prior_week_position_median(rows, "f_adot")
    assert pd.isna(medians.loc[0])
    assert medians.loc[1] == 8.0
    assert medians.loc[2] == 8.0
    assert medians.loc[3] == 100.0


def test_autopilot_blocks_model_when_game_feed_has_no_capture_times(tmp_path, monkeypatch) -> None:
    (tmp_path / "games.csv").write_text("game_id,spread_line,total_line,wind\nG1,2.5,47.5,8\n")
    monkeypatch.setattr(autopilot, "DATA", tmp_path)
    assert autopilot.game_context_has_capture_times() is False


def test_manifest_locks_cached_slate_when_model_was_blocked(tmp_path, monkeypatch) -> None:
    (tmp_path / "games_2026_w9.json").write_text(
        '[{"game_id":"2026_09_NE_KC","gameday":"2026-11-08","gametime":"13:00"}]'
    )
    (tmp_path / "slate_2026_w9.json").write_text("[]")
    monkeypatch.setattr(autopilot, "VIEWER", tmp_path)
    now = pd.Timestamp("2026-11-08T12:00:00-05:00").to_pydatetime()
    slate = autopilot.scan_nfl_slates(now, blocked_slate_key="2026_w9")["2026_w9"]
    assert slate["actionLocked"] is True
    assert slate["modelContextStatus"] == "BLOCKED_UNTIMESTAMPED"
    assert slate["picks"] is None
    assert slate["odds"] is None
    assert slate["livePicks"] is None


def test_schedule_only_slate_does_not_overwrite_frozen_research(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "VIEWER", tmp_path)
    path = autopilot.ensure_schedule_only_slate(2026, 9)
    assert path.read_text() == "[]\n"
    path.write_text('[{"existing":"frozen research"}]')
    autopilot.ensure_schedule_only_slate(2026, 9)
    assert path.read_text() == '[{"existing":"frozen research"}]'


def test_daily_autopilot_continues_schedule_without_model_or_picks(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    viewer = tmp_path / "viewer"
    data.mkdir()
    viewer.mkdir()
    (data / "games.csv").write_text("game_id,spread_line,total_line,wind\nG1,2.5,47.5,8\n")
    monkeypatch.setattr(autopilot, "DATA", data)
    monkeypatch.setattr(autopilot, "VIEWER", viewer)
    monkeypatch.setattr(autopilot, "FEEDS", viewer / "feeds")
    monkeypatch.setattr(autopilot, "ROOT", tmp_path)
    monkeypatch.setattr(autopilot, "refresh_feeds", lambda season: None)
    monkeypatch.setattr(autopilot, "refresh_game_context", lambda season, week: None)
    monkeypatch.setattr(autopilot, "run_model", lambda *args: pytest.fail("blocked model ran"))
    monkeypatch.setattr(autopilot, "load_schedule", lambda now: (2026, [{
        "game_id": "2026_09_NE_KC", "season_i": 2026, "week_i": 9,
        "gameday": "2026-11-08", "gametime": "13:00",
    }]))
    monkeypatch.setattr(autopilot, "week_span_label", lambda games: "Nov 8")

    def write_games(season, week, games):
        path = viewer / f"games_{season}_w{week}.json"
        path.write_text('[{"game_id":"2026_09_NE_KC","gameday":"2026-11-08","gametime":"13:00"}]')
        return path

    def write_injuries(season, week, games):
        path = viewer / f"injuries_{season}_w{week}.json"
        path.write_text('{"injuries":[]}')
        return path

    monkeypatch.setattr(autopilot, "write_games", write_games)
    monkeypatch.setattr(autopilot, "write_injuries", write_injuries)
    monkeypatch.setattr(autopilot, "fetch_nba_days", lambda now: None)
    monkeypatch.setattr(autopilot, "fetch_nba_odds_days", lambda now: None)
    monkeypatch.setattr(autopilot, "fetch_ufc", lambda now: None)
    monkeypatch.setattr(autopilot, "bump_build_hash_week", lambda week: [])
    monkeypatch.setattr(build_player_photos, "refresh", lambda: {"new": 0, "kept": 0, "unresolved": 0})
    monkeypatch.setattr(autopilot.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr(sys, "argv", ["autopilot.py", "--run"])
    monkeypatch.setenv("PROPWIRE_NOW", "2026-11-08T12:00:00-05:00")
    assert autopilot.main() == 0
    assert (viewer / "slate_2026_w9.json").read_text() == "[]\n"
    assert "Research board paused" in (viewer / "todays_board.html").read_text()
    assert (viewer / "injuries_2026_w9.json").exists()


def test_inactive_timestamp_before_cutoff_enforcement() -> None:
    player = pd.DataFrame({
        "game_id": ["2026_08_BAL_BUF"],
        "team": ["BAL"],
        "pricing_cutoff_timestamp": ["2026-11-01T16:00:00Z"],
    })

    # 1. Missing cutoff in player rows fails
    with pytest.raises(UnverifiedGameContextError, match="pricing_cutoff_timestamp"):
        assert_inactive_timestamp_before_cutoff(
            player.drop(columns=["pricing_cutoff_timestamp"]),
            pd.DataFrame({"team": ["BAL"], "inactive_report_timestamp": ["2026-11-01T15:30:00Z"]}),
        )

    # 2. Missing inactive report timestamp fails
    with pytest.raises(UnverifiedGameContextError, match="observed-at timestamp provenance"):
        assert_inactive_timestamp_before_cutoff(
            player,
            pd.DataFrame({"team": ["BAL"], "status": ["OUT"]}),
        )

    # 3. Post-cutoff inactive report timestamp fails closed
    with pytest.raises(UnverifiedGameContextError, match="after pricing cutoff"):
        assert_inactive_timestamp_before_cutoff(
            player,
            pd.DataFrame({"team": ["BAL"], "inactive_report_timestamp": ["2026-11-01T16:00:01Z"]}),
        )

    # 4. Pre-cutoff inactive report passes
    assert_inactive_timestamp_before_cutoff(
        player,
        pd.DataFrame({"team": ["BAL"], "inactive_report_timestamp": ["2026-11-01T15:30:00Z"]}),
    )
