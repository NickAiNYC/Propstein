"""Dataset assembly — fail-closed build, joins, DNP handling, pace."""

import pytest

from nba_model.data.dataset import build_dataset
from nba_model.data.providers import SyntheticSeasonProvider


def test_empty_rows_fail_closed():
    with pytest.raises(ValueError):
        build_dataset([], [])


def test_synthetic_dataset_shape_and_joins(synthetic_world):
    df, meta = synthetic_world["df"], synthetic_world["meta"]
    assert meta["n_rows"] > 0
    assert meta["n_games"] > 0
    assert meta["all_fixture"] is True
    assert meta["source"] == "synthetic_season"
    # opponent filled for every row (synthetic rows ship opponent="" upstream)
    assert df["opponent"].notna().all() and (df["opponent"] != "").all()
    # opponent always differs from own team
    assert (df["team"] != df["opponent"]).all()
    # margin + pace aggregates present
    assert df["margin"].notna().all()
    assert df["pace_ratio"].notna().all()
    assert meta["league_avg_poss"] > 0


def test_dnp_rows_flagged():
    provider = SyntheticSeasonProvider(start_date="2026-10-19", n_days=6, seed=11)
    world = provider.fetch_range(None)
    # inject a DNP row explicitly (generator emits played rows or omits)
    dnp_row = dict(world["rows"][0])
    dnp_row.update(minutes=0.0, pts=None, player_id="syn-dnp-test")
    df, _ = build_dataset(world["rows"] + [dnp_row], world["games"])
    row = df[df["player_id"] == "syn-dnp-test"].iloc[0]
    assert bool(row["dnp"]) is True
    assert row["ppm"] != row["ppm"]  # NaN


def test_provider_determinism():
    a = SyntheticSeasonProvider("2026-10-19", n_days=4, seed=42).fetch_range(None)
    b = SyntheticSeasonProvider("2026-10-19", n_days=4, seed=42).fetch_range(None)
    assert a["rows"] == b["rows"]
    assert a["odds"] == b["odds"]


def test_all_rows_carry_fixture_flag(synthetic_world):
    df = synthetic_world["df"]
    assert df["_fixture"].all()
    assert (df["source"] == "synthetic_season").all()
