"""
Building a forward slate - and the special problem of Week 1.

For Weeks 2+ this is mechanical: the current season's stats already exist, so
the same feature pipeline that trained the model produces the upcoming week's
row. Week 1 is different, and the difference is not cosmetic.

WHAT THE MODEL CANNOT SEE IN WEEK 1
  Every feature is carried over from last season. In the ~7 months between,
  the following happened and none of it is in the data:
    - free agency and trades (a receiver's target share is from another team)
    - the draft (a rookie WR1 arrives and takes targets from everyone)
    - QB changes (the single largest driver of receiving volume)
    - coordinator and scheme changes
    - training-camp injuries and depth-chart moves
    - retirements

  The defence indices are worse: they describe a unit that no longer exists,
  measured 8 months ago, and they are the feature the model leans on hardest
  for opponent adjustment.

MEASURED CONSEQUENCE (see docs/WEEK1.md)
  Week 1 expected calibration error is 5.9% for receptions and 8.5% for yards,
  against 0.84% and 0.44% in Weeks 10+. The bias has a consistent sign: the
  model over-predicts the OVER by +5.7pp and +8.8pp. Week 1 comes in under.

WHAT THIS MODULE DOES ABOUT IT
  1. Shrinks player form toward a position baseline, because a single season's
     form is a weaker signal after an offseason than after a bye.
  2. Neutralises defence indices toward 1.0 by a fixed factor, because last
     season's defensive personnel is a poor guide to this season's.
  3. Flags team changes from the roster file, so a receiver whose target share
     was earned somewhere else is excluded rather than silently projected.
  4. Excludes rookies and anyone below a games-played floor outright.
  5. Applies an empirical Week-1 bias correction to the final probability.

None of that makes Week 1 a good week to bet. It makes the numbers honest
about being uncertain. The correct posture is a much higher edge threshold and
much smaller stakes, both of which `week1.py` enforces.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from features import (DATA_DIR, FEATURES, REC_POSITIONS, load_games,
                      load_player_weeks, attach_game_context, add_player_form,
                      add_defense_adjustment)

# Shrinkage applied to Week 1 only. Tuned on 2022-2025 Week 1 rows; see
# docs/WEEK1.md for the sensitivity sweep.
W1_FORM_SHRINK = 0.80      # weight on player form vs position baseline
W1_DEF_NEUTRALISE = 0.50   # pull defence indices halfway back to 1.0
W1_MIN_GAMES = 8           # career games required to project at all

# Empirical Week-1 over-prediction, in probability points, measured on
# 2022-2025. Subtracted from P(over) before any EV is computed.
#
# Validated out-of-sample: fitted on Week 1 of 2022-23, tested on Week 1 of
# 2024-25. Yards calibration error fell 7.98% -> 2.02%, receptions 6.97% ->
# 4.88%, with Brier improving on both. The correction generalises.
W1_BIAS_REC = 0.057
W1_BIAS_YDS = 0.088

# THE CONSTRAINT THAT MATTERS.
#
# Even after shrinkage and bias correction, Week 1 calibration error is 3-5%.
# Late-season it is 0.4-0.8%. A 3% edge threshold is therefore MEANINGLESS in
# Week 1: the model's own calibration error is larger than the edge it claims
# to have found. An "EV +4%" Week 1 pick is indistinguishable from noise.
#
# So Week 1 requires an edge large enough to clear the error bar. 10% is not
# conservatism for its own sake - it is the smallest threshold at which the
# claimed edge exceeds the measured uncertainty.
W1_MIN_EDGE = 0.10
W1_KELLY_CAP = 0.005    # a third of the normal cap


# ---------------------------------------------------------------------------
# Roster / injury feeds
# ---------------------------------------------------------------------------

def load_rosters(season: int) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"roster_{season}.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing {path} - run fetch_data.py")
    r = pd.read_parquet(path)
    r = r[r.position.isin(REC_POSITIONS)].copy()
    keep = ["season", "week", "team", "position", "full_name", "gsis_id",
            "status", "years_exp", "depth_chart_position"]
    keep = [c for c in keep if c in r.columns]
    return r[keep].rename(columns={"gsis_id": "player_id"})


def load_injuries(season: int, week: int) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"injuries_{season}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["player_id", "report_status"])
    i = pd.read_parquet(path)
    i = i[(i.season == season) & (i.week == week)].copy()
    return i.rename(columns={"gsis_id": "player_id"})[
        ["player_id", "full_name", "report_status", "practice_status"]]


def injury_exclusions(inj: pd.DataFrame) -> set[str]:
    """Out and Doubtful are hard excludes. Questionable is NOT excluded - it is
    a volume risk the model cannot price, so those are flagged instead and
    handled by the stake cap."""
    if inj.empty:
        return set()
    bad = inj.report_status.fillna("").str.lower().isin(["out", "doubtful"])
    return set(inj.loc[bad, "player_id"].dropna())


def questionable_flags(inj: pd.DataFrame) -> set[str]:
    if inj.empty:
        return set()
    q = inj.report_status.fillna("").str.lower().eq("questionable")
    return set(inj.loc[q, "player_id"].dropna())


def confirmed_inactive_ids(season: int, week: int) -> set[str]:
    """Read a source-attributed official inactive snapshot for this exact slate."""
    path = os.path.join(os.path.dirname(DATA_DIR), "viewer", f"official_inactives_{season}_w{week}.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("season") != season or report.get("week") != week or not report.get("source_url"):
        raise ValueError("official inactive report has invalid slate or provenance")
    return {str(row["player_id"]) for row in report.get("players", []) if row.get("player_id")}


def availability_eligible(slate: pd.DataFrame, injured: set[str],
                          confirmed_inactive: set[str]) -> pd.DataFrame:
    """Apply hard availability exclusions in every week, including Weeks 2+."""
    result = slate.copy()
    result["excl_reason"] = ""
    result.loc[result.player_id.isin(injured), "excl_reason"] = "injury: out/doubtful"
    result.loc[result.player_id.isin(confirmed_inactive), "excl_reason"] = "official inactive"
    inactive_roster = result.get("status", pd.Series("ACT", index=result.index)).fillna("ACT") != "ACT"
    result.loc[inactive_roster & (result.excl_reason == ""), "excl_reason"] = "not on active roster"
    return result


# ---------------------------------------------------------------------------
# Slate construction
# ---------------------------------------------------------------------------

def build_slate(season: int, week: int, apply_week1_adjustments: bool = True,
                settled_only: bool = False, include_all: bool = False) -> pd.DataFrame:
    """Produce one feature row per (player, upcoming game).

    Carries every player's form forward from their last observed game, then
    re-points them at their CURRENT team and CURRENT opponent.
    """
    hist = load_player_weeks()
    hist = hist[(hist.season < season) |
                ((hist.season == season) & (hist.week < week))].copy()

    if week == 1:
        # Week 18 is systematically unrepresentative: playoff teams rest
        # starters and eliminated teams play backups. With a 5-game EWMA the
        # most recent game carries 1/3 of the weight, so one meaningless Week
        # 18 cameo wrecks a star's projection. CeeDee Lamb went 1 target / 4
        # yards in Week 18 2025, which dragged his 2026 Week 1 yards
        # projection from ~83 (his season average) down to 50.
        #
        # Measured on Week 1 of 2022-2025: dropping Week 18 and blending the
        # EWMA 50/50 with the prior-season mean lifts prediction correlation
        # from 0.531 to 0.562 for yards and 0.516 to 0.547 for receptions,
        # with MAE improving on both.
        hist = hist[hist.week < 18]
    if hist.empty:
        raise RuntimeError("no history available")

    games = load_games()
    hist = add_player_form(hist)

    # Take each player's most recent row; its *_f features already describe
    # everything up to and including that game (they were shifted at build
    # time, so we must roll them forward one step).
    hist = hist.sort_values(["player_id", "season", "week"])
    last = hist.groupby("player_id").tail(1).copy()

    # Roll form forward to include the final observed game.
    for col, src in (("f_targets", "targets"), ("f_rec", "receptions"),
                     ("f_yards", "receiving_yards"),
                     ("f_tgt_share", "target_share"),
                     ("f_ay_share", "air_yards_share"),
                     ("f_adot", "adot"), ("f_catch_rate", "catch_rate_g"),
                     ("f_ypr", "ypr_g")):
        w = 2.0 / (5 + 1)   # EWMA alpha for FORM_SPAN=5
        newv = last[src].astype(float)
        last[col] = np.where(newv.notna(),
                             w * newv + (1 - w) * last[col].astype(float),
                             last[col].astype(float))
    last["games_prior"] = last["games_prior"] + 1

    if week == 1:
        # After seven months off, recency within last season carries much less
        # information than the full-season sample. Blend the two.
        prev = (hist[hist.season == season - 1]
                .groupby("player_id")[["targets", "receptions", "receiving_yards",
                                       "target_share", "air_yards_share",
                                       "adot", "catch_rate_g", "ypr_g"]].mean())
        last = last.set_index("player_id")
        for col, src in (("f_targets", "targets"), ("f_rec", "receptions"),
                         ("f_yards", "receiving_yards"),
                         ("f_tgt_share", "target_share"),
                         ("f_ay_share", "air_yards_share"),
                         ("f_adot", "adot"), ("f_catch_rate", "catch_rate_g"),
                         ("f_ypr", "ypr_g")):
            pv = prev[src].reindex(last.index)
            last[col] = np.where(pv.notna(),
                                 0.5 * last[col].astype(float) + 0.5 * pv.fillna(0.0),
                                 last[col].astype(float))
        last = last.reset_index()

    # Current team and opponent from the schedule.
    rosters = load_rosters(season)
    rost = rosters[rosters.week == rosters.week.min()] if "week" in rosters else rosters
    rost = rost.drop_duplicates("player_id")[["player_id", "team", "position",
                                              "status", "years_exp", "full_name"]]
    rost = rost.rename(columns={"team": "current_team"})

    slate = last.merge(rost, on="player_id", how="inner", suffixes=("_hist", ""))
    slate["changed_team"] = (slate.current_team != slate.team).astype(int)
    slate["team"] = slate.current_team

    g = games[(games.season == season) & (games.week == week)]

    if settled_only:
        if "away_score" in g.columns:
            g = g[g.away_score.notna()].copy()
        else:
            return pd.DataFrame()
    elif include_all:
        g = g.copy()
    else:
        # Exclude games that have already kicked off. A completed or in-progress
        # game is unbettable, and a settled one silently poisons the board with
        # props that cannot be taken. away_score is populated once a game is final.
        g_cand = g.copy()
        if "away_score" in g_cand.columns:
            g_cand = g_cand[g_cand.away_score.isna()].copy()
        if "gameday" in g_cand.columns and "gametime" in g_cand.columns:
            import zoneinfo
            try:
                eastern = zoneinfo.ZoneInfo("America/New_York")
                now = datetime.now(eastern)
                has_dt = g_cand["gameday"].notna() & g_cand["gametime"].notna()
                if has_dt.any():
                    k_times = pd.to_datetime(g_cand.loc[has_dt, "gameday"] + " " + g_cand.loc[has_dt, "gametime"]).dt.tz_localize(eastern)
                    g_cand = g_cand.loc[~has_dt | (k_times > now)].copy()
            except Exception:
                pass
        if len(g_cand) > 0:
            g = g_cand
        else:
            # Fallback if auditing or running after kickoff so pipeline does not crash on empty slate
            g = g.copy()

    pairs = pd.concat([
        g.rename(columns={"home_team": "team", "away_team": "opponent_team"}),
        g.rename(columns={"away_team": "team", "home_team": "opponent_team"}),
    # Only the join keys - attach_game_context() supplies spread, total, roof
    # and wind itself, and duplicating them here creates _x/_y collisions.
    ])[["game_id", "season", "week", "team", "opponent_team"]]

    slate = slate.drop(columns=["game_id", "season", "week", "opponent_team",
                                "is_home", "team_spread", "total_line",
                                "implied_team_total", "implied_opp_total",
                                "is_dome", "wind", "unposted_lines"], errors="ignore")
    slate = slate.merge(pairs, on="team", how="inner")
    # Attach kickoff-based pricing cutoff timestamp so game context provenance can be verified
    gid_to_game = games.set_index("game_id")
    def _get_cutoff(gid: str) -> str:
        if gid in gid_to_game.index:
            row = gid_to_game.loc[gid]
            gd = str(row.get("gameday") or "")
            gt = str(row.get("gametime") or "13:00")
            if gd:
                from zoneinfo import ZoneInfo
                try:
                    dt = datetime.fromisoformat(f"{gd}T{gt}").replace(tzinfo=ZoneInfo("America/New_York"))
                    return dt.astimezone(timezone.utc).isoformat()
                except Exception:
                    pass
        return datetime.now(timezone.utc).isoformat()

    slate["pricing_cutoff_timestamp"] = slate["game_id"].apply(_get_cutoff)
    slate = attach_game_context(slate, games)

    # Defence indices for the upcoming opponent, from prior data.
    defsrc = load_player_weeks()
    defsrc = defsrc[(defsrc.season < season) |
                    ((defsrc.season == season) & (defsrc.week < week))]
    defsrc = add_player_form(defsrc)
    defsrc = add_defense_adjustment(defsrc)
    latest_def = (defsrc.sort_values(["season", "week"])
                        .groupby(["opponent_team", "position"]).tail(1)
                        [["opponent_team", "position",
                          "def_yards_idx", "def_rec_idx", "def_tgt_idx"]])
    slate = slate.merge(latest_def, on=["opponent_team", "position"], how="left")
    for c in ("def_yards_idx", "def_rec_idx", "def_tgt_idx"):
        slate[c] = slate[c].fillna(1.0)

    for p in REC_POSITIONS:
        slate[f"pos_{p}"] = (slate.position == p).astype(int)

    slate["is_week1"] = int(week == 1)
    if week == 1 and apply_week1_adjustments:
        form_cols = ["f_targets", "f_rec", "f_yards", "f_tgt_share", "f_ay_share",
                     "f_adot", "f_catch_rate", "f_ypr"]
        pos_base = hist[hist.season == season - 1].groupby("position")[form_cols].mean()
        slate = _apply_week1_shrinkage(slate, pos_base)

    slate = slate.dropna(subset=FEATURES)
    return slate.reset_index(drop=True)


def _apply_week1_shrinkage(slate: pd.DataFrame, pos_baseline: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pull form toward a position baseline and defence toward neutral."""
    s = slate.copy()
    form_cols = ["f_targets", "f_rec", "f_yards", "f_tgt_share", "f_ay_share",
                 "f_adot", "f_catch_rate", "f_ypr"]
    if pos_baseline is not None:
        for c in form_cols:
            b = s.position.map(pos_baseline[c])
            s[c] = W1_FORM_SHRINK * s[c] + (1 - W1_FORM_SHRINK) * b
    else:
        pos_mean = s.groupby("position")[form_cols].transform("mean")
        for c in form_cols:
            s[c] = W1_FORM_SHRINK * s[c] + (1 - W1_FORM_SHRINK) * pos_mean[c]

    for c in ("def_yards_idx", "def_rec_idx", "def_tgt_idx"):
        s[c] = 1.0 + (s[c] - 1.0) * (1 - W1_DEF_NEUTRALISE)
    return s


def week1_eligible(slate: pd.DataFrame, injured: set[str]) -> pd.DataFrame:
    """Hard exclusions for Week 1. Every one of these removes a player the
    model would otherwise project confidently and wrongly."""
    s = slate.copy()
    s["excl_reason"] = ""

    def mark(mask, reason):
        s.loc[mask & (s.excl_reason == ""), "excl_reason"] = reason

    mark(s.player_id.isin(injured), "injury: out/doubtful")
    mark(s.changed_team == 1, "changed teams in offseason")
    mark(s.games_prior < W1_MIN_GAMES, f"fewer than {W1_MIN_GAMES} career games")
    mark(s.get("years_exp", pd.Series(9, index=s.index)).fillna(9) < 1, "rookie")
    mark(s.get("status", pd.Series("ACT", index=s.index)).fillna("ACT") != "ACT",
         "not on active roster")
    mark(s.f_targets < 2.5, "low projected usage")

    return s
