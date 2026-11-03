"""Date-based walk-forward harness — the repo's core honesty mechanism.

For each evaluation date d:
  1. train = strictly ALL games with game_date < d   (expanding window)
  2. fit projector on train ONLY
  3. predict every played player-game on d
  4. score predictions against realized points (z-scores) and, when an
     odds feed is supplied, against de-vigged market probabilities at the
     quoted lines (Brier / reliability / slope)

Leakage protection is two-layered:
  - the date split above (nothing from d or later enters the fit), and
  - the shift(1) guard inside features/form.py (history columns see only
    strictly-earlier games).
tests/test_walkforward.py asserts BOTH layers explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..features.form import add_rolling_form
from ..features.injuries import add_availability_adjustments
from ..model.projector import NBAPointsProjector
from ..model.distribution import PointsDistribution
from . import calibration
from .devig import group_quotes, market_consensus


@dataclass
class WalkForwardResult:
    records: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict = field(default_factory=dict)
    distributional: dict = field(default_factory=dict)

    @property
    def uncalibrated(self) -> bool:
        return bool(self.summary.get("uncalibrated", True))


def _injuries_for_date(injuries: list[dict] | None, date: str) -> list[dict]:
    if not injuries:
        return None
    rows = [i for i in injuries if i.get("game_id", "").find(date.replace("-", "")) >= 0
            or str(i.get("as_of", "")).startswith(date)]
    return rows or None


def run_walk_forward(
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    odds: list[dict] | None = None,
    injuries: list[dict] | None = None,
) -> WalkForwardResult:
    """df must be the built dataset (data/dataset.py) with ppm/margin/poss."""
    df = add_rolling_form(df)

    all_dates = sorted(d for d in df["game_date"].dropna().unique())
    eval_dates = [d for d in all_dates if start_date <= d <= end_date]
    if not eval_dates:
        raise ValueError(f"no evaluation dates in [{start_date}, {end_date}]")

    odds_by_date: dict[str, list[dict]] = {}
    for q in odds or []:
        obs = str(q.get("observed_at", ""))[:10]
        odds_by_date.setdefault(obs, []).append(q)

    records: list[dict] = []
    z_scores: list[float] = []

    for d in eval_dates:
        train = df[df["game_date"] < d]
        test = df[(df["game_date"] == d) & (~df["dnp"])].copy()
        if train.empty or test.empty:
            continue

        projector = NBAPointsProjector().fit(train)
        test_adj = add_availability_adjustments(test, _injuries_for_date(injuries, d))
        preds = projector.predict(test_adj, history=train)
        baseline = projector.naive_baseline(test)
        preds = preds.merge(baseline, on=["player_id", "game_id"], how="left")

        actual = test[["player_id", "game_id", "pts"]].rename(columns={"pts": "actual_pts"})
        preds = preds.merge(actual, on=["player_id", "game_id"], how="left")

        # ── distributional z-scores (no lines needed) ───────────────────────
        for _, p in preds.iterrows():
            if pd.notna(p["actual_pts"]):
                z_scores.append((float(p["actual_pts"]) - float(p["mean_pts"])) / float(p["sd_pts"]))

        # ── line-based records vs de-vigged market ─────────────────────────
        day_odds = odds_by_date.get(d, [])
        if day_odds:
            grouped = group_quotes(day_odds, market="points")
            # join on player only; each quoted line becomes one record
            preds_by_player = {p: (row) for p, row in preds.set_index("player_id").iterrows()}
            for (player_id, line), quotes in grouped.items():
                p_row = preds_by_player.get(player_id)
                if p_row is None:
                    continue
                consensus = market_consensus(quotes)
                if consensus is None or consensus["n_books"] < 1:
                    continue
                dist = PointsDistribution(mean=float(p_row["mean_pts"]), sd=float(p_row["sd_pts"]))
                naive_dist = PointsDistribution(
                    mean=float(p_row["naive_mean"]), sd=float(p_row["naive_sd"])
                )
                outcome_pts = float(p_row["actual_pts"])
                push = dist.p_push(line)
                # exclude near-push lines from scoring (record keeps the info)
                if abs(line - round(line)) < 1e-9 and push > 0.20:
                    continue
                outcome = int(outcome_pts > line)
                records.append({
                    "date": d,
                    "player_id": player_id,
                    "line": float(line),
                    "model_p": dist.p_over(line),
                    "market_p": consensus["p_over"],
                    "naive_p": naive_dist.p_over(line),
                    "outcome": outcome,
                    "n_books": consensus["n_books"],
                })

    records_df = pd.DataFrame(records)
    result = WalkForwardResult(records=records_df)
    result.summary = calibration.summarize(records_df)

    z = np.asarray(z_scores, float)
    if len(z):
        result.distributional = {
            "n_player_games": int(len(z)),
            "z_mean": round(float(z.mean()), 4),
            "z_sd": round(float(z.std(ddof=1)), 4),
            "interpretation": (
                "z_sd ≈ 1.0 means the predicted variance matches realized spread"
            ),
        }
    return result
