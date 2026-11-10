"""Odds math: implied probability, devig, American conversion."""

from __future__ import annotations

from fractions import Fraction

import pytest

from pipeline.odds import (
    american_from_probability,
    devig_two_way,
    exact_implied_probability,
    fair_probability_for_side,
    implied_probability,
    vig_fraction,
)


def test_implied_probability_plus_side():
    assert implied_probability(100) == 0.5
    assert implied_probability(150) == 0.4
    assert implied_probability(400) == 0.2


def test_implied_probability_minus_side():
    assert implied_probability(-100) == 0.5
    assert implied_probability(-110) == pytest.approx(0.52381, abs=1e-4)
    assert implied_probability(-400) == 0.8
    assert implied_probability(-115) == pytest.approx(0.5349, abs=1e-4)


def test_implied_probability_zero_rejected():
    with pytest.raises(ValueError):
        implied_probability(0)


def test_devig_two_way_normalizes():
    p_over, p_under = devig_two_way(-110, -110)
    assert p_over == pytest.approx(0.5, abs=1e-12)
    assert p_over + p_under == pytest.approx(1.0, abs=1e-12)


def test_devig_two_way_juiced_book():
    p_over, p_under = devig_two_way(-115, -105)
    assert p_over + p_under == pytest.approx(1.0, abs=1e-9)
    assert p_over > 0.5 > p_under
    assert vig_fraction(-115, -105) == pytest.approx(implied_probability(-115) + implied_probability(-105) - 1.0)


def test_fair_probability_for_side():
    assert fair_probability_for_side(-110, -110, "over") == pytest.approx(0.5, abs=1e-12)
    assert fair_probability_for_side(-110, -110, "under") == pytest.approx(0.5, abs=1e-12)


def test_exact_implied_probability_rational():
    assert exact_implied_probability(-110) == Fraction(110, 210)
    assert exact_implied_probability(150) == Fraction(100, 250)


def test_american_from_probability_roundtrip():
    for odds in (100, 150, 400, -110, -115, -300):
        p = implied_probability(odds)
        # roundtrip within one tick of quantization
        rebuilt = american_from_probability(p)
        assert abs(implied_probability(rebuilt) - p) < 0.006


def test_american_from_probability_extremes_clamped():
    # clamp bounds are 0.03 / 0.97 -> |odds| = 100*0.97/0.03 = 3233.33 -> 3233
    assert american_from_probability(0.99) == -3233
    assert american_from_probability(0.01) == 3233
