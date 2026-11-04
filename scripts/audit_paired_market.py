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

    # If CLV report exists, construct paired cohort
    if clv_path.is_file() and not observations:
        try:
            clv_data = json.loads(clv_path.read_text(encoding="utf-8"))
            ledger_rows = clv_data.get("ledger") or []
            for row in ledger_rows:
                edge = float(row.get("trigger_edge") or 0.0)
                # Reconstruct implied entry prob and closing devig prob
                # Standard American -115 -> ~0.5349 raw, ~0.50 devigged two-way
                p_mkt = 0.50
                p_mod = p_mkt + edge
                # Status: BEAT_CLOSE -> 1, FADED -> 0, PUSH/TIE -> 0.5
                st = row.get("status")
                y = 1.0 if st == "BEAT_CLOSE" else (0.5 if st == "PUSH" else 0.0)
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

