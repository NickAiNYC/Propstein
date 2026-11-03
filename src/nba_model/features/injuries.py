"""Availability / rotation adjustments from the project's injury feed.

Consumes the existing PropWire availability schema (viewer/nba_injuries_*.json
shape): rows with player_id, team, game_id, report_status, as_of, and — when
the upstream report supplies them — vacated_minutes / redistribution_plan.

Adjustments (all explicit, all explainable):
  own status "Out"                    -> availability_mult = 0 (not projected)
  own status Questionable/GTD/Doubtful -> variance inflation
  teammate(s) Out                     -> capped minutes boost, share-based
  missing/stale feed                  -> neutral 1.0 (recorded, never guessed)
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    QUESTIONABLE_VAR_INFLATION,
    TEAMMATE_OUT_BOOST_CAP,
    TEAMMATE_OUT_MINUTES_BOOST,
)

BOOST_STATUSES = {"out", "out (rehab assignment)", "inactive", "suspended"}
VAR_STATUSES = {"questionable", "game time decision", "gtd", "doubtful"}


def add_availability_adjustments(
    df: pd.DataFrame,
    injuries: list[dict] | None,
) -> pd.DataFrame:
    df = df.copy()
    df["availability_mult"] = 1.0
    df["var_inflation"] = 1.0
    df["teammates_out"] = 0

    if not injuries:
        df["availability_source"] = "none"
        df["own_status"] = ""
        return df
    df["availability_source"] = "project_feed"

    inj_df = pd.DataFrame(injuries)
    inj_df["status_key"] = inj_df["report_status"].fillna("").str.lower()

    # Own status per (player_id, game_id). The merge supplies the column —
    # do NOT pre-create own_status above (pandas suffix collision).
    own = inj_df[["player_id", "game_id", "status_key"]].rename(
        columns={"status_key": "own_status"}
    )
    df = df.merge(
        own.drop_duplicates(subset=["player_id", "game_id"]),
        on=["player_id", "game_id"], how="left",
    )
    df["own_status"] = df["own_status"].fillna("")

    # Teammate-out map per (game_id, team): OUT rows only
    out_map = (
        inj_df[inj_df["status_key"].isin(BOOST_STATUSES)]
        .groupby(["game_id", "team"])["player_id"]
        .apply(set)
        .to_dict()
    )

    boost_values, var_values, n_out_values = [], [], []
    for _, row in df.iterrows():
        var = QUESTIONABLE_VAR_INFLATION if row["own_status"] in VAR_STATUSES else 1.0
        var_values.append(var)

        out_ids = out_map.get((row["game_id"], row["team"]), set())
        boost, n_out = 0.0, 0
        for out_id in out_ids:
            if out_id == row["player_id"]:
                continue
            # Share-based: each Out teammate adds a flat share of the boost
            # cap. When the upstream report ships a redistribution_plan, the
            # caller may refine availability_mult per beneficiary (feed wins).
            boost += TEAMMATE_OUT_MINUTES_BOOST
            n_out += 1
        boost_values.append(round(min(boost, TEAMMATE_OUT_BOOST_CAP), 4))
        n_out_values.append(n_out)

    df["availability_mult"] = 1.0 + pd.Series(boost_values, index=df.index)
    df["var_inflation"] = pd.Series(var_values, index=df.index)
    df["teammates_out"] = pd.Series(n_out_values, index=df.index)
    df.loc[df["own_status"].isin(BOOST_STATUSES), "availability_mult"] = 0.0
    return df
