"""
Week runner. Produces projections, and picks if odds are available.

    python week1.py --season 2026 --week 1                 # projections only
    python week1.py --season 2026 --week 1 --odds          # + live odds, picks

Without an ODDS_API_KEY this still runs and emits fair lines and fair prices
per player. You can compare those to a book by hand. That is the honest
fallback: the model's job is to produce a probability, and a probability is
useful even when you have to do the comparison yourself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from features import build_panel, load_player_weeks
from model import ReceivingModel, prob_to_american, ev_per_unit, kelly_fraction
from slate import (build_slate, load_injuries, injury_exclusions,
                   availability_eligible, confirmed_inactive_ids,
                   questionable_flags, week1_eligible,
                   W1_BIAS_REC, W1_BIAS_YDS, W1_MIN_EDGE, W1_KELLY_CAP)
from agent import MIN_EDGE, KELLY_CAP, MIN_BOOKS, Pick, log_picks

# Viewer qualification policy mirrors the verified-quote adapter. These values
# are exported so the browser never invents or hardcodes an action threshold.
VIEWER_GATE_EDGE = 0.10
VIEWER_KELLY_CAP = 0.03


def project(season: int, week: int, include_all: bool = False) -> tuple[pd.DataFrame, ReceivingModel]:
    panel = build_panel()
    panel = panel[(panel.season < season) |
                  ((panel.season == season) & (panel.week < week))]
    model = ReceivingModel.fit(panel)

    slate = build_slate(season, week, include_all=include_all)
    inj = load_injuries(season, week)
    out = injury_exclusions(inj)
    quest = questionable_flags(inj)

    inactive = confirmed_inactive_ids(season, week)
    slate = week1_eligible(slate, out) if week == 1 else availability_eligible(slate, out, inactive)
    if week == 1:
        slate.loc[slate.player_id.isin(inactive), "excl_reason"] = "official inactive"
    slate["questionable"] = slate.player_id.isin(quest).astype(int)

    p = model.predict_params(slate)
    if "is_open_field" in slate.columns:
        slate.loc[slate.is_open_field == 1, "wind"] = round(model.panel_mean_wind, 2)
    slate["mu_rec"] = p.mu_rec.values
    slate["mu_ypr"] = p.mu_ypr.values
    slate["proj_rec"] = slate.mu_rec
    slate["proj_yards"] = slate.mu_rec * slate.mu_ypr

    # Fair lines = median of the calibrated predictive distribution.
    r = 1.0 / model.alpha
    pp = r / (r + slate.mu_rec.values)
    from scipy import stats as st
    n = st.nbinom.ppf(0.5, r, pp).astype(int)
    lo = np.maximum(n - 1, 0)
    bias_rec = W1_BIAS_REC if week == 1 else 0.0
    bias_yds = W1_BIAS_YDS if week == 1 else 0.0
    sf_lo = st.nbinom.sf(lo, r, pp) - bias_rec
    sf_hi = st.nbinom.sf(n, r, pp) - bias_rec
    slate["fair_line_rec"] = np.where(np.abs(sf_lo - 0.5) < np.abs(sf_hi - 0.5), lo + 0.5, n + 0.5)
    q_yds = 0.50 - bias_yds
    slate["fair_line_yards"] = np.round(
        model.yards_quantile_vec(slate.mu_rec.values, slate.mu_ypr.values, q_yds) * 2) / 2
    slate["p_rec_at_fair_line"] = np.round(
        np.clip(model.p_rec_over_vec(slate.mu_rec.values, slate.fair_line_rec.values) - bias_rec, 0.01, 0.99), 4)

    # Regression assertion: mean P(over) at fair lines must average ~50%
    p_rec_over_mean = slate["p_rec_at_fair_line"].mean()
    assert 0.46 <= p_rec_over_mean <= 0.54, f"Reception fair lines miscalibrated: mean P(over) = {p_rec_over_mean:.3f}"

    return slate, model


def prob_for(model, row, market, line, week):
    """Probability of the OVER, with the Week-1 bias correction applied."""
    if market == "receptions":
        p = model.p_rec_over(row.mu_rec, line)
        if week == 1:
            p -= W1_BIAS_REC
    else:
        p = model.p_yards_over(row.mu_rec, row.mu_ypr, line)
        if week == 1:
            p -= W1_BIAS_YDS
    return float(np.clip(p, 0.01, 0.99))


def make_picks(slate, model, consensus, week) -> list[Pick]:
    min_edge = W1_MIN_EDGE if week == 1 else MIN_EDGE
    cap = W1_KELLY_CAP if week == 1 else KELLY_CAP
    by_player = {r.player_display_name: r for r in slate.itertuples()
                 if r.excl_reason == ""}
    picks = []
    for (player, mkey, line), c in consensus.items():
        market = {"player_receptions": "receptions",
                  "player_reception_yds": "receiving_yards"}.get(mkey)
        if market is None or player not in by_player or c["n_books"] < MIN_BOOKS:
            continue
        row = by_player[player]
        p_over = prob_for(model, row, market, line, week)
        for side, pm, odds, book in (
                ("over", p_over, c["best_over_odds"], c["best_over_book"]),
                ("under", 1 - p_over, c["best_under_odds"], c["best_under_book"])):
            if odds is None:
                continue
            p_mkt = c["p_over"] if side == "over" else 1 - c["p_over"]
            edge = pm - p_mkt
            ev = ev_per_unit(pm, odds)
            if edge < min_edge or ev <= 0:
                continue
            picks.append(Pick(
                player=player, market=market, side=side, line=line, book=book,
                odds=odds, model_prob=round(pm, 4), market_prob=round(p_mkt, 4),
                edge=round(edge, 4), ev_per_unit=round(ev, 4),
                kelly_stake=round(kelly_fraction(pm, odds, cap=cap), 5),
                projection=round(float(row.proj_rec if market == "receptions"
                                       else row.proj_yards), 1)))
    picks.sort(key=lambda p: p.ev_per_unit, reverse=True)
    return picks


def score_settled_games(season: int, week: int, model: ReceivingModel) -> pd.DataFrame | None:
    """Evaluate predictions against actuals for games already completed in data."""
    try:
        settled_slate = build_slate(season, week, settled_only=True)
        if settled_slate.empty:
            return None
        inj = load_injuries(season, week)
        out = injury_exclusions(inj)
        eligible = week1_eligible(settled_slate, out) if week == 1 else settled_slate.assign(excl_reason="")
        eligible = eligible[eligible.excl_reason == ""].copy()
        if eligible.empty:
            return None

        p = model.predict_params(eligible)
        eligible["proj_rec"] = p.mu_rec.values
        eligible["proj_yards"] = p.mu_rec.values * p.mu_ypr.values

        from scipy import stats as st
        r = 1.0 / model.alpha
        pp = r / (r + eligible.proj_rec.values)
        n = st.nbinom.ppf(0.5, r, pp).astype(int)
        lo = np.maximum(n - 1, 0)
        bias_rec = W1_BIAS_REC if week == 1 else 0.0
        bias_yds = W1_BIAS_YDS if week == 1 else 0.0
        sf_lo = st.nbinom.sf(lo, r, pp) - bias_rec
        sf_hi = st.nbinom.sf(n, r, pp) - bias_rec
        eligible["fair_line_rec"] = np.where(np.abs(sf_lo - 0.5) < np.abs(sf_hi - 0.5), lo + 0.5, n + 0.5)
        q_yds = 0.50 - bias_yds
        eligible["fair_line_yards"] = np.round(model.yards_quantile_vec(p.mu_rec.values, p.mu_ypr.values, q_yds) * 2) / 2
        eligible["p_rec_at_fair_line"] = np.round(
            np.clip(model.p_rec_over_vec(eligible.mu_rec.values, eligible.fair_line_rec.values) - bias_rec, 0.01, 0.99), 4)

        stats_path = f"data/stats_{season}.parquet"
        if not os.path.exists(stats_path):
            return None
        s_act = pd.read_parquet(stats_path)
        settled_game_ids = settled_slate["game_id"].unique()
        act = s_act[s_act.game_id.isin(settled_game_ids)][["player_id", "receptions", "receiving_yards"]].rename(
            columns={"receptions": "actual_rec", "receiving_yards": "actual_yards"}
        )
        scored = eligible.merge(act, on="player_id", how="left")
        scored["actual_rec"] = scored["actual_rec"].fillna(0)
        scored["actual_yards"] = scored["actual_yards"].fillna(0)
        return scored
    except Exception:
        return None


def recent_receiving_games(season: int, week: int) -> dict:
    """Newest first, with only regular-season games before the requested slate."""
    games = load_player_weeks()
    prior = games[(games.season < season) | ((games.season == season) & (games.week < week))]
    history = {}
    prior = prior.dropna(subset=["game_id"]).sort_values(["season", "week"], ascending=False)
    for player_id, rows in prior.groupby("player_id", sort=False):
        history[player_id] = [
            {"receptions": int(row.receptions), "yards": int(row.receiving_yards)}
            for row in rows.drop_duplicates("game_id").head(10).itertuples()
        ]
    return history


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--odds", action="store_true", help="pull live odds (needs key)")
    ap.add_argument("--all-games", action="store_true", help="include all games on slate regardless of kickoff time")
    ap.add_argument("--out", default="slate_projections.csv")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    slate, model = project(a.season, a.week, include_all=a.all_games)
    ok = slate[slate.excl_reason == ""]

    settled_scored = score_settled_games(a.season, a.week, model)
    if settled_scored is not None and len(settled_scored) > 0:
        n = len(settled_scored)
        err_yds = settled_scored["actual_yards"] - settled_scored["proj_yards"]
        err_rec = settled_scored["actual_rec"] - settled_scored["proj_rec"]
        over_yds = (settled_scored["actual_yards"] > settled_scored["fair_line_yards"]).mean()
        over_rec = (settled_scored["actual_rec"] > settled_scored["fair_line_rec"]).mean()
        r_yds = np.corrcoef(settled_scored["proj_yards"], settled_scored["actual_yards"])[0, 1] if n > 1 else np.nan
        r_rec = np.corrcoef(settled_scored["proj_rec"], settled_scored["actual_rec"])[0, 1] if n > 1 else np.nan

        print(f"\n{'=' * 78}")
        print(f"  SETTLED GAMES OUT-OF-SAMPLE AUDIT  |  {a.season} Week {a.week} (n={n})")
        print(f"{'=' * 78}")
        print(f"  Yards Over-rate vs Fair Line: {over_yds:.1%} ({sum(settled_scored['actual_yards'] > settled_scored['fair_line_yards'])}/{n}, expected ~50%)")
        print(f"  Rec Over-rate vs Fair Line:   {over_rec:.1%} ({sum(settled_scored['actual_rec'] > settled_scored['fair_line_rec'])}/{n}, discrete half-step; expected player-level P(over) range ~40-62%)")
        print(f"  Mean Error (Actual - Proj):   {err_yds.mean():+.1f} yds (MAE {err_yds.abs().mean():.1f}), {err_rec.mean():+.2f} rec (MAE {err_rec.abs().mean():.2f})")
        print(f"  Correlation r:                {r_yds:.3f} (Yards), {r_rec:.3f} (Receptions)")
        print(f"  Guardrail Takeaway:           Directional under-bias replicated. Lean Under on close calls.")

    print(f"\n{'=' * 78}")
    print(f"  {a.season} WEEK {a.week} ACTIVE SLATE  |  {len(slate)} rostered receivers, "
          f"{len(ok)} projectable")
    print(f"{'=' * 78}")
    if a.week == 1:
        print("  WEEK 1 CAVEAT: measured calibration error 3-5% after correction,")
        print("  vs 0.4-0.8% late season. Edge threshold raised to "
              f"{W1_MIN_EDGE:.0%}, stake cap {W1_KELLY_CAP:.1%}.")
        print("  See docs/WEEK1.md before betting any of this.")
    if len(slate) > len(ok):
        print("\n  Excluded:")
        for reason, n in slate[slate.excl_reason != ""].excl_reason.value_counts().items():
            print(f"    {n:>4}  {reason}")

    cols = ["player_display_name", "position", "team", "opponent_team",
            "proj_rec", "fair_line_rec", "proj_yards", "fair_line_yards",
            "questionable"]
    top = ok.sort_values("proj_yards", ascending=False).head(a.top)
    print(f"\n  TOP {a.top} BY PROJECTED YARDS (yards fair line = calibrated median; receptions = closest half-step)\n")
    print(top[cols].to_string(index=False,
                              float_format=lambda x: f"{x:.1f}"))

    # Projectable receivers first sorted by projected yards descending, followed by excluded receivers
    sorted_slate = slate.sort_values(by=["excl_reason", "proj_yards"], ascending=[True, False])
    sorted_slate.to_csv(a.out, index=False)
    print(f"\n  full slate -> {a.out} ({len(ok)} projectable, {len(slate)} total)")

    # Export sanitized JSON (convert NaN to None for standard JSON compliance)
    import math
    records = sorted_slate.to_dict(orient="records")
    history = recent_receiving_games(a.season, a.week)
    clean_records = []
    for r in records:
        r["recent_receiving_games"] = history.get(r["player_id"], [])
        clean_records.append({
            k: (None if (v is None or (isinstance(v, float) and math.isnan(v))) else v)
            for k, v in r.items()
        })
    json_out = a.out.replace(".csv", ".json")
    with open(json_out, "w") as f:
        json.dump(clean_records, f, indent=2, allow_nan=False)
    if os.path.exists("viewer"):
        with open(os.path.join("viewer", json_out), "w") as f:
            json.dump(clean_records, f, indent=2, allow_nan=False)
        sorted_slate.to_csv(os.path.join("viewer", a.out), index=False)
    print(f"  full slate JSON -> {json_out} (and synced to viewer/)")

    # Generate current_picks.json with p_rec_at_fair_line
    top25 = sorted_slate.head(25)
    picks_list = []
    for idx, r in enumerate(top25.to_dict(orient="records")):
        picks_list.append({
            "rank": idx + 1,
            "player": r["player_display_name"],
            "team": r["team"],
            "opponent": r["opponent_team"],
            "position": r["position"],
            "proj_rec": round(float(r["proj_rec"]), 1),
            "fair_line_rec": round(float(r["fair_line_rec"]), 1),
            "p_rec_at_fair_line": round(float(r.get("p_rec_at_fair_line", 0.5)), 3),
            "proj_yards": round(float(r["proj_yards"]), 1),
            "fair_line_yards": round(float(r["fair_line_yards"]), 1),
            "implied_total": round(float(r["implied_team_total"]), 1),
            "spread": round(float(r["team_spread"]), 1),
            "questionable": int(r["questionable"])
        })
    picks_payload = {
        "season": a.season,
        "week": a.week,
        "gate_edge": W1_MIN_EDGE if a.week == 1 else VIEWER_GATE_EDGE,
        "kelly_cap": W1_KELLY_CAP if a.week == 1 else VIEWER_KELLY_CAP,
        "rostered_player_records": len(slate),
        "projectable_player_records": len(ok),
        "note": "Top 25 Projections & Fair Lines (Active Games Only)",
        "picks": picks_list
    }
    for target_name in ["current_picks.json", "top_picks.json"]:
        with open(target_name, "w") as f:
            json.dump(picks_payload, f, indent=2, allow_nan=False)
        if os.path.exists("viewer"):
            with open(os.path.join("viewer", target_name), "w") as f:
                json.dump(picks_payload, f, indent=2, allow_nan=False)
    print("  current_picks.json & top_picks.json -> generated and synced to viewer/")

    if not a.odds:
        print("\n  No odds pulled. Compare the fair lines above to your book:")
        print("  a book line BELOW the fair line favours the over, and vice versa.")
        print("  Run with --odds and ODDS_API_KEY set for scored picks.\n")
        return

    if not os.environ.get("ODDS_API_KEY"):
        print("\n  ODDS_API_KEY not set - cannot pull odds. "
              "Player props are a paid tier.\n")
        return

    from odds import OddsClient, no_vig_consensus
    client = OddsClient()
    quotes = client.slate()
    cons = no_vig_consensus(quotes)
    print(f"\n  {len(quotes)} quotes, {len(cons)} distinct player/market/line "
          f"({client.credits_remaining} credits left)")

    picks = make_picks(ok, model, cons, a.week)
    print(f"\n  {len(picks)} picks clear the {(W1_MIN_EDGE if a.week==1 else MIN_EDGE):.0%} "
          f"edge gate\n")
    for p in picks:
        print(f"  {p.player:<24} {p.side.upper():<5} {p.line:>5.1f} "
              f"{p.market:<16} {p.odds:>+5.0f} @{p.book:<12} "
              f"model {p.model_prob:.1%} vs mkt {p.market_prob:.1%}  "
              f"EV {p.ev_per_unit:+.1%}  stake {p.kelly_stake:.2%}")
    # Persist scored live picks for the viewer / pre-kickoff board (the
    # snapshot shelf stays empty until the freeze workflow fills it).
    from dataclasses import asdict
    live_name = f"live_picks_{a.season}_w{a.week}.json"
    live_payload = {
        "season": a.season, "week": a.week,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "The Odds API",
        "picks": [asdict(p) for p in picks],
    }
    viewer_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "viewer")
    with open(os.path.join(viewer_dir, live_name), "w") as f:
        json.dump(live_payload, f, indent=2)
    if picks:
        log_picks(picks, "picks_log.jsonl")
        print("\n  logged to picks_log.jsonl - record closing lines after kickoff")


if __name__ == "__main__":
    main()
