import numpy as np
import pytest
from src.research.pit import (
    compute_pit_continuous,
    compute_randomized_pit_discrete,
    evaluate_pit_uniformity,
)


def test_perfect_uniform_pit():
    # Exactly uniform points
    u = np.linspace(0.005, 0.995, 200)
    rep = evaluate_pit_uniformity(u, market="receiving_yards")
    assert rep.n_samples == 200
    assert rep.is_uniform_at_05 is True
    assert rep.shape_diagnosis == "CALIBRATED_UNIFORM_SHAPE"
    assert len(rep.decile_frequencies) == 10
    for f in rep.decile_frequencies:
        assert 0.08 <= f <= 0.12


def test_underdispersed_light_tails_diagnosis():
    # Points bunched at the extremes (0.01 and 0.99)
    u = np.concatenate([
        np.full(50, 0.02),
        np.full(50, 0.98),
        np.linspace(0.1, 0.9, 100),
    ])
    rep = evaluate_pit_uniformity(u, market="receiving_yards")
    assert rep.is_uniform_at_05 is False
    assert "UNDERDISPERSED_LIGHT_TAILS" in rep.shape_diagnosis


def test_randomized_pit_discrete_in_range():
    # Poisson CDF dummy
    def dummy_cdf(y, lam=3.0):
        from scipy.stats import poisson
        return poisson.cdf(y, mu=lam)

    actuals = [0, 1, 2, 3, 4, 5, 6]
    params = [{"lam": 3.0} for _ in actuals]
    u = compute_randomized_pit_discrete(actuals, dummy_cdf, params)
    assert len(u) == len(actuals)
    assert np.all(u >= 0.0)
    assert np.all(u <= 1.0)
