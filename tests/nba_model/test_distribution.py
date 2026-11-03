"""PointsDistribution — tails, push mass, DNP mixing, floors."""

import math

import pytest
from scipy import stats as sps

from nba_model.model.distribution import PointsDistribution


def test_half_line_tail_matches_continuity_correction():
    d = PointsDistribution(mean=25.0, sd=6.0)
    # over 28.5 ⇔ X ≥ 29 ⇔ N > 28.5
    expected = float(sps.norm.sf((28.5 - 25.0) / 6.0))
    assert d.p_over(28.5) == pytest.approx(expected, abs=1e-12)


def test_integer_line_over_equals_next_half_line():
    d = PointsDistribution(mean=25.0, sd=6.0)
    # over 28 ⇔ X ≥ 29 ⇔ N > 28.5 — identical to over 28.5
    assert d.p_over(28) == pytest.approx(d.p_over(28.5), abs=1e-12)


def test_integer_line_mass_sums_to_one():
    d = PointsDistribution(mean=25.0, sd=6.0)
    total = d.p_over(28) + d.p_push(28) + d.p_under(28)
    assert total == pytest.approx(1.0, abs=1e-12)


def test_push_mass_matches_normal_interval():
    d = PointsDistribution(mean=25.0, sd=6.0)
    expected = float(
        sps.norm.cdf((28.5 - 25) / 6) - sps.norm.cdf((27.5 - 25) / 6)
    )
    assert d.p_push(28) == pytest.approx(expected, abs=1e-12)
    assert d.p_push(28.5) == 0.0


def test_p_over_monotone_decreasing_in_line():
    d = PointsDistribution(mean=22.0, sd=5.0)
    lines = [12.5, 15.5, 18.5, 21.5, 24.5, 27.5, 30.5, 33.5]
    probs = [d.p_over(l) for l in lines]
    assert all(a > b for a, b in zip(probs, probs[1:]))


def test_dnp_mass_rescales_tails_and_lands_under():
    d = PointsDistribution(mean=25.0, sd=6.0, dnp_prob=0.3)
    assert d.p_over(28) == pytest.approx(0.7 * float(sps.norm.sf((28.5 - 25) / 6)))
    # integer-line partition (over / push / under) preserves full mass
    assert d.p_over(28) + d.p_push(28) + d.p_under(28) == pytest.approx(1.0, abs=1e-9)
    # half-line partition (over / under, no push) preserves full mass
    assert d.p_over(28.5) + d.p_under(28.5) == pytest.approx(1.0, abs=1e-9)
    # DNP's 0 points is under any positive line...
    assert d.p_under(28.5) > 0.3
    # ...but not under a 0 line (0 < 0 is false)
    assert d.p_under(0) == 0.0


def test_sd_floor_enforced():
    d = PointsDistribution(mean=20.0, sd=1.0)
    assert d.sd == 4.0  # SD_FLOOR_PTS


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        PointsDistribution(mean=float("nan"), sd=5.0)
    with pytest.raises(ValueError):
        PointsDistribution(mean=20.0, sd=5.0, dnp_prob=1.5)
    with pytest.raises(ValueError):
        PointsDistribution(mean=-1.0, sd=5.0)


def test_fair_line_is_nearest_half_point_to_median():
    d = PointsDistribution(mean=25.0, sd=6.0)
    assert d.fair_line() == 25.0
    # exact 50/50 is unattainable on the integer grid — nearest line is close
    assert abs(d.p_over(d.fair_line()) - 0.5) < 0.05


def test_prob_to_american_even():
    d = PointsDistribution(mean=20.0, sd=5.0)
    assert d.prob_to_american(0.5, vig=0.0) == -100
