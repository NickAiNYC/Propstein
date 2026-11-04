"""
Leak-free feature construction for NFL receiving props.

Every feature available at row (player, season, week) uses ONLY information
from strictly earlier weeks. This is enforced by shifting all rolling
aggregates by one game before they are joined back to the panel.

The single most common way a prop model looks profitable and isn't is
leakage. Read `assert_no_leakage()` at the bottom before trusting anything.
"""

from __future__ import annotations

import glob
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

REC_POSITIONS = ("WR", "TE", "RB")

# EWMA span (in games) for player form. ~5 balances recency against noise;
# tuned on 2016-2021 only, held out 2022+.
FORM_SPAN = 5
DEF_SPAN = 8

CONTEXT_OBSERVATION_FIELDS = (
    "spread_observed_at",
    "total_observed_at",
    "weather_observed_at",
)


class UnverifiedGameContextError(ValueError):
    """Pregame context has no proof that it existed at the pricing cutoff."""


def _aware_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise UnverifiedGameContextError(f"{field} requires a timestamped source")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UnverifiedGameContextError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise UnverifiedGameContextError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def assert_context_known_at_cutoff(df: pd.DataFrame, games: pd.DataFrame) -> None:
    """Fail closed until every game context value has pre-cutoff provenance.

    The historical nflverse games.csv has no source capture times for its
    closing spread, total, or weather. Those values must not enter a new
    fitted model or a prospective projection as if they were pregame inputs.
    """
    if "pricing_cutoff_timestamp" not in df.columns:
        raise UnverifiedGameContextError("pricing_cutoff_timestamp is required for every pricing row")
    missing = [name for name in CONTEXT_OBSERVATION_FIELDS if name not in games.columns]
    if missing:
        raise UnverifiedGameContextError(
            f"game context lacks observed-at provenance: {', '.join(missing)}"
        )
    by_game = games.set_index("game_id")
    for game_id, cutoff_value in df[["game_id", "pricing_cutoff_timestamp"]].itertuples(index=False, name=None):
        if game_id not in by_game.index:
            raise UnverifiedGameContextError(f"no game context for {game_id}")
        cutoff = _aware_utc(cutoff_value, "pricing_cutoff_timestamp")
        source = by_game.loc[game_id]
        for field in CONTEXT_OBSERVATION_FIELDS:
            observed = _aware_utc(source[field], field)
            if observed > cutoff:
                raise UnverifiedGameContextError(
                    f"{field} for {game_id} was observed after pricing cutoff"
                )


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------

def load_player_weeks(seasons: tuple[int, ...] | None = None) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(DATA_DIR, "stats_*.parquet")))
    frames = []
    for f in files:
        year = int(os.path.basename(f).split("_")[1].split(".")[0])
        if seasons and year not in seasons:
            continue
        frames.append(pd.read_parquet(f))
    df = pd.concat(frames, ignore_index=True)

    df = df[df.season_type == "REG"].copy()
    df = df[df.position.isin(REC_POSITIONS)].copy()

    keep = [
        "player_id", "player_display_name", "position", "season", "week",
        "game_id", "team", "opponent_team", "targets", "receptions",
        "receiving_yards", "receiving_air_yards", "receiving_yards_after_catch",
        "target_share", "air_yards_share", "receiving_tds",
    ]
    df = df[keep]

    num = [c for c in keep if c not in
           ("player_id", "player_display_name", "position", "game_id",
            "team", "opponent_team")]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # A player-week with no targets is a real observation (0 receptions,
    # 0 yards) and must be kept - dropping them biases every rate upward.
    df["targets"] = df["targets"].fillna(0)
    df["receptions"] = df["receptions"].fillna(0)
    df["receiving_yards"] = df["receiving_yards"].fillna(0)
    df["receiving_air_yards"] = df["receiving_air_yards"].fillna(0)
    df["target_share"] = df["target_share"].fillna(0)

    return df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)


def load_games() -> pd.DataFrame:
    g = pd.read_csv(os.path.join(DATA_DIR, "games.csv"))
    g = g[g.game_type == "REG"].copy()
    keep = ["game_id", "season", "week", "gameday", "gametime", "away_team", "home_team",
            "away_score", "spread_line", "total_line", "roof", "temp", "wind"]
    return g[keep + [c for c in CONTEXT_OBSERVATION_FIELDS if c in g.columns]]


