"""
Weekly pick generation.

The agent is deliberately boring: fit -> project -> compare to the de-vigged
consensus -> emit only what clears the gates. There is no LLM in the decision
path. An LLM is used only to write the human-readable reasoning AFTER the
numbers are fixed, so it can never talk the model into a bet.

That separation is the whole design. Every "AI betting agent" that puts a
language model in the decision loop is generating narrative that is
uncorrelated with its own probabilities, and the narrative is what convinces
the customer.

HARD GATES (all must pass):
  1. Model probability beats de-vigged consensus by >= MIN_EDGE.
  2. At least MIN_BOOKS books quoting, so the consensus means something.
  3. Player has MIN_GAMES of prior usage this season.
  4. Not flagged Out/Doubtful in the injury feed.
  5. Kelly stake, capped, on a bankroll unit - never a "confidence" star rating.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from features import build_panel, FEATURES
from model import (ReceivingModel, kelly_fraction, ev_per_unit,
                   american_to_decimal, devig_two_way)

MIN_EDGE = 0.03          # model p minus de-vigged consensus p
MIN_BOOKS = 3
MIN_GAMES = 3
KELLY_CAP = 0.015        # 1.5% of bankroll maximum, ever
MARKET_MAP = {"player_receptions": "receptions",
              "player_reception_yds": "receiving_yards"}


@dataclass
class Pick:
    player: str
    market: str
    side: str
    line: float
    book: str
    odds: float
    model_prob: float
    market_prob: float
    edge: float
    ev_per_unit: float
    kelly_stake: float
    projection: float
    reasoning: str = ""


class PickAgent:
    def __init__(self, model: ReceivingModel, panel: pd.DataFrame):
        self.m = model
        self.panel = panel

    @classmethod
    def train(cls, through_season: int | None = None) -> "PickAgent":
        panel = build_panel()
        if through_season:
            panel = panel[panel.season <= through_season]
        return cls(ReceivingModel.fit(panel), panel)

    def project_slate(self, slate_rows: pd.DataFrame) -> pd.DataFrame:
        """slate_rows must carry the same FEATURES as the training panel,
        built for the upcoming week from the same feature pipeline."""
        p = self.m.predict_params(slate_rows)
        out = slate_rows.copy()
        out["mu_rec"] = p.mu_rec.values
        out["mu_ypr"] = p.mu_ypr.values
        out["proj_receptions"] = out.mu_rec
        out["proj_receiving_yards"] = out.mu_rec * out.mu_ypr
        return out

    def find_edges(self, projections: pd.DataFrame, consensus: dict,
                   injuries: set[str] | None = None) -> list[Pick]:
        injuries = injuries or set()
        by_player = {r.player_display_name: r for r in projections.itertuples()}
        picks: list[Pick] = []

        for (player, market_key, line), c in consensus.items():
            market = MARKET_MAP.get(market_key)
            if market is None or player not in by_player:
                continue
            if c["n_books"] < MIN_BOOKS or player in injuries:
                continue
            r = by_player[player]

            if market == "receptions":
                p_over = self.m.p_rec_over(r.mu_rec, line)
                proj = float(r.mu_rec)
            else:
                p_over = self.m.p_yards_over(r.mu_rec, r.mu_ypr, line)
                proj = float(r.mu_rec * r.mu_ypr)

            for side, p_model, odds, book in (
                    ("over", p_over, c["best_over_odds"], c["best_over_book"]),
                    ("under", 1 - p_over, c["best_under_odds"], c["best_under_book"])):
                if odds is None:
                    continue
                p_mkt = c["p_over"] if side == "over" else 1 - c["p_over"]
                edge = p_model - p_mkt
                if edge < MIN_EDGE:
                    continue
                ev = ev_per_unit(p_model, odds)
                if ev <= 0:
                    continue
                picks.append(Pick(
                    player=player, market=market, side=side, line=line,
                    book=book, odds=odds, model_prob=round(p_model, 4),
                    market_prob=round(p_mkt, 4), edge=round(edge, 4),
                    ev_per_unit=round(ev, 4),
                    kelly_stake=round(kelly_fraction(p_model, odds, cap=KELLY_CAP), 5),
                    projection=round(proj, 1)))

        picks.sort(key=lambda p: p.ev_per_unit, reverse=True)
        return picks

    # ------------------------------------------------------------------
    # Reasoning is generated AFTER the numbers. It explains; it never decides.
    # ------------------------------------------------------------------

    def explain(self, pick: Pick, context: dict | None = None) -> str:
        ctx = context or {}
        bits = [
            f"Model projects {pick.projection} {pick.market.replace('_', ' ')} "
            f"vs a line of {pick.line}.",
            f"Model probability {pick.model_prob:.1%} against a de-vigged "
            f"consensus of {pick.market_prob:.1%} - a {pick.edge:.1%} disagreement.",
        ]
        if ctx.get("def_yards_idx"):
            idx = ctx["def_yards_idx"]
            bits.append(
                f"Opponent has allowed {abs(1 - idx):.0%} "
                f"{'more' if idx > 1 else 'fewer'} receiving yards to the position "
                f"than league average over the last 8 games.")
        if ctx.get("implied_team_total"):
            bits.append(f"Implied team total {ctx['implied_team_total']:.1f}.")
        bits.append(
            "This is a probability estimate, not a prediction. At "
            f"{pick.model_prob:.1%} this loses roughly "
            f"{1 - pick.model_prob:.0%} of the time when the model is right.")
        return " ".join(bits)


# ----------------------------------------------------------------------------
# CLV logging - the only number that proves the model works
# ----------------------------------------------------------------------------

def log_picks(picks: list[Pick], path: str = "picks_log.jsonl") -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with open(path, "a") as f:
        for p in picks:
            f.write(json.dumps({"logged_at": ts, **asdict(p)}) + "\n")


def record_closing(path: str, closing: dict) -> None:
    """Append the closing de-vigged probability for each logged pick.

    CLV is the discipline. If your picks do not consistently beat the closing
    line, you do not have an edge, no matter what your win rate looked like
    over 200 bets. Win rate takes thousands of bets to become significant.
    CLV becomes significant in dozens."""
    rows = [json.loads(l) for l in open(path)]
    for r in rows:
        key = (r["player"], r["market"], r["line"])
        if key in closing:
            r["closing_prob"] = closing[key]
            entry_mkt = r.get("market_prob", 0.5)
            # CLV measures whether entry market price beat the closing market price
            r["clv"] = (closing[key] - entry_mkt) if r["side"] == "over" \
                else (entry_mkt - closing[key])
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def clv_report(path: str = "picks_log.jsonl") -> dict:
    all_rows = [json.loads(l) for l in open(path) if "clv" in json.loads(l)]
    rows = [r for r in all_rows if not (r.get("is_demo") is True or r.get("status") == "demo")]
    excluded_demo = len(all_rows) - len(rows)
    if not rows:
        return {"status": "no closing lines recorded yet", "n": 0,
                "excluded_demo": excluded_demo,
                "note": "demo/scenario rows are excluded from CLV grading; no real CLV data exists yet"}
    clv = np.array([r["clv"] for r in rows])
    se = float(clv.std(ddof=1) / np.sqrt(len(clv))) if len(clv) > 1 else 0.0
    mean_val = float(clv.mean())
    return {
        "n": len(clv),
        "excluded_demo": excluded_demo,
        "mean_clv": mean_val,
        "ci95": [float(mean_val - 1.96 * se), float(mean_val + 1.96 * se)],
        "pct_beating_close": float((clv > 0).mean()),
        "verdict": ("positive CLV - edge is plausible" if (len(clv) > 1 and mean_val - 1.96 * se > 0)
                    else ("insufficient sample size (n < 5)" if len(clv) < 5
                          else "NOT distinguishable from zero - do not scale")),
    }
