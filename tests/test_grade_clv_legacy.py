"""Legacy CLV reports must not claim independent verification or invent closes."""

import json
import tempfile
import unittest
from pathlib import Path

from src.grade_clv import grade_clv_snapshots


class LegacyClvHonestyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "snapshots.jsonl"
        self.output = Path(self.temp.name) / "report.json"
        self.trigger = {
            "snapshot_id": "SYN-1", "created_at": "2030-01-01T15:00:00+00:00",
            "player_id": "SYN-A", "player_name": "Synthetic A", "market": "receptions",
            "quote": {"status": "verified", "book": "SyntheticBook", "line": 4.5,
                      "over_odds": -110, "under_odds": -110,
                      "evaluation": {"best_side": "OVER", "is_qualified": True, "prob_edge": 0.2}},
        }

    def write(self, rows):
        self.source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return grade_clv_snapshots(self.source, self.output)

    def test_one_quote_is_not_its_own_close(self):
        report = self.write([self.trigger])
        self.assertEqual(report["summary"]["total_graded"], 0)
        self.assertIsNone(report["summary"]["verification_rate"])
        self.assertFalse(report["summary"]["immutable_ledger"])

    def test_missing_closing_odds_are_not_filled(self):
        later = json.loads(json.dumps(self.trigger))
        later["snapshot_id"] = "SYN-2"
        later["created_at"] = "2030-01-01T16:00:00+00:00"
        later["quote"].pop("over_odds")
        report = self.write([self.trigger, later])
        self.assertEqual(report["summary"]["total_graded"], 0)


if __name__ == "__main__":
    unittest.main()
