"""Provider contracts — fail-closed auth, tier gates, pagination, rate limits.

The balldontlie transport is stubbed; nothing here touches the network.
"""

import pytest

from nba_model.data.providers import (
    BalldontlieProvider,
    MissingKeyError,
    ProviderNetworkError,
    RateLimitError,
    SyntheticSeasonProvider,
    TierError,
)


def _provider(transport, key="test-key", sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return BalldontlieProvider(
        api_key=key,
        transport=transport,
        sleep_fn=sleeps.append,
        spacing_seconds=0.0,
    )


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    provider = BalldontlieProvider(api_key=None)
    with pytest.raises(MissingKeyError):
        provider.fetch_range(["2026-11-01"])


def test_401_maps_to_missing_key():
    calls = []

    def transport(url):
        calls.append(url)
        return 401, {}

    with pytest.raises(MissingKeyError):
        _provider(transport).fetch_range(["2026-11-01"])
    assert len(calls) == 1


def test_402_403_maps_to_tier_error():
    def transport(url):
        return 402, {}

    with pytest.raises(TierError):
        _provider(transport).fetch_range(["2026-11-01"])


def test_429_rate_limit_exhausted():
    def transport(url):
        return 429, {}

    with pytest.raises(RateLimitError):
        _provider(transport).fetch_range(["2026-11-01"])


def test_429_then_success_after_retry():
    state = {"n": 0}

    def transport(url):
        state["n"] += 1
        if state["n"] == 1:
            return 429, {}
        return 200, {"data": []}

    world = _provider(transport).fetch_range(["2026-11-01"])
    assert state["n"] == 2
    assert world["rows"] == []


def test_500_maps_to_network_error():
    def transport(url):
        return 500, {}

    with pytest.raises(ProviderNetworkError):
        _provider(transport).fetch_range(["2026-11-01"])


def test_rate_limit_sleep_is_honoured():
    sleeps = []

    def transport(url):
        return 200, {"data": []}

    _provider(transport, sleeps=sleeps).fetch_range(["2026-11-01"])
    assert len(sleeps) >= 1  # spacing applied between calls


def test_stats_pagination_via_cursor():
    game_payload = {
        "data": [{
            "id": 55, "date": "2026-11-01T23:30:00Z", "status": "Final",
            "home_team": {"id": 1, "abbreviation": "ALP"},
            "visitor_team": {"id": 2, "abbreviation": "BRV"},
        }],
    }
    page1 = {
        "data": [{
            "player": {"id": 9, "first_name": "Test", "last_name": "One", "position": "G1"},
            "team": {"abbreviation": "ALP"},
            "game": {"id": 55},
            "min": "34:30", "pts": 24, "reb": 4, "ast": 6, "fg3m": 2,
            "fgm": 9, "fga": 18, "ftm": 4, "fta": 5, "oreb": 1, "tov": 2,
        }],
        "meta": {"next_cursor": "c2"},
    }
    page2 = {
        "data": [{
            "player": {"id": 10, "first_name": "Test", "last_name": "Two", "position": "W1"},
            "team": {"abbreviation": "BRV"},
            "game": {"id": 55},
            "min": "28:00", "pts": 15, "reb": 5, "ast": 2, "fg3m": 1,
            "fgm": 6, "fga": 14, "ftm": 2, "fta": 3, "oreb": 2, "tov": 1,
        }],
        "meta": {},
    }
    urls = []

    def transport(url):
        urls.append(url)
        if "/games?" in url:
            return 200, game_payload
        if "cursor=c2" in url:
            return 200, page2
        return 200, page1

    world = _provider(transport, sleeps=[]).fetch_range(["2026-11-01"])
    assert len(world["rows"]) == 2
    assert sum(1 for u in urls if "/stats?" in u and "cursor=c2" in u) == 1
    row = world["rows"][0]
    assert row["player_id"] == "bdl-9"
    assert row["minutes"] == pytest.approx(34.5)   # "34:30" -> 34 + 30/60
    assert row["team"] == "ALP" and row["opponent"] == "BRV"
    assert row["is_home"] is True
    assert row["_fixture"] is False and row["source"] == "balldontlie"
    assert world["meta"]["source"] == "balldontlie"


def test_synthetic_provider_flags_and_no_real_names():
    world = SyntheticSeasonProvider("2026-10-19", n_days=3, seed=5).fetch_range(None)
    assert world["meta"]["_fixture"] is True
    for row in world["rows"]:
        assert row["_fixture"] is True
    for q in world["odds"]:
        assert q["_fixture"] is True
        assert "synthetic" in q["source"].lower()
        # book names are synthetic, never real sportsbooks
        assert q["book"] in ("Book One", "Book Two")
    blob = str(world)
    for real in ("LeBron", "Curry", "Tatum", "DraftKings", "FanDuel"):
        assert real.lower() not in blob.lower()
