"""
Focused Test Suite for Live Odds Ingestion Adapter & Snapshot Immutability
==========================================================================
Tests:
1. Matching & Normalization (exact names, suffixes, first initial + last name, punctuation).
2. Odds Conversion & Devigging (American -> Decimal, implied probs, multiplicative vig removal).
3. Push Handling Math (exact break-even formula and expected return on integer lines).
4. Qualification Policy (10% edge hurdle, positive EV, gating against Out/Doubtful injury).
5. Snapshot Immutability & Content Hashing (SHA-256 canonical RFC-8785 hash verification).
"""

import json
import unittest
from pathlib import Path

import numpy as np

import sys
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from odds_adapter import (
    NameNormalizer, american_to_decimal, american_to_implied_prob,
    devig_two_way, calculate_break_even_prob, calculate_expected_return,
    PropQuote, OddsIngestionAdapter
)
from freeze_slate import compute_canonical_hash


class TestOddsAdapter(unittest.TestCase):

    def setUp(self):
        self.mock_slate = [
            {"player_id": "00-0038621", "player_display_name": "DeMario Douglas", "team": "NE", "position": "WR", "mu_rec": 2.46, "mu_ypr": 12.2, "fair_line_yards": 24.5, "fair_line_rec": 2.5},
            {"player_id": "00-0033090", "player_display_name": "Hunter Henry", "team": "NE", "position": "TE", "mu_rec": 3.25, "mu_ypr": 9.88, "fair_line_yards": 27.0, "fair_line_rec": 2.5},
            {"player_id": "00-0035676", "player_display_name": "A.J. Brown", "team": "NE", "position": "WR", "mu_rec": 5.23, "mu_ypr": 12.98, "fair_line_yards": 61.0, "fair_line_rec": 4.5},
            {"player_id": "00-0037816", "player_display_name": "Romeo Doubs", "team": "NE", "position": "WR", "excl_reason": "injury: out/doubtful", "fair_line_yards": 26.5},
            {"player_id": "00-0031408", "player_display_name": "Mike Evans", "team": "SF", "position": "WR", "excl_reason": "injury: out/doubtful", "fair_line_yards": 46.5},
            {"player_id": "00-0036963", "player_display_name": "Amon-Ra St. Brown", "team": "DET", "position": "WR", "fair_line_yards": 113.0}
        ]

    # 1. Matching & Normalization Tests
    def test_name_matching_exact_and_variations(self):
        # Exact match
        p1 = NameNormalizer.match_player("DeMario Douglas", "NE", self.mock_slate)
        self.assertIsNotNone(p1)
        self.assertEqual(p1["player_id"], "00-0038621")

        # Punctuation & casing variation
        p2 = NameNormalizer.match_player("AJ Brown", "NE", self.mock_slate)
        self.assertIsNotNone(p2)
        self.assertEqual(p2["player_id"], "00-0035676")

        # First initial + last name
        p3 = NameNormalizer.match_player("H. Henry", "NE", self.mock_slate)
        self.assertIsNotNone(p3)
        self.assertEqual(p3["player_id"], "00-0033090")

        # Hyphenated / special character handling
        p4 = NameNormalizer.match_player("Amon-Ra St Brown", "DET", self.mock_slate)
        self.assertIsNotNone(p4)
        self.assertEqual(p4["player_id"], "00-0036963")

    # 2. Odds Conversion & Devigging Tests
    def test_american_to_decimal(self):
        # Minus odds (-110) -> 1.90909
        dec_minus = american_to_decimal(-110)
        self.assertAlmostEqual(dec_minus, 1.90909, places=4)

        # Plus odds (+150) -> 2.50
        dec_plus = american_to_decimal(150)
        self.assertAlmostEqual(dec_plus, 2.50, places=2)

        # Even money (+100) -> 2.00
        self.assertAlmostEqual(american_to_decimal(100), 2.00, places=2)

    def test_multiplicative_devig(self):
        # Balanced -110 / -110 line should de-vig exactly to 50% / 50%
        p_over, p_under = devig_two_way(-110, -110)
        self.assertAlmostEqual(p_over, 0.50, places=4)
        self.assertAlmostEqual(p_under, 0.50, places=4)

        # Asymmetric market (+100 / -120)
        p_over, p_under = devig_two_way(100, -120)
        self.assertAlmostEqual(p_over + p_under, 1.00, places=4)
        self.assertTrue(p_under > p_over)

    # 3. Push Handling Math Tests
    def test_break_even_and_push_probability(self):
        # At -110 with 0 push: BE = 1 / 1.90909 = 52.38%
        be_no_push = calculate_break_even_prob(-110, p_push=0.0)
        self.assertAlmostEqual(be_no_push, 0.5238, places=4)

        # Integer line with 5% push probability
        # On push stake is returned: BE = (1 - 0.05) / 1.90909 = 49.76%
        be_with_push = calculate_break_even_prob(-110, p_push=0.05)
        self.assertAlmostEqual(be_with_push, 0.4976, places=4)

        # Expected return test
        # If win prob = 0.55 at -110:
        ev = calculate_expected_return(0.55, -110, p_push=0.0)
        # EV = 0.55 * (1.90909 - 1) - 0.45 = 0.55 * 0.90909 - 0.45 = 0.5000 - 0.45 = +0.0500 (5%)
        self.assertAlmostEqual(ev, 0.0500, places=3)

    # 4. Qualification Policy & Gating Tests
    def test_injury_exclusion_gating(self):
        adapter = OddsIngestionAdapter.__new__(OddsIngestionAdapter)
        adapter.season = 2026
        adapter.week = 7
        adapter.slate_players = self.mock_slate
        adapter.injury_beneficiaries = {}
        from freeze_slate import ReceivingModel, MODEL_ALPHA, MODEL_K
        adapter.model = ReceivingModel(rec_params=None, ypr_params=None, alpha=MODEL_ALPHA, k=MODEL_K, means=None, sds=None, cols=None)

        # Quote for player with fatal injury exclusion (Romeo Doubs)
        quote = PropQuote(
            quote_id="test_inj_doubs",
            book="DraftKings",
            market="receiving_yards",
            player_raw_name="Romeo Doubs",
            team="NE",
            opponent="CHI",
            line=20.0,
            over_odds=-110,
            under_odds=-110,
            observed_at="2026-10-20T02:00:00Z",
            source="test"
        )
        ev = adapter.evaluate_quote(quote)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.status, "EXCLUDED")
        self.assertFalse(ev.is_qualified)
        self.assertEqual(ev.actionable_stake, 0.0)

    # 5. Snapshot Immutability & Deterministic Hash Tests
    def test_canonical_sha256_hash_immutability(self):
        payload_1 = {
            "snapshot_id": "test-uuid-1",
            "snapshot_type": "first_published",
            "game_id": "2026_07_NE_CHI",
            "player_id": "00-0038621",
            "line": 34.5,
            "odds": -110
        }
        # Keys in different insertion order must yield the EXACT same hash
        payload_2 = {
            "odds": -110,
            "line": 34.5,
            "player_id": "00-0038621",
            "game_id": "2026_07_NE_CHI",
            "snapshot_type": "first_published",
            "snapshot_id": "test-uuid-1"
        }
        hash_1 = compute_canonical_hash(payload_1)
        hash_2 = compute_canonical_hash(payload_2)
        self.assertEqual(hash_1, hash_2)
        self.assertEqual(len(hash_1), 64)


    # 6. Proxy Bandwidth Circuit Breaker Tests
    def test_proxy_bandwidth_budget_circuit_breaker(self):
        from odds_adapter import (
            PROXY_BYTES_BUDGET, proxy_bytes_used,
            get_proxy_bytes_used, reset_proxy_bytes, scrape_with_budget
        )
        import odds_adapter

        reset_proxy_bytes()
        self.assertEqual(get_proxy_bytes_used(), 0)

        # Mock provider returning byte content
        class MockProvider:
            def fetch(self, url):
                class MockResponse:
                    content = b"x" * 1000
                return MockResponse()

        provider = MockProvider()
        scrape_with_budget(provider, "https://example.com/test")
        self.assertEqual(get_proxy_bytes_used(), 1000)

        # Exceed budget manually and verify RuntimeError halt
        odds_adapter.proxy_bytes_used = PROXY_BYTES_BUDGET
        with self.assertRaises(RuntimeError) as ctx:
            scrape_with_budget(provider, "https://example.com/test2")
        self.assertIn("PROXY_BUDGET_EXCEEDED", str(ctx.exception))

        # Reset works cleanly
        reset_proxy_bytes()
        self.assertEqual(get_proxy_bytes_used(), 0)

    # 7. Fair-line and Volume Invariant Tests (Phase 1)
    def test_fair_line_and_projected_volume_invariants(self):
        adapter = OddsIngestionAdapter.__new__(OddsIngestionAdapter)
        adapter.season = 2026
        adapter.week = 7
        adapter.slate_players = self.mock_slate
        adapter.injury_beneficiaries = {}
        from freeze_slate import ReceivingModel, MODEL_ALPHA, MODEL_K
        adapter.model = ReceivingModel(rec_params=None, ypr_params=None, alpha=MODEL_ALPHA, k=MODEL_K, means=None, sds=None, cols=None)

        # Receiving yards quote: fair line is median yards, proj volume is mean yards (mu_rec * mu_ypr)
        quote_yds = PropQuote(
            quote_id="test_fair_inv_yds",
            book="DraftKings",
            market="receiving_yards",
            player_raw_name="DeMario Douglas",
            team="NE",
            opponent="CHI",
            line=24.5,
            over_odds=-110,
            under_odds=-110,
            observed_at="2026-10-20T02:00:00Z",
            source="test"
        )
        ev_yds = adapter.evaluate_quote(quote_yds)
        self.assertIsNotNone(ev_yds)
        self.assertEqual(ev_yds.fair_line, 24.5)  # median yards
        self.assertEqual(ev_yds.proj_volume, round(2.46 * 12.2, 2))  # mean volume: 30.01 != 24.5
        self.assertTrue(ev_yds.proj_volume > ev_yds.fair_line)  # right-skewed distribution property

        # Receptions quote: fair line must sit on nearest half-hook (.5), proj volume is mean rec (mu_rec)
        quote_rec = PropQuote(
            quote_id="test_fair_inv_rec",
            book="DraftKings",
            market="receptions",
            player_raw_name="DeMario Douglas",
            team="NE",
            opponent="CHI",
            line=2.5,
            over_odds=-110,
            under_odds=-110,
            observed_at="2026-10-20T02:00:00Z",
            source="test"
        )
        ev_rec = adapter.evaluate_quote(quote_rec)
        self.assertEqual(ev_rec.fair_line % 1.0, 0.5)  # hook alignment
        self.assertEqual(ev_rec.proj_volume, 2.46)  # mean receptions

    # 8. Quote Price Integrity (Phase 1 Invariant 3)
    def test_missing_or_zero_price_fails_closed(self):
        adapter = OddsIngestionAdapter.__new__(OddsIngestionAdapter)
        adapter.season = 2026
        adapter.week = 7
        adapter.slate_players = self.mock_slate
        adapter.injury_beneficiaries = {}
        from freeze_slate import ReceivingModel, MODEL_ALPHA, MODEL_K
        adapter.model = ReceivingModel(rec_params=None, ypr_params=None, alpha=MODEL_ALPHA, k=MODEL_K, means=None, sds=None, cols=None)

        # Quote with 0 over_odds and None under_odds must fail closed: no EV, no edge, status PASS
        quote_zero_price = PropQuote(
            quote_id="test_zero_price",
            book="DraftKings",
            market="receiving_yards",
            player_raw_name="DeMario Douglas",
            team="NE",
            opponent="CHI",
            line=24.5,
            over_odds=0,
            under_odds=None,
            observed_at="2026-10-20T02:00:00Z",
            source="test"
        )
        ev_zero = adapter.evaluate_quote(quote_zero_price)
        self.assertIsNotNone(ev_zero)
        self.assertFalse(ev_zero.is_qualified)
        self.assertEqual(ev_zero.actionable_stake, 0.0)
        self.assertEqual(ev_zero.prob_edge, 0.0)
        self.assertEqual(ev_zero.expected_return, 0.0)
        self.assertEqual(ev_zero.status, "PASS")


if __name__ == "__main__":
    unittest.main()

