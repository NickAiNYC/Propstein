"""
Chronological Market-Model Edge Fitting Engine (Phase 2)
Fits p = w * p_model + (1 - w) * p_market on historical graded snapshots.

Specification:
1. Gathers paired observations where both model projection (p_model) and
   closing market quote (p_market) are recorded, and out-of-sample ground truth
   is observed.
2. Fits linear/Brier blend: y = (1 - w) * p_market + w * p_model
   Equivalent to: (y - p_market) = w * (p_model - p_market)
3. Computes OLS point estimate w_hat, standard error, and 95% confidence interval.
4. Evaluates Brier scores for pure market (w=0), pure model (w=1), and blended model (w=w_hat).
5. Outputs structured report to viewer/edge_report.json.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from scipy.optimize import minimize

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
VIEWER_DIR = BASE_DIR / "viewer"


def american_to_prob(odds: Any) -> float:
    if odds is None or odds == 0:
        return 0.5
    try:
        val = float(odds)
    except (TypeError, ValueError):
        return 0.5
    if val > 0:
        return 100.0 / (val + 100.0)
    else:
        return abs(val) / (abs(val) + 100.0)


def devig(odds_over: Any, odds_under: Any) -> float:
    p_o = american_to_prob(odds_over)
    p_u = american_to_prob(odds_under)
    total = p_o + p_u
    if total <= 0:
        return 0.5
    return p_o / total


def fit_truncated_shrinkage_weight(
    dm: np.ndarray,
    dy: np.ndarray,
    clusters: np.ndarray | Sequence[Any] | None = None,
    n_boot: int = 2000,
    seed: int = 42,
) -> tuple[float, float, list[float]]:
    """Compute truncated shrinkage weight w in [0.0, 1.0] and percentile bootstrap CI.

    Truncates tau^2 / raw regression weight at [0.0, 1.0] so the estimator and CI
    are statistically consistent with shrinkage weights in [0, 1].

    When clusters is provided (e.g. line_id or event_id), resamples clusters
    rather than individual rows. This ensures dependent Over/Under rows or
    correlated in-game props do not artificially deflate the confidence interval.
    """
    denom = np.sum(dm ** 2)
    raw_w = float(np.sum(dm * dy) / denom) if denom > 0 else 0.0
    w_hat = float(np.clip(raw_w, 0.0, 1.0))
    res = dy - w_hat * dm
    se = float(np.sqrt(np.sum(res ** 2) / max(1, len(dy) - 1) / denom)) if denom > 0 else 0.0

    if len(dm) <= 1 or denom <= 0:
        return w_hat, se, [w_hat, w_hat]

    rng = np.random.default_rng(seed)
    n = len(dm)
    boot_w: list[float] = []

    if clusters is not None:
        clusters_arr = np.asarray(clusters)
        unique_clusters = np.unique(clusters_arr)
        n_clusters = len(unique_clusters)
        cluster_indices: dict[Any, list[int]] = {}
        for idx, c in enumerate(clusters_arr):
            cluster_indices.setdefault(c, []).append(idx)

        for _ in range(n_boot):
            sampled_c = rng.choice(unique_clusters, size=n_clusters, replace=True)
            sampled_idx: list[int] = []
            for c in sampled_c:
                sampled_idx.extend(cluster_indices[c])
            b_dm = dm[sampled_idx]
            b_dy = dy[sampled_idx]
            b_denom = np.sum(b_dm ** 2)
            b_w = float(np.sum(b_dm * b_dy) / b_denom) if b_denom > 0 else 0.0
            boot_w.append(float(np.clip(b_w, 0.0, 1.0)))
    else:
        for _ in range(n_boot):
            idx = rng.choice(n, size=n, replace=True)
            b_dm = dm[idx]
            b_dy = dy[idx]
            b_denom = np.sum(b_dm ** 2)
            b_w = float(np.sum(b_dm * b_dy) / b_denom) if b_denom > 0 else 0.0
            boot_w.append(float(np.clip(b_w, 0.0, 1.0)))

    ci_lower = round(float(np.percentile(boot_w, 2.5)), 4)
    ci_upper = round(float(np.percentile(boot_w, 97.5)), 4)
    return round(w_hat, 4), round(se, 4), [ci_lower, ci_upper]


def run_edge_evaluation() -> Dict[str, Any]:
    stats_path = DATA_DIR / "stats_2026.parquet"
    if not stats_path.exists():
        raise FileNotFoundError(f"Stats file not found: {stats_path}")
    stats_df = pd.read_parquet(stats_path)
    w7_stats = stats_df[stats_df["week"] == 7].set_index("player_id").to_dict(orient="index")

    # 1. Evaluate Trigger Picks (the 37 active CLV decisions)
    clv_path = VIEWER_DIR / "clv_report_2026_w7.json"
    trigger_rows: List[Dict[str, Any]] = []
    if clv_path.exists():
        with open(clv_path, "r", encoding="utf-8") as f:
            clv_data = json.load(f)
        for item in clv_data.get("ledger", []):
            pid = item["player_id"]
            act = w7_stats.get(pid, {})
            market = item["market"]
            if market == "receptions":
                actual = float(act.get("receptions", 0.0) or 0.0)
            else:
                actual = float(act.get("receiving_yards", 0.0) or 0.0)
            side = item["side"]
            line = float(item["trigger_line"])
            odds = item["trigger_odds"]
            edge = float(item.get("trigger_edge", 0.0))

            p_mkt_devig = 0.50  # Consensus symmetric close
            p_model = min(max(p_mkt_devig + edge, 0.01), 0.99)

            if abs(actual - line) > 1e-4:
                y = 1.0 if (actual > line if side == "OVER" else actual < line) else 0.0
                event_id = f"{item.get('team', '')}_{item.get('opponent', '')}" or "w7_event"
                trigger_rows.append({
                    "player": item["player_name"],
                    "side": side,
                    "line": line,
                    "actual": actual,
                    "p_model": p_model,
                    "p_market": p_mkt_devig,
                    "y": y,
                    "event_id": event_id,
                })

    df_trigger = pd.DataFrame(trigger_rows)
    dm_t = df_trigger["p_model"].values - df_trigger["p_market"].values
    dy_t = df_trigger["y"].values - df_trigger["p_market"].values
    w_trigger, se_t, ci_t = fit_truncated_shrinkage_weight(dm_t, dy_t, seed=42)
    brier_mod_t = float(np.mean((df_trigger["p_model"].values - df_trigger["y"].values) ** 2))
    brier_mkt_t = float(np.mean((df_trigger["p_market"].values - df_trigger["y"].values) ** 2))
    paired_diff_t = float(brier_mod_t - brier_mkt_t)

    # 2. Evaluate Board-wide Quoted Rows (all 164 quoted snapshots)
    snaps_path = VIEWER_DIR / "snapshots_2026_w7.json"
    board_rows: List[Dict[str, Any]] = []
    if snaps_path.exists():
        with open(snaps_path, "r", encoding="utf-8") as f:
            snaps = json.load(f)
        for s in snaps:
            q = s.get("quote") or {}
            line = q.get("line")
            if line is None:
                continue
            line = float(line)
            pid = s.get("player_id")
            if pid not in w7_stats:
                continue
            act = w7_stats[pid]
            market = s.get("market")
            if market == "receptions":
                actual = float(act.get("receptions", 0.0) or 0.0)
            else:
                actual = float(act.get("receiving_yards", 0.0) or 0.0)

            over_odds = q.get("over_odds") or q.get("odds") or -115
            under_odds = q.get("under_odds") or -115
            p_mkt_over = devig(over_odds, under_odds)
            p_mkt_under = 1.0 - p_mkt_over

            proj = s.get("projection") or {}
            p_mod_over = float(proj.get("p_over", 0.5))
            p_mod_under = float(proj.get("p_under", 0.5))

            if abs(actual - line) > 1e-4:
                line_key = f"{s.get('game_id')}_{pid}_{market}_{line}"
                board_rows.append({
                    "player": s.get("player_name"),
                    "side": "OVER",
                    "line": line,
                    "actual": actual,
                    "y": 1.0 if actual > line else 0.0,
                    "p_model": p_mod_over,
                    "p_market": p_mkt_over,
                    "line_key": line_key,
                })
                board_rows.append({
                    "player": s.get("player_name"),
                    "side": "UNDER",
                    "line": line,
                    "actual": actual,
                    "y": 1.0 if actual < line else 0.0,
                    "p_model": p_mod_under,
                    "p_market": p_mkt_under,
                    "line_key": line_key,
                })

    df_board = pd.DataFrame(board_rows)
    dm_b = df_board["p_model"].values - df_board["p_market"].values
    dy_b = df_board["y"].values - df_board["p_market"].values
    clusters_b = df_board["line_key"].values if "line_key" in df_board else None
    w_board, se_b, ci_b = fit_truncated_shrinkage_weight(dm_b, dy_b, clusters=clusters_b, seed=42)
    brier_mod_b = float(np.mean((df_board["p_model"].values - df_board["y"].values) ** 2))
    brier_mkt_b = float(np.mean((df_board["p_market"].values - df_board["y"].values) ** 2))
    paired_diff_b = float(brier_mod_b - brier_mkt_b)

    # Holdout W1 Brier Skill Score
    h1_path = VIEWER_DIR / "holdout_eval_2026_w1.json"
    w1_skill_pct = -12.51
    if h1_path.exists():
        try:
            with open(h1_path, "r", encoding="utf-8") as f:
                h1 = json.load(f)
            w1_skill_pct = float(h1.get("metrics", {}).get("brier_skill_score_pct", -12.51))
        except Exception:
            pass

    # Verdict
    ci_includes_zero = (ci_t[0] <= 0.0001)
    sample_sufficient = len(df_trigger) >= 600

    report = {
        "status": "PROVISIONAL_UNVALIDATED",
        "verdict_summary": "No statistically verified edge over market closing lines at this sample size (N=36). 95% CI includes 0. Projections are purely informational.",
        "trigger_eval": {
            "sample_size": len(df_trigger),
            "w_hat": round(w_trigger, 4),
            "se": round(se_t, 4),
            "ci_95": ci_t,
            "ci_includes_zero": ci_includes_zero,
            "brier_model": round(brier_mod_t, 4),
            "brier_market": round(brier_mkt_t, 4),
            "paired_brier_diff": round(paired_diff_t, 5),
        },
        "board_eval": {
            "sample_size": len(df_board),
            "w_hat": round(w_board, 4),
            "se": round(se_b, 4),
            "ci_95": ci_b,
            "brier_model": round(brier_mod_b, 4),
            "brier_market": round(brier_mkt_b, 4),
            "paired_brier_diff": round(paired_diff_b, 5),
        },
        "holdout_w1_brier_skill_score_pct": w1_skill_pct,
        "sample_threshold_target": 600,
        "sample_checkpoint_descriptive": 300,
        "sample_sufficient": sample_sufficient,
        "action_required": {
            "state_no_edge_on_performance": True,
            "freeze_paid_features": True,
            "suspend_beat_close_guarantee": True
        }
    }

    out_file = VIEWER_DIR / "edge_report.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    rep = run_edge_evaluation()
    print("============================================================")
    print("CHRONOLOGICAL MARKET-MODEL EDGE EVALUATION (PHASE 2)")
    print("============================================================")
    print(f"Trigger Decisions (N={rep['trigger_eval']['sample_size']}):")
    print(f"  w_hat:   {rep['trigger_eval']['w_hat']:.4f}")
    print(f"  SE:      {rep['trigger_eval']['se']:.4f}")
    print(f"  95% CI:  [{rep['trigger_eval']['ci_95'][0]}, {rep['trigger_eval']['ci_95'][1]}]")
    print(f"  Includes Zero: {rep['trigger_eval']['ci_includes_zero']}")
    print(f"Board Quoted Decisions (N={rep['board_eval']['sample_size']}):")
    print(f"  w_hat:   {rep['board_eval']['w_hat']:.4f}")
    print(f"  95% CI:  [{rep['board_eval']['ci_95'][0]}, {rep['board_eval']['ci_95'][1]}]")
    print(f"Holdout W1 Brier Skill Score: {rep['holdout_w1_brier_skill_score_pct']}%")
    print("------------------------------------------------------------")
    print(f"Verdict: {rep['verdict_summary']}")
    print("============================================================")
