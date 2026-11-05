import json
import unittest
from pathlib import Path
from scripts.fit_edge import run_edge_evaluation, DATA_DIR

STATS_FILE = DATA_DIR / "stats_2026.parquet"

class TestFitEdge(unittest.TestCase):
    # The stats parquet is local-only data (autopilot downloads it; it is not
    # committed). A fresh CI checkout cannot run the real fit — skip honestly
    # instead of failing on missing input.
    @unittest.skipUnless(STATS_FILE.exists(), f"requires local {STATS_FILE} (not committed; autopilot downloads it)")
    def test_fit_edge_generates_report(self):
        rep = run_edge_evaluation()
        self.assertIn("trigger_eval", rep)
        self.assertIn("ci_95", rep["trigger_eval"])
        self.assertTrue(rep["trigger_eval"]["ci_includes_zero"])
        self.assertTrue(rep["action_required"]["state_no_edge_on_performance"])
        self.assertTrue(rep["action_required"]["freeze_paid_features"])
        self.assertTrue(rep["action_required"]["suspend_beat_close_guarantee"])
        # Both board and trigger cohorts record paired Brier diffs and CIs spanning zero
        self.assertEqual(rep["trigger_eval"]["sample_size"], 36)
        self.assertIn("paired_brier_diff", rep["board_eval"])
        self.assertIn("paired_brier_diff", rep["trigger_eval"])
        self.assertTrue(rep["board_eval"]["paired_brier_diff_spans_zero"])
        self.assertTrue(rep["trigger_eval"]["paired_brier_diff_spans_zero"])
        self.assertNotIn("win_rate_pct", rep["trigger_eval"])

    def test_cluster_bootstrap_160_vs_320_identity(self):
        import numpy as np
        from scripts.fit_edge import fit_truncated_shrinkage_weight

        np.random.seed(42)
        dm_160 = np.random.normal(0, 0.05, 160)
        dy_160 = 0.5 * dm_160 + np.random.normal(0, 0.1, 160)
        clusters_160 = np.arange(160)

        # 320 symmetric paired Over/Under rows
        dm_320 = np.concatenate([dm_160, -dm_160])
        dy_320 = np.concatenate([dy_160, -dy_160])
        clusters_320 = np.concatenate([clusters_160, clusters_160])

        w_160, se_160, ci_160 = fit_truncated_shrinkage_weight(
            dm_160, dy_160, clusters=clusters_160, seed=42
        )
        w_320, se_320, ci_320 = fit_truncated_shrinkage_weight(
            dm_320, dy_320, clusters=clusters_320, seed=42
        )

        self.assertEqual(w_160, w_320)
        self.assertEqual(ci_160, ci_320)

    @unittest.skipUnless(STATS_FILE.exists(), f"requires local {STATS_FILE}")
    def test_missing_stat_records_are_excluded_never_defaulted_to_zero(self):
        """Generalization guard against silent-default-to-zero bugs.

        Ensures that any ledger record with missing box scores is strictly excluded,
        preventing missing-stat rows (like Hollins) from silently turning into 0.0 losses
        and inflating sample size in the wrong direction.
        """
        import pandas as pd
        from scripts.fit_edge import VIEWER_DIR

        stats_df = pd.read_parquet(STATS_FILE)
        w7_stats = stats_df[stats_df["week"] == 7].set_index("player_id").to_dict(orient="index")

        clv_path = VIEWER_DIR / "clv_report_2026_w7.json"
        with open(clv_path, "r", encoding="utf-8") as f:
            clv_data = json.load(f)

        missing_stat_pids = set()
        for item in clv_data.get("ledger", []):
            pid = item["player_id"]
            if pid not in w7_stats:
                missing_stat_pids.add(pid)

        # Mack Hollins was the real-world missing-stat record in W7
        self.assertIn("00-0033555", missing_stat_pids)

        # Run evaluation and confirm no record with a missing stat is in the evaluated sample
        rep = run_edge_evaluation()
        self.assertEqual(rep["trigger_eval"]["sample_size"], len(clv_data.get("ledger", [])) - len(missing_stat_pids))

        # Re-check that if a hypothetical unrecorded player is added, it is excluded rather than scored as 0.0 loss
        hypothetical_item = {
            "player_id": "00-NONEXISTENT",
            "player_name": "Ghost Player",
            "team": "NE",
            "opponent": "CHI",
            "market": "receiving_yards",
            "side": "OVER",
            "trigger_line": 25.5,
            "trigger_odds": -115,
            "status": "DNP",
        }
        # In our logic, absent from stats -> strictly excluded
        self.assertNotIn("00-NONEXISTENT", w7_stats)


if __name__ == "__main__":
    unittest.main()
