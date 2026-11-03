"""Rolling 5/10/20-game form — strictly as-of (no leakage by construction).

Every history column is computed with a per-player groupby on the PLAYED
subset and shifted one game forward: the row for game G only ever sees
games strictly BEFORE G. A walk-forward date split then re-checks this at
the date level (tests/test_walkforward.py asserts both layers).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FORM_WINDOWS, GARBAGE_MARGIN


def add_rolling_form(
    df: pd.DataFrame,
    windows: tuple[int, ...] = FORM_WINDOWS,
) -> pd.DataFrame:
    """Adds, per player-game (played rows only; DNP rows get NaN history):
      form{w}_ppm      rolling mean points-per-minute over last w played games
      form{w}_minutes  rolling mean minutes over last w played games
      games_played     cumulative count of played games before this one
      garbage5_share   share of last 5 games that were blowouts (context, not signal)
    """
    df = df.copy()
    played = ~df["dnp"]
    is_garbage = df["margin"].abs() >= GARBAGE_MARGIN

    for col_suffix, source_col in (
        ("ppm", "ppm"),
        ("minutes", "minutes"),
    ):
        for w in windows:
            df[f"form{w}_{col_suffix}"] = (
                df.loc[played]
                .groupby("player_id")[source_col]
                .transform(lambda s: s.shift(1).rolling(w, min_periods=1).mean())
                .reindex(df.index)
            )

    df["games_played"] = (
        df.loc[played].groupby("player_id").cumcount().reindex(df.index)
    )

    df["garbage5_share"] = (
        df.loc[played]
        .groupby("player_id")["margin"]
        .transform(lambda s: (s.abs() >= GARBAGE_MARGIN).shift(1).rolling(5, min_periods=1).mean())
        .reindex(df.index)
    )

    # Trend: recent5 vs long20 — a stable, interpretable form signal.
    df["form_trend_ppm"] = df.get("form5_ppm") - df.get("form20_ppm")
    # Flag rows whose history is too thin for the long window.
    df["thin_history"] = df["games_played"].fillna(0) < min(windows)
    return df
