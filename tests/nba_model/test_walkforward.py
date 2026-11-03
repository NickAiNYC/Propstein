"""Walk-forward harness — smoke + the two-layer no-leakage contract."""

import pandas as pd
import pytest

from nba_model.data.dataset import build_dataset
from nba_model.data.providers import SyntheticSeasonProvider
from nba_model.eval.walkforward import run_walk_forward


def test_walk_forward_smoke(synthetic_world):
    result = run_walk_forward(
        synthetic_world["df"],
        start_date="2026-11-02",
        end_date="2026-11-11",
        odds=synthetic_world["odds"],
        injuries=synthetic_world["injuries"],
    )
    assert len(result.records) > 0
    rec = result.records
    for col in ("date", "player_id", "line", "model_p", "market_p", "naive_p", "outcome"):
        assert col in rec.columns
    assert rec["model_p"].between(0, 1).all()
    assert rec["market_p"].between(0, 1).all()
    assert rec["outcome"].isin([0, 1]).all()
    assert result.summary["n"] == len(rec)
    assert result.distributional["n_player_games"] > 0


def test_no_leakage_future_rows_cannot_change_today(synthetic_world):
    """Running the harness for date d on the FULL dataset vs a dataset
    truncated at d must give identical model probabilities."""
    world = synthetic_world
    d = "2026-11-05"

    full = run_walk_forward(world["df"], d, d, odds=world["odds"])
    truncated_df = world["df"][world["df"]["game_date"] <= d]
    trunc = run_walk_forward(truncated_df, d, d, odds=world["odds"])

    def keyed(res):
        return {
            (r.player_id, round(float(r.line), 3)): round(float(r.model_p), 10)
            for r in res.records.itertuples()
        }

    assert len(full.records) > 0
    assert keyed(full) == keyed(trunc), "future rows changed today's predictions"


def test_leakage_detection_canary(synthetic_world):
    """Sanity: the harness DOES react when the training window itself is
    contaminated — otherwise test_no_leakage would be vacuous."""
    world = synthetic_world
    d = "2026-11-05"
    base = run_walk_forward(world["df"], d, d, odds=world["odds"])

    contaminated = world["df"].copy()
    # corrupt the LAST game before d for one quoted player
    quoted_player = base.records.iloc[0]["player_id"]
    pre_d = contaminated[
        (contaminated["player_id"] == quoted_player)
        & (contaminated["game_date"] < d)
        & (~contaminated["dnp"])
    ]
    assert len(pre_d) > 0
    idx = pre_d.index[-1]
    contaminated.loc[idx, "pts"] = contaminated.loc[idx, "pts"] + 40
    contaminated.loc[idx, "ppm"] = contaminated.loc[idx, "pts"] / max(
        contaminated.loc[idx, "minutes"], 1
    )

    altered = run_walk_forward(contaminated, d, d, odds=world["odds"])
    assert keyed(base) != keyed(altered), "harness ignored a real training change"


def keyed(res):
    return {
        (r.player_id, round(float(r.line), 3)): round(float(r.model_p), 10)
        for r in res.records.itertuples()
    }


def test_walk_forward_empty_window_raises(synthetic_world):
    with pytest.raises(ValueError):
        run_walk_forward(synthetic_world["df"], "2025-01-01", "2025-01-02")
