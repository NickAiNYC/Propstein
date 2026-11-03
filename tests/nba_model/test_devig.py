"""De-vig correctness — the market's honest probability is the benchmark."""

import pytest

from nba_model.eval.devig import (
    american_to_prob,
    devig_multiplicative,
    devig_power,
    group_quotes,
    market_consensus,
)


def test_american_to_prob_negative():
    assert american_to_prob(-110) == pytest.approx(110 / 210)


def test_american_to_prob_positive():
    assert american_to_prob(100) == pytest.approx(0.5)


def test_multiplicative_even_pair():
    p_over, p_under = devig_multiplicative(-110, -110)
    assert p_over + p_under == pytest.approx(1.0)
    assert p_over == pytest.approx(0.5)


def test_multiplicative_uneven_pair():
    p_over, _ = devig_multiplicative(100, -120)
    # raw: 0.5 / 0.5455 -> normalized ~0.4783
    assert p_over == pytest.approx(0.5 / 1.04545, rel=1e-3)


def test_power_devig_sums_to_one_and_favours_favourite_less():
    p_mul, _ = devig_multiplicative(-200, 170)
    p_pow, _ = devig_power(-200, 170)
    assert p_pow > p_mul, "power de-vig reduces favourite overpricing"
    pair = devig_power(-200, 170)
    assert sum(pair) == pytest.approx(1.0)


def test_group_quotes_matches_lines_exactly():
    quotes = [
        {"player_id": "A", "line": 28.5, "market": "points", "book": "B1"},
        {"player_id": "A", "line": 28.0, "market": "points", "book": "B2"},
        {"player_id": "A", "line": 28.5, "market": "points", "book": "B2"},
        {"player_id": "B", "line": 28.5, "market": "points", "book": "B1"},
        {"player_id": "A", "line": 6.5, "market": "rebounds", "book": "B1"},
    ]
    grouped = group_quotes(quotes, market="points")
    assert set(grouped.keys()) == {("A", 28.5), ("A", 28.0), ("B", 28.5)}
    assert len(grouped[("A", 28.5)]) == 2


def test_market_consensus_counts_distinct_books():
    quotes = [
        {"player_id": "A", "line": 28.5, "over_odds": -110, "under_odds": -110,
         "book": "B1", "source": "s1", "observed_at": "2026-11-01T22:00:00Z"},
        {"player_id": "A", "line": 28.5, "over_odds": -105, "under_odds": -115,
         "book": "B2", "source": "s2", "observed_at": "2026-11-01T22:04:00Z"},
        {"player_id": "A", "line": 28.5, "over_odds": -110, "under_odds": -110,
         "book": "B1", "source": "s1", "observed_at": "2026-11-01T22:02:00Z"},
    ]
    consensus = market_consensus(group_quotes(quotes)[("A", 28.5)])
    assert consensus["n_books"] == 2  # B1 twice, B2 once
    assert consensus["distinct_sources"] == 2
    assert consensus["latest_observed_at"] == "2026-11-01T22:04:00Z"
    assert 0 < consensus["p_over"] < 1
