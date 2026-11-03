"""Context adjustments — team pace, opponent defence, rest.

LEAKAGE RULE: TeamContext ratings are fitted on the TRAINING window only
and applied frozen to the prediction window. The dataset's same-game
pace columns are descriptive/history features, never prediction inputs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import B2B_MINUTES_MULT, OPP_MULT_BOUNDS, PACE_MULT_BOUNDS


class TeamContext:
    def __init__(self):
        self.team_pace: dict[str, float] = {}
        self.team_def_ratio: dict[str, float] = {}
        self.league_avg_pts: float = 0.0

    def fit(self, train: pd.DataFrame) -> "TeamContext":
        played = train[~train["dnp"]]
        if played.empty:
            return self
        tg = (
            played.groupby(["game_id", "team"], as_index=False)
            .agg(team_pts=("pts", "sum"), poss=("poss", "mean"),
                 opponent=("opponent", "first"))
        )
        # points ALLOWED per team-game: look up the opponent side's score
        # in the same game (no merge — the left frame keys on "team")
        score_lookup = tg.set_index(["game_id", "team"])["team_pts"]
        tg["pts_allowed"] = [
            score_lookup.get((g, o), np.nan)
            for g, o in zip(tg["game_id"], tg["opponent"])
        ]

        league_poss = float(tg["poss"].mean())
        league_pts = float(tg["team_pts"].mean())
        self.league_avg_pts = league_pts

        self.team_pace = {
            team: float(np.clip(grp["poss"].mean() / league_poss, 0.7, 1.3))
            for team, grp in tg.groupby("team")
        }
        self.team_def_ratio = {
            team: float(np.clip(grp["pts_allowed"].mean() / league_pts, 0.7, 1.3))
            for team, grp in tg.groupby("team") if grp["pts_allowed"].notna().any()
        }
        return self

    def apply(self, df: pd.DataFrame, schedule_df: pd.DataFrame | None = None) -> pd.DataFrame:
        df = df.copy()
        pace_own = df["team"].map(self.team_pace).fillna(1.0)
        pace_opp = df["opponent"].map(self.team_pace).fillna(1.0)
        df["pace_mult"] = (
            ((pace_own + pace_opp) / 2.0).clip(*PACE_MULT_BOUNDS).round(4)
        )
        def_ratio = df["opponent"].map(self.team_def_ratio).fillna(1.0)
        df["opp_mult"] = def_ratio.clip(*OPP_MULT_BOUNDS).round(4)

        # Back-to-back rest: gap of exactly 1 calendar day between this
        # player's previous PLAYED game (from the full schedule history)
        # and the current one. Schedule facts only — no trained parameters.
        base = schedule_df if schedule_df is not None else df
        played_hist = (
            base[~base["dnp"]][["player_id", "game_date"]]
            .dropna()
            .groupby("player_id")["game_date"]
            .apply(lambda s: np.sort(pd.to_datetime(s).values))
        )
        dates_by_player = played_hist.to_dict()

        df["b2b"] = False
        row_dates = pd.to_datetime(df["game_date"]).values
        b2b_flags = []
        for player_id, row_date in zip(df["player_id"], row_dates):
            hist = dates_by_player.get(player_id)
            if hist is None or len(hist) == 0:
                b2b_flags.append(False)
                continue
            idx = int(np.searchsorted(hist, row_date, side="left"))
            prev = hist[idx - 1] if idx > 0 else None
            if prev is None:
                b2b_flags.append(False)
                continue
            gap_days = (row_date - prev) / np.timedelta64(1, "D")
            b2b_flags.append(bool(1.0 <= gap_days < 2.0))
        df["b2b"] = b2b_flags
        df["rest_mult"] = np.where(df["b2b"], B2B_MINUTES_MULT, 1.0)
        return df
