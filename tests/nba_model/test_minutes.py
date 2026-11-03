"""Expected-minutes model — blend, garbage trimming, fallbacks."""

import pandas as pd
import pytest

from nba_model.features.minutes import ExpectedMinutesModel


def _train_frame():
    rows = []
    # P1: 9 clean games at 30 min + 1 garbage blowout at 12 min
    for i in range(10):
        garbage = i == 9
        rows.append({
            "player_id": "P1", "game_id": f"g{i}",
            "game_date": f"2026-01-{i + 1:02d}", "team": "AAA",
            "opponent": "BBB", "position": "G1",
            "minutes": 12.0 if garbage else 30.0,
            "pts": 20.0, "ppm": 0.6, "margin": 30.0 if garbage else 5.0,
            "poss": 100.0, "dnp": False,
        })
    return pd.DataFrame(rows)


def test_recent_window_excludes_garbage():
    model = ExpectedMinutesModel().fit(_train_frame())
    params = model.player_params["P1"]
    assert params["recent_mean"] == pytest.approx(30.0)   # blowout excluded
    assert params["n_recent"] == 5
    assert params["season_mean"] == pytest.approx((9 * 30 + 12) / 10)


def test_blend_full_history():
    model = ExpectedMinutesModel().fit(_train_frame())
    test = _train_frame().iloc[[0]].assign(game_id="g_next", game_date="2026-01-20")
    out = model.predict(test)
    # w_eff = 0.5 with full recent history: 0.5*30 + 0.5*28.2
    assert out.iloc[0]["minutes_hat"] == pytest.approx(0.5 * 30.0 + 0.5 * 28.2)
    assert out.iloc[0]["minutes_source"] == "player_history"


def test_thin_recent_history_shrinks_toward_season():
    model = ExpectedMinutesModel().fit(_train_frame())
    model.player_params["P1"]["n_recent"] = 1  # simulate thin recent window
    test = _train_frame().iloc[[0]].assign(game_id="g_next")
    out = model.predict(test)
    w = 0.5 * (1 / 5)
    assert out.iloc[0]["minutes_hat"] == pytest.approx(w * 30 + (1 - w) * 28.2)


def test_position_fallback_for_unknown_player():
    model = ExpectedMinutesModel().fit(_train_frame())
    test = pd.DataFrame([{
        "player_id": "UNKNOWN", "game_id": "gX", "position": "G1",
        "team": "CCC", "opponent": "DDD", "game_date": "2026-01-20",
        "minutes": 0.0, "pts": 0.0, "ppm": None, "margin": 0.0,
        "poss": 100.0, "dnp": False,
    }])
    out = model.predict(test)
    assert out.iloc[0]["minutes_source"] == "position_fallback"
    # position mean over the train window (incl. the garbage game): 28.2
    assert out.iloc[0]["minutes_hat"] == pytest.approx((9 * 30 + 12) / 10)


def test_minutes_clipped_to_nba_bounds():
    model = ExpectedMinutesModel().fit(_train_frame())
    model.player_params["P1"]["season_mean"] = 55.0
    model.player_params["P1"]["recent_mean"] = 55.0
    model.player_params["P1"]["n_recent"] = 5
    test = _train_frame().iloc[[0]].assign(game_id="g_next")
    out = model.predict(test)
    assert out.iloc[0]["minutes_hat"] <= 48.0
