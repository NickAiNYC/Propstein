"""Propstein 2.0 worker selftest — offline sanity checks (no DATABASE_URL needed).

    python worker/selftest.py

Verifies: odds conversions, edge math, nameKey normalization, ingest arg
parsing, fail-closed exit codes for missing DATABASE_URL.
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from ev import american_to_decimal, compute_edge, decimal_to_american, prob_over  # noqa: E402
from ingest_props import name_key  # noqa: E402


class TestOdds(unittest.TestCase):
    def test_american_to_decimal(self):
        self.assertAlmostEqual(american_to_decimal(150), 2.50, places=6)
        self.assertAlmostEqual(american_to_decimal(-110), 1.909091, places=6)
        self.assertAlmostEqual(american_to_decimal(-3233), 1.030931, places=6)
        self.assertAlmostEqual(american_to_decimal(100), 2.0, places=6)

    def test_decimal_to_american(self):
        self.assertEqual(decimal_to_american(2.5), 150)
        self.assertEqual(decimal_to_american(1.9090909), -110)

    def test_roundtrip(self):
        for a in (-105, -110, -150, 100, 122, 488):
            self.assertEqual(decimal_to_american(american_to_decimal(a)), a)

    def test_prob_over_bounds(self):
        p = prob_over(113.5, 99.5, "receiving_yards")
        self.assertTrue(0.5 < p < 1.0)


class TestEdge(unittest.TestCase):
    def test_jsn_over(self):
        e = compute_edge(113.5, 99.5, "receiving_yards", -117, 113)
        self.assertEqual(e["best_side"], "OVER")
        self.assertAlmostEqual(e["prob_win"], 0.6794, places=3)
        self.assertGreater(e["ev"], 0)
        self.assertLessEqual(e["kelly"], 0.25)

    def test_juiced_line_is_minus_ev(self):
        # -3233 on a 91% win prob is still -EV
        e = compute_edge(41.0, 59.5, "receiving_yards", 122, -3233)
        self.assertEqual(e["best_side"], "UNDER")
        self.assertLess(e["ev"], 0)
        self.assertEqual(e["kelly"], 0.0)
        self.assertEqual(e["lean"], "PASS")

    def test_kelly_capped(self):
        e = compute_edge(113.5, 60.0, "receiving_yards", -110, -110)
        self.assertLessEqual(e["kelly"], 0.25)


class TestNameKey(unittest.TestCase):
    def test_diacritics(self):
        self.assertEqual(name_key("Nikola Jović"), name_key("Nikola Jovic"))

    def test_punctuation(self):
        self.assertEqual(name_key("P.J. Washington"), name_key("PJ Washington"))
        self.assertEqual(name_key("D'Andre Swift"), name_key("Dandre Swift"))

    def test_case(self):
        self.assertEqual(name_key("LeBron James"), "lebronjames")


class TestFailClosed(unittest.TestCase):
    def test_no_database_url_exits_2(self):
        env = dict(os.environ)
        env.pop("DATABASE_URL", None)
        for script in ("ingest_games.py", "ingest_players.py", "ingest_props.py"):
            path = os.path.join(os.path.dirname(__file__), script)
            r = subprocess.run([sys.executable, path], env=env, capture_output=True, timeout=30)
            self.assertEqual(r.returncode, 2, f"{script} should exit 2 without DATABASE_URL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
