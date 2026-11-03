"""Rolling form — the shift(1) no-leakage guard is the contract under test."""

import numpy as np
import pandas as pd
import pytest

from nba_model.features.form import add_rolling_form


def test_form_excludes_current_game(small_frame):
    df = add_rolling_form(small_frame)
    p1 = df[df["player_id"] == "P1"].sort_values("game_date").reset_index(drop=True)
    # row 6: last 5 games are rows 1..5
    expected = p1.loc[1:5, "ppm"].mean()
    assert p1.loc[6, "form5_ppm"] == pytest.approx(expected)
    # row 0 has no history
    assert pd.isna(p1.loc[0, "form5_ppm"])
    assert p1.loc[0, "games_played"] == 0


def test_form_windows(small_frame):
    df = add_rolling_form(small_frame)
    p1 = df[df["player_id"] == "P1"].sort_values("game_date").reset_index(drop=True)
    assert p1.loc[7, "form10_ppm"] == pytest.approx(p1.loc[0:6, "ppm"].mean())
    # window 20 exceeds history: rolling min_periods=1 -> mean of all 7 prior
    assert p1.loc[8, "form20_ppm"] == pytest.approx(p1.loc[0:7, "ppm"].mean())


def test_thin_history_flag(small_frame):
    df = add_rolling_form(small_frame)
    p1 = df[df["player_id"] == "P1"].sort_values("game_date").reset_index(drop=True)
    assert bool(p1.loc[3, "thin_history"]) is True    # 3 prior games < 5
    assert bool(p1.loc[6, "thin_history"]) is False   # 6 prior games


def test_dnp_rows_get_no_history(small_frame):
    df = add_rolling_form(small_frame)
    dnp_row = df[df["player_id"] == "P2"].iloc[0]
    assert pd.isna(dnp_row["form5_ppm"])
    assert pd.isna(dnp_row["games_played"])


def test_future_rows_cannot_change_history(small_frame):
    """The leakage guard: appending a future game must not move any earlier
    row's history columns."""
    base = add_rolling_form(small_frame)
    extended = small_frame.copy()
    future = small_frame.iloc[[0]].copy()
    future["game_id"] = "g_future"
    future["game_date"] = "2026-02-28"
    future["ppm"] = 3.0  # absurd outlier
    extended = pd.concat([extended, future], ignore_index=True)
    after = add_rolling_form(extended)

    cols = [c for c in base.columns if c.startswith("form") or c == "games_played"]
    merged = base.merge(
        after, on=["player_id", "game_id"], suffixes=("_b", "_a")
    )
    for col in cols:
        b, a = merged[f"{col}_b"], merged[f"{col}_a"]
        assert np.allclose(b.astype(float), a.astype(float), equal_nan=True), col
