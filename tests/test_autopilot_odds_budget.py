from datetime import datetime

import pytest

from scripts import autopilot as ap

ET = ap.ET


def game(day, hour=13):
    return {"kickoff": datetime.fromisoformat(f"{day}T{hour:02d}:00").replace(tzinfo=ET)}


SUNDAY_MORNING = datetime(2026, 11, 15, 9, 0, tzinfo=ET)
GAMES = [game("2026-11-12", 20), game("2026-11-15", 13), game("2026-11-16", 20)]


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "k")


def test_game_day_with_credits_pulls():
    ok, why = ap.nfl_odds_pull_allowed(GAMES, SUNDAY_MORNING, lambda k: 5000)
    assert ok and "5000" in why


def test_low_balance_pauses_nfl_to_protect_nba():
    ok, why = ap.nfl_odds_pull_allowed(GAMES, SUNDAY_MORNING, lambda k: 300)
    assert not ok and "only 300" in why


def test_non_game_day_never_spends_or_even_checks():
    calls = []
    ok, _ = ap.nfl_odds_pull_allowed(GAMES, datetime(2026, 11, 13, 9, tzinfo=ET),
                                     lambda k: calls.append(k) or 5000)
    assert not ok and calls == []


def test_after_last_kickoff_of_the_day_skips():
    ok, _ = ap.nfl_odds_pull_allowed(GAMES, datetime(2026, 11, 16, 21, tzinfo=ET), lambda k: 5000)
    assert not ok


def test_unreadable_balance_or_missing_key_fails_closed(monkeypatch):
    assert not ap.nfl_odds_pull_allowed(GAMES, SUNDAY_MORNING, lambda k: None)[0]
    monkeypatch.delenv("ODDS_API_KEY")
    assert not ap.nfl_odds_pull_allowed(GAMES, SUNDAY_MORNING, lambda k: 5000)[0]


def test_run_model_only_passes_odds_flag_when_allowed(monkeypatch):
    seen = []

    class Done:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ap.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or Done())
    ap.run_model(2026, 11)
    ap.run_model(2026, 11, with_odds=True)
    assert "--odds" not in seen[0] and "--odds" in seen[1]
