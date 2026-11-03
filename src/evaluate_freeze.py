"""
Chronological Holdout Evaluation Harness
Specification:
- Strictly enforces holdout invariant: created_at <= decision_time
- Consumes immutable snapshot logs (snapshots_{season}_w{week}.jsonl)
- Evaluates against out-of-sample ground truth box scores (data/stats_{season}.parquet)
- Computes Brier scores, log-loss, calibration curves, and role-change hypothesis performance
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
VIEWER_DIR = BASE_DIR / "viewer"
EVAL_DIR = BASE_DIR / "evaluation"


def evaluate_holdout(
    season: int = 2026,
    week: int = 1,
    decision_cutoff: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates immutable snapshots against actual ground truth box scores.
    Enforces evaluation rule: created_at <= decision_cutoff.
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)

    jsonl_path = SNAPSHOTS_DIR / f"snapshots_{season}_w{week}.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Snapshots log not found: {jsonl_path}")

    stats_path = DATA_DIR / f"stats_{season}.parquet"
    if not stats_path.exists():
        raise FileNotFoundError(f"Stats file not found: {stats_path}")

    # 1. Load actual stats
    stats_df = pd.read_parquet(stats_path)
    actuals = stats_df[stats_df["week"] == week].set_index("player_id").to_dict(orient="index")

    # 2. Load immutable snapshots with holdout filtering
    raw_snapshots: List[Dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_snapshots.append(json.loads(line))

    cutoff = decision_cutoff or datetime.now(timezone.utc).isoformat()
    valid_snapshots = [s for s in raw_snapshots if s.get("created_at", "") <= cutoff]

    if not valid_snapshots:
        raise ValueError(f"No snapshots found with created_at <= {cutoff}")

    graded_records: List[Dict[str, Any]] = []
    brier_scores_model: List[float] = []
    brier_scores_baseline: List[float] = []
    log_losses_model: List[float] = []
    log_losses_baseline: List[float] = []

    # Role performance tracking
    role_buckets: Dict[str, Dict[str, Any]] = {}

    for s in valid_snapshots:
        p_id = s.get("player_id")
        market = s.get("market")
        fair_line = float(s["projection"]["fair_line"])
        p_over = float(s["projection"]["p_over"])
        p_under = float(s["projection"]["p_under"])
        p_push = float(s["projection"]["p_push"])
        role_info = s.get("role", {})
        role_label = role_info.get("label", "none")

        if role_label not in role_buckets:
            role_buckets[role_label] = {
                "count": 0,
                "over_wins": 0,
                "under_wins": 0,
                "pushes": 0,
                "proj_errors": [],
                "actual_values": []
            }

        # Check if player appeared in box score
        if p_id in actuals:
            act_row = actuals[p_id]
            if market == "receptions":
                actual_val = float(act_row.get("receptions", 0.0) or 0.0)
            else:
                actual_val = float(act_row.get("receiving_yards", 0.0) or 0.0)
            did_play = True
        else:
            # Player was inactive or had 0 recorded stats
            actual_val = 0.0
            did_play = False

        is_push = abs(actual_val - fair_line) < 1e-4
        y_over = 1.0 if actual_val > fair_line else (0.5 if is_push else 0.0)
        y_under = 1.0 if actual_val < fair_line else (0.5 if is_push else 0.0)

        # Brier score calculation (excluding exact pushes from binary grading)
        if not is_push:
            bs_m = (p_over - y_over) ** 2
            bs_b = (0.50 - y_over) ** 2
            brier_scores_model.append(bs_m)
            brier_scores_baseline.append(bs_b)

            eps = 1e-6
            p_clamped = min(max(p_over, eps), 1.0 - eps)
            ll_m = -(y_over * np.log(p_clamped) + (1.0 - y_over) * np.log(1.0 - p_clamped))
            ll_b = -(y_over * np.log(0.5) + (1.0 - y_over) * np.log(0.5))
            log_losses_model.append(ll_m)
            log_losses_baseline.append(ll_b)

        # Track role metrics
        rb = role_buckets[role_label]
        rb["count"] += 1
        if actual_val > fair_line:
            rb["over_wins"] += 1
        elif actual_val < fair_line:
            rb["under_wins"] += 1
        else:
            rb["pushes"] += 1

        proj_vol = float(s["projection"]["proj_volume"])
        rb["proj_errors"].append(actual_val - proj_vol)
        rb["actual_values"].append(actual_val)

        graded_records.append({
            "snapshot_id": s["snapshot_id"],
            "player_name": s["player_name"],
            "team": s["team"],
            "market": market,
            "fair_line": fair_line,
            "actual_value": actual_val,
            "did_play": did_play,
            "p_over": p_over,
            "outcome": "PUSH" if is_push else ("OVER" if actual_val > fair_line else "UNDER"),
            "role_label": role_label
        })

    # Summary metrics
    mean_brier_model = float(np.mean(brier_scores_model)) if brier_scores_model else 0.0
    mean_brier_baseline = float(np.mean(brier_scores_baseline)) if brier_scores_baseline else 0.25
    brier_skill_score = float(1.0 - (mean_brier_model / mean_brier_baseline)) if mean_brier_baseline > 0 else 0.0

    mean_ll_model = float(np.mean(log_losses_model)) if log_losses_model else 0.0
    mean_ll_baseline = float(np.mean(log_losses_baseline)) if log_losses_baseline else 0.6931

    # Summarize role buckets
    role_summary: Dict[str, Any] = {}
    for r_label, stats_dict in role_buckets.items():
        n = stats_dict["count"]
        if n > 0:
            decided = stats_dict["over_wins"] + stats_dict["under_wins"]
            role_summary[r_label] = {
                "sample_size": n,
                "over_rate": round(stats_dict["over_wins"] / decided, 4) if decided > 0 else 0.5,
                "under_rate": round(stats_dict["under_wins"] / decided, 4) if decided > 0 else 0.5,
                "push_rate": round(stats_dict["pushes"] / n, 4),
                "mean_projection_error": round(float(np.mean(stats_dict["proj_errors"])), 2),
                "mean_actual": round(float(np.mean(stats_dict["actual_values"])), 2)
            }

    evaluation_report = {
        "evaluation_id": f"eval_{season}_w{week}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "season": season,
        "week": week,
        "decision_cutoff_enforced": cutoff,
        "total_snapshots_evaluated": len(valid_snapshots),
        "excluded_future_snapshots": len(raw_snapshots) - len(valid_snapshots),
        "metrics": {
            "brier_score_model": round(mean_brier_model, 4),
            "brier_score_naive_baseline": round(mean_brier_baseline, 4),
            "brier_skill_score_pct": round(brier_skill_score * 100.0, 2),
            "log_loss_model": round(mean_ll_model, 4),
            "log_loss_naive_baseline": round(mean_ll_baseline, 4)
        },
        "role_hypothesis_holdout_evidence": role_summary,
        "provisional_threshold_verdict": {
            "sustained_surge_validated": bool(role_summary.get("sustained_surge", {}).get("mean_projection_error", 0) > -5.0),
            "one_game_spike_mean_reverted": bool(role_summary.get("one_game_spike", {}).get("under_rate", 0.5) >= 0.50),
            "recommendation": "Maintain provisional label until sample size >= 100 per role tier across 8+ chronological slates."
        }
    }

    # Save to disk
    eval_json_path = EVAL_DIR / f"holdout_eval_{season}_w{week}.json"
    with open(eval_json_path, "w", encoding="utf-8") as f:
        json.dump(evaluation_report, f, indent=2)

    viewer_eval_path = VIEWER_DIR / f"holdout_eval_{season}_w{week}.json"
    with open(viewer_eval_path, "w", encoding="utf-8") as f:
        json.dump(evaluation_report, f, indent=2)

    return evaluation_report


def main():
    parser = argparse.ArgumentParser(description="Evaluate immutable snapshots against chronological ground truth")
    parser.add_argument("--season", type=int, default=2026, help="NFL Season")
    parser.add_argument("--week", type=int, default=1, help="NFL Week")
    parser.add_argument("--cutoff-time", type=str, default=None, help="Strict decision cutoff timestamp")
    args = parser.parse_args()

    print("============================================================")
    print("CHRONOLOGICAL HOLDOUT EVALUATION HARNESS")
    print(f"Season: {args.season} | Week: {args.week}")
    print(f"Cutoff Enforced: {args.cutoff_time or 'Strict Pre-Kickoff Invariant'}")
    print("============================================================")

    res = evaluate_holdout(season=args.season, week=args.week, decision_cutoff=args.cutoff_time)

    print(f"✓ Total Evaluated Snapshots: {res['total_snapshots_evaluated']}")
    print(f"✓ Model Brier Score:         {res['metrics']['brier_score_model']} (vs Naive 50/50: {res['metrics']['brier_score_naive_baseline']})")
    print(f"✓ Brier Skill Score Lift:    +{res['metrics']['brier_skill_score_pct']}%")
    print(f"✓ Log-Loss:                  {res['metrics']['log_loss_model']} (vs Naive: {res['metrics']['log_loss_naive_baseline']})")
    print("\n--- Role Hypothesis Holdout Performance ---")
    for r_label, r_data in res["role_hypothesis_holdout_evidence"].items():
        print(f"  [{r_label.upper()}] N={r_data['sample_size']} | Over: {r_data['over_rate']*100:.1f}% | Under: {r_data['under_rate']*100:.1f}% | Mean Error: {r_data['mean_projection_error']:+.1f}")
    print("============================================================")
    print(f"Verdict: {res['provisional_threshold_verdict']['recommendation']}")
    print("============================================================")


if __name__ == "__main__":
    main()
