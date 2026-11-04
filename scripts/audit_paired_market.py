#!/usr/bin/env python3
"""audit_paired_market.py — paired market-relative Brier comparison & copycat diagnostic.

Evaluates predictions against the de-vigged closing market on the exact same outcomes.
Generates viewer/paired_market_eval.json and reports paired Brier difference + 95% CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ledger.paired_scoring import compute_paired_market_comparison


def main() -> int:
    holdout_path = ROOT / "viewer" / "holdout_eval_2026_w1.json"
    clv_path = ROOT / "viewer" / "clv_report_2026_w7.json"

    observations: list[dict] = []

    # If holdout evaluation has pairs
    if holdout_path.is_file():
        try:
            holdout_data = json.loads(holdout_path.read_text(encoding="utf-8"))
            raw_pairs = holdout_data.get("paired_observations") or []
            observations.extend(raw_pairs)
        except Exception:
            pass

    # If CLV report exists, construct paired cohort with actual on-field outcomes
    if clv_path.is_file() and not observations:
        try:
            stats_path = ROOT / "data" / "stats_2026.parquet"
            w7_stats = {}
            if stats_path.is_file():
                import pandas as pd
                stats_df = pd.read_parquet(stats_path)
                w7_stats = stats_df[stats_df["week"] == 7].set_index("player_id").to_dict(orient="index")

            clv_data = json.loads(clv_path.read_text(encoding="utf-8"))
            ledger_rows = clv_data.get("ledger") or []
            from scripts.fit_edge import devig
            import numpy as np

            for row in ledger_rows:
                pid = row.get("player_id")
                line = float(row.get("trigger_line", 0.0))
                market = row.get("market")
                side = row.get("side", "OVER")

                if pid in w7_stats:
                    act = w7_stats[pid]
                    actual = float(act.get("receptions" if market == "receptions" else "receiving_yards", 0.0) or 0.0)
                    if abs(actual - line) < 1e-4:
                        continue  # Exclude exact pushes from evaluable sample
                    y = 1.0 if (actual > line if side == "OVER" else actual < line) else 0.0
                else:
                    st = row.get("status")
                    if st in ("PUSH", "VOID", "DNP", "CANCELLED"):
                        continue
                    y = 1.0 if st == "BEAT_CLOSE" else 0.0

                c_odds = row.get("closing_odds") or row.get("trigger_odds") or -115
                p_mkt = devig(c_odds, -115)
                edge = float(row.get("trigger_edge") or 0.0)
                p_mod = float(np.clip(p_mkt + edge, 0.01, 0.99))
                event_id = f"{row.get('team', '')}_{row.get('opponent', '')}" or "w7_event"
                observations.append({
                    "p_model": p_mod,
                    "p_market": p_mkt,
                    "outcome": y,
                    "event_id": event_id,
                })
        except Exception:
            pass

    comparison = compute_paired_market_comparison(observations)
    payload = comparison.as_dict()

    out_path = ROOT / "viewer" / "paired_market_eval.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 65)
    print("  PROPSTEIN PAIRED MARKET-RELATIVE BENCHMARK & DIAGNOSTIC")
    print("=" * 65)
    print(f"Sample Pairs:            N = {comparison.n_pairs} across {comparison.n_events} game clusters")
    print(f"Model Brier:             {comparison.brier_model:.4f}")
    print(f"Market Brier:            {comparison.brier_market:.4f}")
    print(f"Paired Brier Difference: {comparison.paired_diff:+.5f} (negative = model better)")
    print(f"Cluster 95% CI:          [{comparison.paired_diff_ci95[0]:+.5f}, {comparison.paired_diff_ci95[1]:+.5f}]")
    print(f"Median Absolute Gap:     {comparison.median_abs_gap_pts:.2f} percentage points")
    print(f"Model-Market Corr:       {comparison.corr_model_market:.4f} {'[COPYCAT ALERT]' if comparison.is_copycat else '[INDEPENDENT]'}")
    print(f"Paired Win Rate:         {comparison.paired_win_rate * 100:.1f}%")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())

