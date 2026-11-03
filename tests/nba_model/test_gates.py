"""Publish gates — every failure mode refuses loudly."""

import pandas as pd
import pytest

from nba_model import config
from nba_model.publish.gates import (
    evaluate_calibration_gate,
    evaluate_freshness_gate,
    evaluate_play_quote_gate,
)

NOW = pd.Timestamp("2026-11-11T22:50:00Z")


def _meta(max_date="2026-11-11"):
    return {"max_game_date": max_date, "source": "synthetic_season"}


def _quotes(observed="2026-11-11T22:45:00Z"):
    return [{"observed_at": observed, "book": "Book One"}]


# ── freshness ───────────────────────────────────────────────────────────────

def test_freshness_pass():
    report = evaluate_freshness_gate(_meta(), _quotes(), now=NOW)
    assert report.all_passed, report.fail_reasons


def test_freshness_boxscores_too_old():
    report = evaluate_freshness_gate(_meta("2026-11-05"), _quotes(), now=NOW)
    assert not report.all_passed
    assert any("boxscore_recency" in r for r in report.fail_reasons)


def test_freshness_quotes_missing_fails():
    report = evaluate_freshness_gate(_meta(), [], now=NOW)
    assert not report.all_passed


def test_freshness_quotes_stale():
    report = evaluate_freshness_gate(_meta(), _quotes("2026-11-11T20:00:00Z"), now=NOW)
    assert not report.all_passed
    assert any("quote_recency" in r for r in report.fail_reasons)


# ── calibration ─────────────────────────────────────────────────────────────

def _good_summary():
    return {
        "n": 500, "calibration_slope": 1.02,
        "brier_model": 0.210, "brier_naive": 0.240, "brier_market": 0.200,
        "brier_vs_market": 0.010, "uncalibrated": False,
    }


def test_calibration_gate_pass_with_market_ahead():
    report = evaluate_calibration_gate(_good_summary())
    assert report.all_passed, report.fail_reasons
    # the market comparison exists as a REPORTED check, never a veto
    reported = [c for c in report.checks if c.name == "brier_vs_market_REPORTED"]
    assert reported and reported[0].passed
    assert "market ahead" in reported[0].detail


def test_calibration_gate_small_n_fails():
    summary = _good_summary() | {"n": 100}
    report = evaluate_calibration_gate(summary)
    assert not report.all_passed


def test_calibration_gate_slope_out_of_band_fails():
    summary = _good_summary() | {"calibration_slope": 0.5}
    report = evaluate_calibration_gate(summary)
    assert not report.all_passed
    assert any("reliability_slope" in r for r in report.fail_reasons)


def test_calibration_gate_worse_than_naive_fails():
    summary = _good_summary() | {"brier_model": 0.30, "brier_naive": 0.24}
    report = evaluate_calibration_gate(summary)
    assert not report.all_passed
    assert any("brier_vs_naive" in r for r in report.fail_reasons)


# ── independent quotes ──────────────────────────────────────────────────────

def _consensus(books=("Book One", "Book Two"),
               observed="2026-11-11T22:45:00Z"):
    return {
        "n_books": len(set(books)), "books": list(books),
        "distinct_sources": len(set(books)),
        "latest_observed_at": observed,
    }


def test_play_quote_gate_single_book_fails():
    report = evaluate_play_quote_gate(_consensus(books=("Book One",)), now=NOW)
    assert not report.all_passed


def test_play_quote_gate_two_books_pass():
    report = evaluate_play_quote_gate(_consensus(), now=NOW)
    assert report.all_passed, report.fail_reasons


def test_play_quote_gate_stale_quotes_fail():
    report = evaluate_play_quote_gate(
        _consensus(observed="2026-11-11T20:00:00Z"), now=NOW
    )
    assert not report.all_passed


def test_edge_hurdle_and_board_size_are_explicit_config():
    # constants that the board relies on are pinned and documented
    assert config.BOARD_SIZE == 8
    assert 0 < config.EDGE_HURDLE < 0.5
    assert config.MIN_INDEPENDENT_BOOKS == 2
