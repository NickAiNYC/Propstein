"""NBAPointsProjector — the interpretable v1 assembly.

    mean_pts = ppm_hat × minutes_hat × rest_mult × pace_mult × opp_mult
               × form_mult × availability_mult
    sd_pts   = sqrt( (sd_ppm × minutes_hat)² + (ppm_hat × sd_minutes)² )
               × var_inflation                      [floored at SD_FLOOR_PTS]

Every multiplier is train-window-only and every projection row carries an
`explain` dict with the raw components, so a published number can always
be re-derived by hand from its receipt.

Shrinkage: player ppm means/sds are shrunk toward position means
(k=8 pseudo-games) because early-season rolling stats overreact.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import (
    FORM_MULT_BOUNDS,
    MINUTES_FLOOR,
    SD_FLOOR_PTS,
)
from ..features.context import TeamContext
from ..features.minutes import ExpectedMinutesModel
from ..util import finite_or
from .distribution import PointsDistribution

PPM_SHRINK_GAMES = 4.0      # pseudo-games of role prior (dampened from 8.0 to prevent under-bias on stars)
FORM_TREND_DAMPING = 0.5    # damp the 5-vs-20 trend before clipping


class NBAPointsProjector:
    def __init__(self):
        self.minutes_model = ExpectedMinutesModel()
        self.context = TeamContext()
        self.player_ppm: dict[str, dict] = {}
        self.position_ppm: dict[str, dict] = {}

    # ── fit (training window only) ──────────────────────────────────────────
    def fit(self, train: pd.DataFrame) -> "NBAPointsProjector":
        self.minutes_model.fit(train)
        self.context.fit(train)

        played = train[~train["dnp"]].copy()
        pos_ppm = played.groupby("position")["ppm"].agg(["mean", "std", "count"])

        # Role-stratified priors: separate primary scorers/starters from bench
        # so high-usage stars are not shrunk toward 10th-man replacement rates.
        player_roles = {}
        for pid, grp in played.groupby("player_id"):
            avg_min = float(grp["minutes"].mean())
            tot_min = float(grp["minutes"].sum())
            tot_fga = (
                float(grp["fga"].sum())
                if "fga" in grp.columns and pd.notna(grp["fga"]).any()
                else 0.0
            )
            fga_pm = (tot_fga / tot_min) if tot_min > 0 else 0.0
            if avg_min >= 24.0 and fga_pm >= 0.48:
                tier = "star"
            elif avg_min >= 24.0:
                tier = "starter"
            elif avg_min >= 14.0:
                tier = "rotation"
            else:
                tier = "bench"
            player_roles[pid] = tier

        played["_tier"] = played["player_id"].map(player_roles).fillna("rotation")
        tier_ppm = played.groupby(["position", "_tier"])["ppm"].agg(["mean", "std", "count"])

        self.player_ppm = {}
        for pid, grp in played.groupby("player_id"):
            n = len(grp)
            mean = float(grp["ppm"].mean())
            sd = finite_or(grp["ppm"].std(ddof=1), 0.0)
            pos = grp["position"].iloc[0]
            tier = player_roles.get(pid, "rotation")

            if (pos, tier) in tier_ppm.index and tier_ppm.loc[(pos, tier), "count"] >= 2:
                t_row = tier_ppm.loc[(pos, tier)]
                prior_mean = float(t_row["mean"])
                prior_sd = finite_or(float(t_row["std"]), 0.12)
            elif pos in pos_ppm.index:
                prior_mean = float(pos_ppm.loc[pos, "mean"])
                prior_sd = finite_or(float(pos_ppm.loc[pos, "std"]), 0.12)
            else:
                prior_mean = mean
                prior_sd = 0.12

            k = PPM_SHRINK_GAMES
            self.player_ppm[pid] = {
                "ppm_mean": (n * mean + k * prior_mean) / (n + k),
                "ppm_sd": (n * sd + k * prior_sd) / (n + k),
                "n": n,
                "position": pos,
                "tier": tier,
                "season_pts_mean": float(grp["pts"].mean()),
                "season_pts_sd": finite_or(grp["pts"].std(ddof=1), 0.0),
            }
        self.position_ppm = {
            pos: {"mean": float(row["mean"]), "sd": finite_or(row["std"], 0.12)}
            for pos, row in pos_ppm.iterrows()
        }
        return self

    # ── predict (test window; features already carry as-of history) ─────────
    def predict(self, test: pd.DataFrame, history: pd.DataFrame | None = None) -> pd.DataFrame:
        """`history` is the training frame — used ONLY for schedule facts
        (back-to-back detection). All fitted parameters stay frozen."""
        if self.player_ppm == {} and not self.position_ppm:
            raise RuntimeError("projector.fit() must run before predict()")

        ctx = self.context.apply(test, schedule_df=history)
        mins = self.minutes_model.predict(ctx)
        ctx = ctx.merge(
            mins[["player_id", "game_id", "minutes_hat", "sd_minutes", "minutes_source", "n_recent"]],
            on=["player_id", "game_id"], how="left",
        )

        rows = []
        for _, r in ctx.iterrows():
            params = self.player_ppm.get(r["player_id"])
            if params is None:
                pos_params = self.position_ppm.get(r["position"], {"mean": 0.55, "sd": 0.14})
                ppm_hat, sd_ppm, n_hist = pos_params["mean"], pos_params["sd"], 0
                ppm_source = "position_fallback"
            else:
                ppm_hat, sd_ppm, n_hist = params["ppm_mean"], params["ppm_sd"], params["n"]
                ppm_source = "player_shrunk"

            # Form: damped 5-vs-20 ppm trend, clipped; neutral when history thin.
            f5, f20 = r.get("form5_ppm"), r.get("form20_ppm")
            if pd.notna(f5) and pd.notna(f20) and n_hist >= 10 and f20 > 0.2:
                trend = (f5 - f20) / f20
                form_mult = float(np.clip(1.0 + FORM_TREND_DAMPING * trend, *FORM_MULT_BOUNDS))
                form_basis = f"trend={trend:+.3f}"
            else:
                form_mult, form_basis = 1.0, "thin_history"

            minutes_hat = float(r["minutes_hat"]) * float(r.get("rest_mult", 1.0))
            mean_pts = (
                ppm_hat * minutes_hat * float(r["pace_mult"]) * float(r["opp_mult"])
                * form_mult * float(r.get("availability_mult", 1.0))
            )
            var_infl = float(r.get("var_inflation", 1.0))
            sd_pts = np.sqrt(
                (sd_ppm * minutes_hat) ** 2 + (ppm_hat * float(r["sd_minutes"])) ** 2
            ) * var_infl
            sd_pts = max(float(sd_pts), SD_FLOOR_PTS)

            dist = PointsDistribution(mean=mean_pts, sd=sd_pts)
            rows.append({
                "player_id": r["player_id"],
                "player_display_name": r.get("player_display_name", r["player_id"]),
                "team": r["team"],
                "opponent": r["opponent"],
                "game_id": r["game_id"],
                "game_date": r["game_date"],
                "position": r.get("position", ""),
                "mean_pts": round(mean_pts, 2),
                "sd_pts": round(sd_pts, 2),
                "fair_line": dist.fair_line(),
                "below_minutes_floor": bool(minutes_hat < MINUTES_FLOOR),
                "explain": {
                    "ppm_hat": round(float(ppm_hat), 4),
                    "ppm_source": ppm_source,
                    "n_history_games": int(n_hist),
                    "minutes_hat": round(minutes_hat, 2),
                    "minutes_source": r.get("minutes_source", ""),
                    "pace_mult": float(r["pace_mult"]),
                    "opp_mult": float(r["opp_mult"]),
                    "form_mult": round(form_mult, 4),
                    "form_basis": form_basis,
                    "rest_mult": float(r.get("rest_mult", 1.0)),
                    "availability_mult": float(r.get("availability_mult", 1.0)),
                    "var_inflation": var_infl,
                    "sd_ppm": round(float(sd_ppm), 4),
                    "sd_minutes": float(r["sd_minutes"]),
                },
            })
        return pd.DataFrame(rows)

    # ── naive baseline (season-mean points, season sd) for calibration ──────
    def naive_baseline(self, test: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in test.iterrows():
            params = self.player_ppm.get(r["player_id"])
            rows.append({
                "player_id": r["player_id"],
                "game_id": r["game_id"],
                "naive_mean": params["season_pts_mean"] if params else 10.0,
                "naive_sd": (params["season_pts_sd"] if params else 6.0) or 6.0,
            })
        return pd.DataFrame(rows)