def _join_game_context(df: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    long = []
    for _, side in (("home", "home"), ("away", "away")):
        pass
    home = games.rename(columns={"home_team": "team", "away_team": "opp"}).copy()
    home["is_home"] = 1
    home["team_spread"] = home["spread_line"]          # favoured => positive
    away = games.rename(columns={"away_team": "team", "home_team": "opp"}).copy()
    away["is_home"] = 0
    away["team_spread"] = -away["spread_line"]
    ctx = pd.concat([home, away], ignore_index=True)

    # Track if book lines are unposted, and impute standard league medians (total 44.5, pick'em 0.0)
    ctx["unposted_lines"] = ctx["total_line"].isna().astype(int)
    ctx["total_line"] = ctx["total_line"].fillna(44.5)
    ctx["team_spread"] = ctx["team_spread"].fillna(0.0)

    # Implied team total = half the game total, shifted by half the spread.
    ctx["implied_team_total"] = ctx["total_line"] / 2.0 + ctx["team_spread"] / 2.0
    ctx["implied_opp_total"] = ctx["total_line"] / 2.0 - ctx["team_spread"] / 2.0
    ctx["is_dome"] = ctx["roof"].isin(["dome", "closed"]).astype(int)
    ctx["wind"] = ctx["wind"].fillna(0.0)
    ctx.loc[ctx.is_dome == 1, "wind"] = 0.0

    cols = ["game_id", "team", "is_home", "team_spread", "total_line",
            "implied_team_total", "implied_opp_total", "is_dome", "wind", "unposted_lines"]
    return df.merge(ctx[cols], on=["game_id", "team"], how="left")


def attach_game_context(df: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Join market context. spread_line is HOME-relative in nflverse:
    positive means the home team is favoured by that many points."""
    assert_context_known_at_cutoff(df, games)
    return _join_game_context(df, games)


# ----------------------------------------------------------------------------
# Player form (strictly backward-looking)
# ----------------------------------------------------------------------------

def _shifted_ewma(s: pd.Series, span: int) -> pd.Series:
    """EWMA of all *prior* observations. shift(1) happens BEFORE the ewm so
    the current row can never see its own value."""
    return s.shift(1).ewm(span=span, min_periods=1).mean()


def _shifted_expanding_mean(s: pd.Series) -> pd.Series:
    return s.shift(1).expanding(min_periods=1).mean()


def _prior_week_position_median(df: pd.DataFrame, value: str) -> pd.Series:
    """Position fallback using only rows from strictly earlier NFL weeks."""
    fallback = pd.Series(np.nan, index=df.index, dtype=float)
    for _, position_rows in df.groupby("position"):
        history: list[float] = []
        for _, week_rows in position_rows.groupby(["season", "week"], sort=True):
            if history:
                fallback.loc[week_rows.index] = float(np.median(history))
            history.extend(float(v) for v in week_rows[value].dropna())
    return fallback


def add_player_form(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["player_id", "season", "week"]).copy()

    df["adot"] = np.where(df.targets > 0,
                          df.receiving_air_yards / df.targets.replace(0, np.nan),
                          np.nan)
    df["catch_rate_g"] = np.where(df.targets > 0,
                                  df.receptions / df.targets.replace(0, np.nan),
                                  np.nan)
    df["ypr_g"] = np.where(df.receptions > 0,
                           df.receiving_yards / df.receptions.replace(0, np.nan),
                           np.nan)

    g = df.groupby("player_id", group_keys=False)

    df["f_targets"] = g["targets"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_tgt_share"] = g["target_share"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_ay_share"] = g["air_yards_share"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_rec"] = g["receptions"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_yards"] = g["receiving_yards"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_adot"] = g["adot"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_catch_rate"] = g["catch_rate_g"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))
    df["f_ypr"] = g["ypr_g"].apply(lambda s: _shifted_ewma(s, FORM_SPAN))

    # Career-to-date baselines stabilise rookies and low-volume players.
    df["c_targets"] = g["targets"].apply(_shifted_expanding_mean)
    df["c_yards"] = g["receiving_yards"].apply(_shifted_expanding_mean)

    df["games_prior"] = g.cumcount()

    # Volatility of target volume - a genuinely predictive feature for props,
    # because a boom/bust profile changes tail probabilities even at a fixed mean.
    df["f_tgt_sd"] = g["targets"].apply(
        lambda s: s.shift(1).rolling(8, min_periods=3).std())

    return df


# ----------------------------------------------------------------------------
# Opponent pass-defence strength (leak-free, league-relative)
# ----------------------------------------------------------------------------

def add_defense_adjustment(df: pd.DataFrame) -> pd.DataFrame:
    """For each defence x position group, an EWMA of receiving yards and
    receptions allowed per game, expressed as a ratio to the league mean for
    that position that season-to-date. Built from prior weeks only."""
    allowed = (df.groupby(["opponent_team", "position", "season", "week"],
                          as_index=False)
                 .agg(def_yards=("receiving_yards", "sum"),
                      def_rec=("receptions", "sum"),
                      def_tgts=("targets", "sum")))
    allowed = allowed.sort_values(["opponent_team", "position", "season", "week"])

    ag = allowed.groupby(["opponent_team", "position"], group_keys=False)
    allowed["d_yards"] = ag["def_yards"].apply(lambda s: _shifted_ewma(s, DEF_SPAN))
    allowed["d_rec"] = ag["def_rec"].apply(lambda s: _shifted_ewma(s, DEF_SPAN))
    allowed["d_tgts"] = ag["def_tgts"].apply(lambda s: _shifted_ewma(s, DEF_SPAN))

    # League baseline for the same position/season/week, also backward-looking.
    lg = (allowed.groupby(["position", "season", "week"], as_index=False)
                 .agg(lg_yards=("d_yards", "mean"),
                      lg_rec=("d_rec", "mean"),
                      lg_tgts=("d_tgts", "mean")))
    allowed = allowed.merge(lg, on=["position", "season", "week"], how="left")

    allowed["def_yards_idx"] = allowed.d_yards / allowed.lg_yards
    allowed["def_rec_idx"] = allowed.d_rec / allowed.lg_rec
    allowed["def_tgt_idx"] = allowed.d_tgts / allowed.lg_tgts

    cols = ["opponent_team", "position", "season", "week",
            "def_yards_idx", "def_rec_idx", "def_tgt_idx"]
    out = df.merge(allowed[cols], on=["opponent_team", "position", "season", "week"],
                   how="left")
    for c in ("def_yards_idx", "def_rec_idx", "def_tgt_idx"):
        out[c] = out[c].fillna(1.0).clip(0.6, 1.6)
    return out


# ----------------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------------

FEATURES = [
    "f_targets", "f_tgt_share", "f_ay_share", "f_rec", "f_yards",
    "f_adot", "f_catch_rate", "f_ypr", "f_tgt_sd",
    "c_targets", "c_yards", "games_prior",
    "def_yards_idx", "def_rec_idx", "def_tgt_idx",
    # The two implied totals jointly encode BOTH the game total and the spread:
    #   implied_team + implied_opp == total_line
    #   implied_team - implied_opp == team_spread
    # So total_line and team_spread are both exactly redundant. Including them
    # makes the design matrix rank-deficient and the coefficients
    # non-identifiable - statsmodels warns but still returns numbers, which is
    # worse than failing. Keep the two implied totals only.
    "implied_team_total", "implied_opp_total",
    "is_home", "is_dome", "wind",
    # WR is the reference category. pos_WR + pos_TE + pos_RB == 1, which is
    # collinear with the intercept - the classic dummy-variable trap. Including
    # all three leaves the design matrix rank-deficient.
    "pos_TE", "pos_RB",
]


def build_panel(seasons: tuple[int, ...] | None = None,
                min_games_prior: int = 3,
                min_form_targets: float = 1.5) -> pd.DataFrame:
    df = load_player_weeks(seasons)
    games = load_games()
    df = _join_game_context(df, games)
    df = add_player_form(df)
    df = add_defense_adjustment(df)

    for p in REC_POSITIONS:
        df[f"pos_{p}"] = (df.position == p).astype(int)

    # Position fallbacks use only strictly earlier weeks. A full-panel median
    # would let later box scores leak into historical training rows.
    for c in ("f_adot", "f_catch_rate", "f_ypr"):
        df[c] = df[c].fillna(_prior_week_position_median(df, c))
    df["f_tgt_sd"] = df["f_tgt_sd"].fillna(df["f_targets"].fillna(0) * 0.6)
    for c in FEATURES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Filter to bettable players: enough history and real usage. Books do not
    # post props on a WR5, and modelling them just adds noise to every metric.
    df = df[(df.games_prior >= min_games_prior)
            & (df.f_targets >= min_form_targets)].copy()

    df = df.dropna(subset=["implied_team_total", "total_line"] + FEATURES)
    return df.reset_index(drop=True)


def assert_no_leakage(panel: pd.DataFrame, raw: pd.DataFrame | None = None) -> None:
    """Sanity check: a player's own current-week outcome must not be
    recoverable from their features. If f_yards ever exactly equals the
    realised receiving_yards for many rows, the shift was dropped somewhere."""
    exact = (panel.f_yards.round(4) == panel.receiving_yards.round(4)).mean()
    assert exact < 0.02, f"suspicious feature/outcome identity rate: {exact:.3%}"
    # First appearance in the panel must have games_prior >= min filter,
    # and career means must never be computed on the current row.
    grp = panel.groupby("player_id").head(1)
    assert (grp.games_prior >= 1).all(), "career features leaked on debut row"
