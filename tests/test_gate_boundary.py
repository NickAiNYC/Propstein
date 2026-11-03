"""
Extreme-edge gate boundary test (audit follow-up to the provenance hotfix).

Why this exists: the bundled demo fixture USED to carry a +32% phantom-EV
quote (line 29.5 vs fair 45.5). The hotfix replaced that demo case with the
efficient-market case (edge 0.0) — correct for shipped data, but it removed
the only data point that exercised the qualification gate near its extreme.
No test had ever pinned that boundary explicitly. This file restores the
coverage with a clearly SYNTHETIC fixture (Player Z / SYN-Z / Synthetic
Book A) so no real player, book, or fixture is involved.

What it locks in (the integrity invariant from OddsIngestionAdapter.run_ingestion):
  1. The evaluator REPRESENTS extreme edges (prob_edge and expected_return
     far above the 10% EDGE_HURDLE).
  2. An UNVERIFIED quote can never qualify or carry a stake — even at an
     extreme edge (fail-closed).
  3. The same quote, verified, DOES qualify with a positive stake — proving
     the gate distinguishes rather than hard-failing everything.
  4. The EDGE_HURDLE itself gates qualification: a verified quote with a
     positive, above-half-hurdle but sub-hurdle edge (and positive EV) is
     LEAN with stake 0 — a positive edge alone never qualifies.

  Properties 2+3 prove VERIFICATION gates qualification; properties 3+4
  prove the EDGE THRESHOLD gates it too. Case selection is empirical and
  rerunnable: `python3 scripts/probe_gate_cases.py` (prints prob_edge /
  expected_return / status / stake for candidate lines and odds).
"""
import sys
import json
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from odds_adapter import PropQuote, OddsIngestionAdapter, EDGE_HURDLE


# Synthetic fixture — no real player, book, or observation (see module docstring).
SYN_SLATE = [{
    "player_id": "SYN-Z",
    "player_display_name": "Player Z",
    "team": "NE",
    "opponent_team": "CHI",
    "game_id": "2026_07_NE_CHI",
    "position": "WR",
    "mu_rec": 4.0,
    "mu_ypr": 11.0,
    "fair_line_rec": 6.5,     # model fair: 6.5 receptions
    "fair_line_yards": 55.0,
}]


def make_quote(verified: bool, line: float = 1.5, over_odds: int = -110,
               under_odds: int = -110) -> PropQuote:
    # Defaults: book line 1.5 vs fair 6.5 -> extreme positive edge on the OVER.
    return PropQuote(
        quote_id="test_gate_boundary_extreme",
        book="Synthetic Book A",
        market="receptions",
        player_raw_name="Player Z",
        team="NE",
        opponent="CHI",
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        observed_at="2026-10-20T06:00:00+00:00",
        source="Synthetic Book A Manual Entry (UNVERIFIED - test fixture)",
        verified=verified,
    )


def make_adapter(quote: PropQuote) -> OddsIngestionAdapter:
    """Adapter assembled via __new__ (same pattern as test_odds_adapter.py):
    no file IO, no model fit, side-effect methods stubbed at the instance."""
    a = OddsIngestionAdapter.__new__(OddsIngestionAdapter)
    a.season = 2026
    a.week = 7
    a.slate_players = SYN_SLATE
    a.injury_beneficiaries = {}
    a.model = None  # receptions market never touches the model
    a.provider = type("StubProvider", (), {
        "fetch_quotes": lambda self, season, week, game_id=None: [quote],
    })()
    captured = {}
    a.emit_snapshots = lambda evaluations: []
    a.export_live_feed = lambda evaluations: captured.update(evals=evaluations) or "unused"
    a._trigger_db_ingestion = lambda: None
    a._captured = captured
    return a


