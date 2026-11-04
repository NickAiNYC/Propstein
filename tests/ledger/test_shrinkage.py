import pytest
from src.ledger.shrinkage import (
    apply_hierarchical_shrinkage,
    calculate_empirical_bayes_weight,
    pool_segments,
)


def test_zero_sample_size_shrinks_completely_to_prior():
    est = apply_hierarchical_shrinkage(
        player_delta=0.15,
        sample_size=0,
        position_prior_delta=0.0,
        segment="WR1",
    )
    assert est.shrinkage_weight == 0.0
    assert est.shrunk_delta == 0.0


def test_infinite_sample_preserves_raw_delta():
    est = apply_hierarchical_shrinkage(
        player_delta=0.08,
        sample_size=100000,
        position_prior_delta=0.0,
        segment="WR1",
    )
    assert est.shrinkage_weight > 0.99
    assert abs(est.shrunk_delta - 0.08) < 1e-3


def test_intermediate_sample_balances_variance():
    w = calculate_empirical_bayes_weight(sample_size=4, within_variance=0.04, between_variance=0.01)
    # sigma^2 / n = 0.04 / 4 = 0.01. tau^2 = 0.01. w = 0.01 / (0.01 + 0.01) = 0.50
    assert abs(w - 0.50) < 1e-4

    est = apply_hierarchical_shrinkage(
        player_delta=0.10,
        sample_size=4,
        position_prior_delta=0.0,
        within_variance=0.04,
        between_variance=0.01,
    )
    assert est.shrinkage_weight == 0.5
    assert est.shrunk_delta == 0.05


def test_pool_segments():
    data = [
        {"segment": "WR1", "raw_delta": 0.06, "sample_size": 20},
        {"segment": "WR2", "raw_delta": -0.02, "sample_size": 10},
        {"segment": "TE", "raw_delta": 0.01, "sample_size": 5},
    ]
    pooled = pool_segments(data)
    assert len(pooled) == 3
    assert pooled["WR1"].shrinkage_weight > pooled["TE"].shrinkage_weight
