"""Scoring contracts: Brier, calibration, deltas, settlement exclusion."""

from __future__ import annotations

import math

from pipeline.scoring import (
    calibration_table,
    delta_vs_previous,
    simulate_settlement,
)


def test_brier_perfect_forecaster():
    brier, rows = calibration_table([(0.0, 0), (1.0, 1), (0.0, 0)])
    assert brier == 0.0
    assert rows


def test_brier_chance_forecaster():
    n = 10_000
    # p=0.5 with balanced outcomes -> expected Brier 0.25
    pairs = [(0.5, i % 2) for i in range(n)]
    brier, _ = calibration_table(pairs)
    assert abs(brier - 0.25) < 0.01


def test_brier_worst_forecaster():
    brier, _ = calibration_table([(0.0, 1), (1.0, 0)])
    assert brier == 1.0


def test_calibration_decile_buckets():
    rows = calibration_table(
        [(0.05, 0), (0.15, 0), (0.25, 1), (0.35, 0), (0.45, 1), (0.55, 0), (0.65, 1), (0.75, 1), (0.85, 1), (0.95, 1)]
    )[1]
    assert len(rows) >= 8
    for r in rows:
        assert 0.0 <= r.predicted <= 1.0
        assert 0.0 <= r.observed <= 1.0
        assert r.n >= 1


def test_empty_calibration():
    brier, rows = calibration_table([])
    assert brier is None
    assert rows == []


def test_settlement_deterministic_and_exclusive():
    a = simulate_settlement("K1", "2026-11-05", 52.5, 0.55)
    b = simulate_settlement("K1", "2026-11-05", 52.5, 0.55)
    assert a == b
    status, result = a
    assert status in ("settled", "push", "void", "dnp")
    if status == "settled":
        assert result in ("win", "loss")
    elif status == "push":
        assert result == "push"
    elif status == "void":
        assert result == "void"
    else:
        assert result is None


def test_settlement_truth_driven_by_market_not_model():
    """At extreme market fair probabilities the outcome follows the market."""
    wins = sum(
        1
        for i in range(300)
        if simulate_settlement(f"K{i}", "2026-11-05", 22.5, 0.95)[1] == "win"
    )
    losses = sum(
        1
        for i in range(300)
        if simulate_settlement(f"L{i}", "2026-11-05", 22.5, 0.05)[1] == "loss"
    )
    assert wins > 240  # ~95% minus exclusions
    assert losses > 240


def test_delta_stats_counts():
    from pipeline.schemas import PredictionRecord
    from pipeline.tests.fixtures import minimal_prediction

    prev = [minimal_prediction("A"), minimal_prediction("B")]
    curr = [minimal_prediction("A"), minimal_prediction("C")]
    stats = delta_vs_previous(curr, prev)
    assert stats.n_compared == 1  # A only (B missing numbers? no — A has numbers)
    assert stats.n_new == 1  # C
    assert stats.n_dropped == 1  # B


def test_delta_stats_no_previous():
    from pipeline.tests.fixtures import minimal_prediction

    curr = [minimal_prediction("A")]
    stats = delta_vs_previous(curr, None)
    assert stats.n_compared == 0
    assert stats.n_new == 1
    assert stats.n_dropped == 0
    assert stats.mean_abs_delta_pp is None
