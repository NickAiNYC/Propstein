"""Calibration metrics — slope direction, Brier, small-sample honesty."""

import numpy as np
import pandas as pd
import pytest

from nba_model.eval.calibration import (
    brier,
    calibration_slope,
    log_loss,
    reliability_table,
    summarize,
)


def test_brier_perfect_and_awful():
    p = pd.Series([1.0, 0.0, 1.0, 0.0])
    y = pd.Series([1, 0, 1, 0])
    assert brier(p, y) == 0.0
    assert brier(1 - p, y) == 1.0


def test_log_loss_degenerates_are_clipped():
    p = pd.Series([1.0, 0.0])
    y = pd.Series([1, 0])
    assert log_loss(p, y) < 1e-3


def test_calibration_slope_near_one_for_well_specified(rng_seed=None):
    rng = np.random.default_rng(2026)
    n = 20000
    p = rng.uniform(0.2, 0.8, n)
    y = (rng.uniform(0, 1, n) < p).astype(float)
    slope = calibration_slope(pd.Series(p), pd.Series(y))
    assert slope == pytest.approx(1.0, abs=0.12)


def test_overconfident_predictions_have_slope_below_one():
    rng = np.random.default_rng(7)
    n = 20000
    p = rng.uniform(0.2, 0.8, n)
    # true probability is the SHRUNK version -> model is over-confident
    true_p = 0.5 + (p - 0.5) * 0.5
    y = (rng.uniform(0, 1, n) < true_p).astype(float)
    slope = calibration_slope(pd.Series(p), pd.Series(y))
    assert slope is not None and slope < 0.75


def test_slope_none_when_degenerate_or_tiny():
    assert calibration_slope(pd.Series([0.5] * 100), pd.Series([1] * 100)) is None
    assert calibration_slope(pd.Series([0.4] * 10), pd.Series([1] * 10)) is None


def test_reliability_table_bins_cover_all():
    rng = np.random.default_rng(3)
    p = pd.Series(rng.uniform(0.05, 0.95, 500))
    y = pd.Series((rng.uniform(0, 1, 500) < p).astype(float))
    table = reliability_table(p, y, bins=10)
    assert sum(b["n"] for b in table) == 500
    for b in table:
        assert 0 <= b["observed_freq"] <= 1


def test_summarize_small_sample_is_uncalibrated():
    records = pd.DataFrame({
        "model_p": [0.6] * 10, "market_p": [0.5] * 10,
        "naive_p": [0.5] * 10, "outcome": [1] * 6 + [0] * 4,
        "date": ["2026-01-01"] * 10,
    })
    summary = summarize(records)
    assert summary["uncalibrated"] is True
    assert summary["small_sample"] is True


def test_summarize_reports_market_delta_without_gating():
    rng = np.random.default_rng(11)
    records = pd.DataFrame({
        # model_p varies (a constant p would make the slope undefined and
        # flip the uncalibrated flag for the wrong reason)
        "model_p": rng.uniform(0.45, 0.75, 400),
        "market_p": np.full(400, 0.5), "naive_p": np.full(400, 0.5),
        # y ~ Bernoulli(0.5): the 0.5 market is well-calibrated, the biased
        # model is not -> model Brier must come out worse, reported not hidden.
        "outcome": (rng.uniform(0, 1, 400) < 0.5).astype(int),
        "date": ["2026-01-01"] * 400,
    })
    summary = summarize(records)
    assert summary["brier_vs_market"] is not None
    assert summary["brier_model"] > summary["brier_market"]  # worse — reported honestly
    assert summary["uncalibrated"] is False
