"""Dataset assembly: normalized provider rows -> tidy player-game DataFrame.

One row per player-game with everything the feature layer needs, plus
team-game aggregates (margin, possessions pace) derived from the same box
scores. No feature leakage happens here — history columns are built later
with strict as-of joins (see features/form.py).
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

NUMERIC_COLS = [
    "minutes", "pts", "rebounds", "assists", "fg3m", "fgm", "fga",
    "ftm", "fta", "oreb", "tov",
]


def _coerce_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def build_dataset(rows: list[dict], games: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Returns (df, meta). df is one row per player-game; meta carries
    provenance + league context used downstream."""
    if not rows:
        raise ValueError("no box-score rows supplied — fail-closed, refusing to build")
    df = pd.DataFrame(rows)

    # ── game join: fill opponent / is_home from the games table ─────────────
    games_df = pd.DataFrame(games) if games else pd.DataFrame()
    if not games_df.empty:
        game_ctx = games_df[["game_id", "home_team", "away_team"]].rename(
            columns={"home_team": "_home", "away_team": "_away"}
        )
        df = df.merge(game_ctx, on="game_id", how="left", suffixes=("", "_g"))
        df["is_home"] = np.where(
            df.get("is_home", pd.Series(index=df.index, dtype="object")).isna(),
            df["team"] == df["_home"],
            df["is_home"],
        )
        df["opponent"] = np.where(df["team"] == df["_home"], df["_away"], df["_home"])

    # ── numeric coercion + DNP handling ─────────────────────────────────────
    for col in NUMERIC_COLS:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = _coerce_float(df[col])
    df["minutes"] = df["minutes"].fillna(0.0).clip(0, 48)
    df["dnp"] = (df["minutes"] <= 0) | df["pts"].isna()
    df["pts"] = df["pts"].fillna(0.0)

    # Played subset drives all history stats.
    played = df[~df["dnp"]].copy()

    # ── team-game totals: margin + pace (possessions) ───────────────────────
    tg = played.groupby(["game_id", "team"], as_index=False).agg(
        team_pts=("pts", "sum"),
        fga=("fga", "sum"), oreb=("oreb", "sum"),
        tov=("tov", "sum"), fta=("fta", "sum"),
    )
    tg["poss"] = (
        tg["fga"].fillna(0) - tg["oreb"].fillna(0)
        + tg["tov"].fillna(0) + 0.44 * tg["fta"].fillna(0)
    )
    league_avg_poss = float(tg["poss"].mean()) if len(tg) else np.nan
    tg["pace_ratio"] = tg["poss"] / league_avg_poss if league_avg_poss else np.nan

    # margin per team-game: derive each team-game's opponent from the games
    # table, then self-join the scores. (When no games table is supplied the
    # margin stays NaN — pace and history features still work.)
    if not games_df.empty:
        tg = tg.merge(
            games_df[["game_id", "home_team", "away_team"]], on="game_id", how="left"
        )
        tg["opponent"] = np.where(
            tg["team"] == tg["home_team"], tg["away_team"], tg["home_team"]
        )
        opp_scores = tg[["game_id", "opponent", "team_pts"]].rename(
            columns={"team_pts": "opp_team_pts"}
        )
        tg = tg.merge(opp_scores, on=["game_id", "opponent"], how="left")
    else:
        tg["opponent"] = np.nan
        tg["opp_team_pts"] = np.nan
    tg["margin"] = tg["team_pts"] - tg["opp_team_pts"].fillna(tg["team_pts"])

    df = df.merge(
        tg[["game_id", "team", "margin", "poss", "pace_ratio"]],
        on=["game_id", "team"], how="left",
    )
    df = df.merge(
        tg[["game_id", "opponent", "pace_ratio"]].rename(
            columns={"pace_ratio": "opp_pace_ratio"}
        ),
        on=["game_id", "opponent"], how="left",
    )
    # NOTE: opponent DEFENSIVE strength is deliberately NOT merged here.
    # Points allowed in the game being predicted is outcome leakage; the
    # projector learns per-team defensive ratings from the training window
    # only (see model/projector.py TeamContext). The same-game margin and
    # pace_ratio columns above are safe because the feature layer only ever
    # consumes them SHIFTED into history (features/form.py).

    # ── derived per-player-game ─────────────────────────────────────────────
    df["ppm"] = np.where(
        (~df["dnp"]) & (df["minutes"] > 0), df["pts"] / df["minutes"].replace(0, np.nan), np.nan
    )
    df = df.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)

    played_dates = sorted(d for d in df.loc[~df["dnp"], "game_date"].dropna().unique())
    meta = {
        "source": df["source"].iloc[0] if "source" in df.columns else "unknown",
        "all_fixture": bool(df["_fixture"].all()) if "_fixture" in df.columns else True,
        "n_rows": int(len(df)),
        "n_games": int(df["game_id"].nunique()),
        "n_players": int(df["player_id"].nunique()),
        "max_game_date": played_dates[-1] if played_dates else None,
        "min_game_date": played_dates[0] if played_dates else None,
        "league_avg_poss": league_avg_poss,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return df, meta
