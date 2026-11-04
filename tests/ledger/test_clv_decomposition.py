import pytest
from src.ledger.clv_decomposition import (
    decompose_single_clv,
    summarize_cohort_decomposition,
)


def test_decompose_line_movement_positive():
    # Entered Over 76.5 at 0.50, closed at Over 78.5 at 0.55
    res = decompose_single_clv(
        signal_id="sig-1",
        entry_line=76.5,
        close_line=78.5,
        entry_implied_prob=0.50,
        close_devig_prob=0.55,
        side="OVER",
        hours_before_close=6.0,
    )
    assert res.total_clv_pp == 5.0
    # 2.0 yards * 2.5 pp/yard = 5.0 pp
    assert res.line_value_pp == 5.0
    assert res.price_value_pp == 0.0
    assert res.timing_attributed_pp > 0


def test_decompose_price_vig_positive_without_line_move():
    # Entered Over 76.5 at +110 (implied 0.476), closed at 76.5 at -125 (devig 0.53)
    res = decompose_single_clv(
        signal_id="sig-2",
        entry_line=76.5,
        close_line=76.5,
        entry_implied_prob=0.476,
        close_devig_prob=0.530,
        side="OVER",
    )
    assert abs(res.total_clv_pp - 5.4) < 1e-3
    assert res.line_value_pp == 0.0
    assert abs(res.price_value_pp - 5.4) < 1e-3


def test_summarize_cohort_decomposition():
    signals = [
        decompose_single_clv("s1", entry_line=70, close_line=72, entry_implied_prob=0.5, close_devig_prob=0.55),
        decompose_single_clv("s2", entry_line=70, close_line=70, entry_implied_prob=0.5, close_devig_prob=0.52),
    ]
    summary = summarize_cohort_decomposition(signals)
    assert summary.n_signals == 2
    assert summary.mean_total_clv_pp > 0
    assert summary.line_beat_rate == 0.5
    assert summary.price_beat_rate == 0.5