class TestExtremeEdgeGateBoundary(unittest.TestCase):

    def test_unverified_quote_is_preserved_with_unverified_status(self):
        """A rejected quote remains in the research record without promotion."""
        quote = make_quote(verified=False)
        a = make_adapter(quote)
        ev = a.evaluate_quote(quote)
        with tempfile.TemporaryDirectory() as folder:
            a.snapshots_dir = Path(folder) / "snapshots"
            a.viewer_dir = Path(folder) / "viewer"
            a.viewer_dir.mkdir()
            emitted = OddsIngestionAdapter.emit_snapshots(a, [ev])
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0]["quote"]["status"], "unverified")
            self.assertFalse(emitted[0]["quote"]["evaluation"]["is_qualified"])
            stored = json.loads((a.snapshots_dir / "snapshots_2026_w7.jsonl").read_text().strip())
            self.assertEqual(stored["content_hash"], emitted[0]["content_hash"])

    def test_evaluator_represents_extreme_edge(self):
        ev = make_adapter(make_quote(verified=False)).evaluate_quote(
            make_quote(verified=False))
        self.assertIsNotNone(ev)
        self.assertGreater(ev.prob_edge, 0.20,
                           "extreme fixture must produce a >20pt edge")
        self.assertGreater(ev.expected_return, 0.20)
        self.assertGreaterEqual(ev.prob_edge, EDGE_HURDLE)

    def test_unverified_extreme_edge_fail_closed(self):
        """THE invariant: no receipt, no stake — even at an extreme edge."""
        a = make_adapter(make_quote(verified=False))
        res = a.run_ingestion()
        self.assertEqual(res["matched_evaluations_count"], 1)
        self.assertEqual(res["qualified_count"], 0)
        (ev,) = a._captured["evals"]
        self.assertEqual(ev.status, "UNVERIFIED")
        self.assertFalse(ev.is_qualified)
        self.assertEqual(ev.actionable_stake, 0.0)

    def test_verified_extreme_edge_qualifies(self):
        """Same quote with a receipt: the boundary must distinguish."""
        a = make_adapter(make_quote(verified=True))
        res = a.run_ingestion()
        self.assertEqual(res["matched_evaluations_count"], 1)
        self.assertEqual(res["qualified_count"], 1)
        (ev,) = a._captured["evals"]
        self.assertEqual(ev.status, "QUALIFIED")
        self.assertTrue(ev.is_qualified)
        self.assertGreater(ev.actionable_stake, 0.0)

    def test_verified_sub_hurdle_edge_does_not_qualify(self):
        """THE THRESHOLD IS REAL: a verified quote with a positive edge BELOW
        EDGE_HURDLE must not qualify or carry a stake — even with positive
        expected return.

        Case shape: book line 2.5 at over -180 / under +150 vs model fair 6.5
        receptions. Precondition assertions below pin the threshold and the
        case's edge as separate numbers, so a reader sees the case is
        provably sub-hurdle (edge in [0.5*EDGE_HURDLE, EDGE_HURDLE)), not
        merely "small". Without this case, tests 2+3 above cannot
        distinguish "the threshold gates qualification" from "any positive
        edge qualifies once verified".
        """
        a = make_adapter(make_quote(verified=True, line=2.5,
                                    over_odds=-180, under_odds=150))
        res = a.run_ingestion()
        self.assertEqual(res["matched_evaluations_count"], 1)
        (ev,) = a._captured["evals"]
        # Preconditions: EV is positive, so only the EDGE threshold can gate
        # this quote; and the edge sits in the LEAN band — provably below the
        # hurdle, above half of it.
        self.assertGreater(ev.expected_return, 0)
        self.assertGreaterEqual(ev.prob_edge, 0.5 * EDGE_HURDLE)
        self.assertLess(ev.prob_edge, EDGE_HURDLE)
        # The property: sub-hurdle edge -> no qualification, no stake.
        self.assertEqual(res["qualified_count"], 0)
        self.assertEqual(ev.status, "LEAN")
        self.assertFalse(ev.is_qualified)
        self.assertEqual(ev.actionable_stake, 0.0)


if __name__ == "__main__":
    unittest.main()
