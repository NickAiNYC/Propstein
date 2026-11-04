import pytest
from src.residual_model import (
    EMPIRICAL_BAND_TILT,
    get_probability_band,
    predict_market_residual,
)


def test_probability_bands_partition():
    assert get_probability_band(0.20) == "band_under_35"
    assert get_probability_band(0.40) == "band_35_45"
    assert get_probability_band(0.50) == "band_neutral_50"
    assert get_probability_band(0.60) == "band_55_65"
    assert get_probability_band(0.80) == "band_over_65"


def test_residual_at_neutral_starter_no_absence_defaults_to_market():
    pred = predict_market_residual(0.50, is_starter=True, teammate_vacated_targets=0.0)
    assert pred.residual_delta == 0.0
    assert pred.p_final == 0.50


def test_bench_player_penalized_on_high_probability():
    pred = predict_market_residual(0.55, is_starter=False)
    # Band 55-65 has +0.025, but non-starter has -0.040, net is negative
    assert pred.residual_delta < 0
    assert pred.role_adjustment < 0
    assert pred.p_final < 0.55


def test_teammate_absence_boosts_starter():
    pred_starter = predict_market_residual(0.50, is_starter=True, teammate_vacated_targets=0.15)
    assert pred_starter.absence_adjustment > 0
    assert pred_starter.residual_delta > 0
    assert pred_starter.p_final > 0.50


def test_regularization_shrinks_delta():
    low_reg = predict_market_residual(0.40, regularization_lambda=0.0)
    high_reg = predict_market_residual(0.40, regularization_lambda=4.0)
    assert abs(high_reg.residual_delta) < abs(low_reg.residual_delta)
