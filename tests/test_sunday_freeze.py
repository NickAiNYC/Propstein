"""Focused safety checks for the 1 PM Eastern prospective board freeze."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import src.freeze_slate as freeze
from scripts.freeze_sunday_early import target
from src.prospective_board import capture_board, verify_journal


def write_slate_fixture(viewer: Path, game_ids: set[str]) -> None:
    """Keep the freeze tests independent of the daily, shrinking live slate."""
    rows = [
        {
            "game_id": game_id,
            "player_id": f"test-{index}",
            "player_display_name": f"Test Player {index}",
            "team": game_id.split("_")[2],
            "opponent_team": game_id.split("_")[3],
            "position": "WR",
            "mu_rec": 4.0,
            "mu_ypr": 12.0,
            "fair_line_yards": 40.5,
            "fair_line_rec": 3.5,
            "proj_yards": 48.0,
            "proj_rec": 4.0,
        }
        for index, game_id in enumerate(sorted(game_ids))
    ]
    (viewer / "slate_2026_w8.json").write_text(json.dumps(rows), encoding="utf-8")


class SundayFreezeTests(unittest.TestCase):
    def test_est_window_selects_all_eight_and_skips_early_and_late_runs(self) -> None:
        early = target(datetime(2026, 11, 1, 16, 30, tzinfo=timezone.utc))
        due = target(datetime(2026, 11, 1, 17, 30, tzinfo=timezone.utc))
        late = target(datetime(2026, 11, 1, 18, 5, tzinfo=timezone.utc))
        self.assertIsNone(early)
        self.assertIsNone(late)
        self.assertIsNotNone(due)
        self.assertEqual(len(due[2]), 8)

    def test_complete_cohort_freezes_and_captures_every_candidate(self) -> None:
        selected = target(datetime(2026, 11, 1, 17, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(selected)
        _, _, kickoffs = selected
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            viewer = root / "viewer"
            snapshots = root / "snapshots"
            viewer.mkdir()
            snapshots.mkdir()
            write_slate_fixture(viewer, set(kickoffs))
            with patch.object(freeze, "VIEWER_DIR", viewer), patch.object(freeze, "SNAPSHOTS_DIR", snapshots):
                frozen, source, bundle = freeze.freeze_slate(
                    2026, 8, game_ids=set(kickoffs),
                    created_at="2026-11-01T17:20:00+00:00",
                )
            kickoff_map = root / "kickoffs.json"
            kickoff_map.write_text(json.dumps(kickoffs), encoding="utf-8")
            journal = snapshots / "full_board.jsonl"
            report = capture_board(
                source, kickoff_map, journal,
                captured_at=datetime(2026, 11, 1, 17, 30, tzinfo=timezone.utc),
            )
            rows = verify_journal(journal)
            self.assertEqual(len(rows), len(frozen))
            self.assertEqual(len(json.loads(bundle.read_text())), len(frozen))
            self.assertEqual({row["game_id"] for row in rows}, set(kickoffs))
            self.assertEqual(report["pass_no_quote_count"], len(rows))

    def test_corrupt_existing_bundle_never_appends_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            viewer = root / "viewer"
            snapshots = root / "snapshots"
            viewer.mkdir()
            snapshots.mkdir()
            write_slate_fixture(viewer, {"2026_08_BAL_BUF"})
            (viewer / "snapshots_2026_w8.json").write_text("{bad json", encoding="utf-8")
            with patch.object(freeze, "VIEWER_DIR", viewer), patch.object(freeze, "SNAPSHOTS_DIR", snapshots):
                with self.assertRaises(json.JSONDecodeError):
                    freeze.freeze_slate(2026, 8, game_id="2026_08_BAL_BUF")
            self.assertFalse((snapshots / "snapshots_2026_w8.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
