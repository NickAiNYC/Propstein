"""Confirmed nonparticipants cannot be treated as eligible NFL props."""

import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from src.slate import availability_eligible, confirmed_inactive_ids


class AvailabilityGateTests(unittest.TestCase):
    def test_official_and_injury_exclusions_apply_after_week_one(self):
        slate = pd.DataFrame([
            {"player_id": "out", "status": "ACT"},
            {"player_id": "official", "status": "ACT"},
            {"player_id": "reserve", "status": "RES"},
            {"player_id": "active", "status": "ACT"},
        ])
        result = availability_eligible(slate, {"out"}, {"official"})
        self.assertEqual(result.excl_reason.tolist(), [
            "injury: out/doubtful", "official inactive", "not on active roster", "",
        ])

    def test_week_eight_official_snapshot_contains_breece_hall(self):
        self.assertIn("00-0038120", confirmed_inactive_ids(2026, 8))
        self.assertEqual(confirmed_inactive_ids(2026, 9), set())


if __name__ == "__main__":
    unittest.main()
