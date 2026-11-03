"""
Walk-forward evaluation against FAIR proxy lines.

WHAT THIS MEASURES
  1. Calibration - when the model says 58%, does it happen 58% of the time?
     This needs no odds data and is the real scientific result.
  2. Whether contextual information (defence, game total, spread, aDOT)
     beats a form-only forecaster that sets the line at its own median.

WHAT THIS STILL DOES NOT MEASURE
  Whether the model beats a real sportsbook. A real line is set by people with
  the same public data, plus injury designations, practice reports, beat
  writers, and the aggregate opinion of everyone who has already bet. The
  form-only baseline here is a punching bag, not a market.

  Treat any win rate below as an UPPER bound on live performance and assume the
  real number is several points worse. The only test that settles it is closing
  line value against actual posted prices. See docs/HISTORICAL_ODDS.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st
from sklearn.isotonic import IsotonicRegression

from features import build_panel, assert_no_leakage
from baseline import BaselineLineSetter
from model import ReceivingModel, prob_to_american, american_to_decimal

VIG = 0.045


def american_to_decimal_vec(o):
    o = np.asarray(o, float)
    return np.where(o > 0, 1 + o / 100.0, 1 + 100.0 / -o)

BREAKEVEN_110 = 0.5238


def brier_and_calibration(p, y, bins=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    brier = float(np.mean((p - y) ** 2))
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum() >= 30:
            rows.append({"bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": int(m.sum()),
                         "pred": round(float(p[m].mean()), 3),
                         "actual": round(float(y[m].mean()), 3)})
    cal = pd.DataFrame(rows)
    ece = float(np.average((cal.pred - cal.actual).abs(), weights=cal.n)) if len(cal) else np.nan
    return brier, ece, cal


def _score_season(m, base, test):
    lines = base.lines(test)
    p = m.predict_params(test)
    d = pd.DataFrame({
        "season": test.season.values, "week": test.week.values,
        "player": test.player_display_name.values, "position": test.position.values,
        "line_rec": lines.line_rec.values, "line_yards": lines.line_yards.values,
        "mu_rec": p.mu_rec.values, "mu_ypr": p.mu_ypr.values,
        "mkt_p_rec": lines.mkt_p_rec.values, "mkt_p_yards": lines.mkt_p_yards.values,
        "receptions": test.receptions.values, "receiving_yards": test.receiving_yards.values,
    })
    d = d[(d.line_rec >= 1.5) & (d.line_yards >= 15)].reset_index(drop=True)
    d["p_rec"] = m.p_rec_over_vec(d.mu_rec.values, d.line_rec.values)
    d["p_yards"] = m.p_yards_over_vec(d.mu_rec.values, d.mu_ypr.values, d.line_yards.values)
    d["hit_rec"] = (d.receptions > d.line_rec).astype(int)
    d["hit_yards"] = (d.receiving_yards > d.line_yards).astype(int)
    return d


def run(test_seasons=(2022, 2023, 2024, 2025), calibrate=True):
    panel = build_panel()
    assert_no_leakage(panel)
    print(f"panel: {len(panel):,} player-weeks | {panel.season.min()}-{panel.season.max()} "
          f"| {panel.player_id.nunique():,} players\n")

    frames = []
    for season in test_seasons:
        train = panel[panel.season < season]
        test = panel[panel.season == season]
        if train.season.nunique() < 4 or test.empty:
            continue

        m = ReceivingModel.fit(train)
        base = BaselineLineSetter.fit(train)

        iso_r = iso_y = None
        if calibrate:
            cal_season = int(train.season.max())
            inner = panel[panel.season < cal_season]
            m_in = ReceivingModel.fit(inner)
            base_in = BaselineLineSetter.fit(inner)
            cd = _score_season(m_in, base_in, panel[panel.season == cal_season])
            iso_r = IsotonicRegression(out_of_bounds="clip").fit(cd.p_rec, cd.hit_rec)
            iso_y = IsotonicRegression(out_of_bounds="clip").fit(cd.p_yards, cd.hit_yards)

        d = _score_season(m, base, test)
        d["p_rec_raw"], d["p_yards_raw"] = d.p_rec, d.p_yards
        if calibrate:
            d["p_rec"] = iso_r.predict(d.p_rec)
            d["p_yards"] = iso_y.predict(d.p_yards)
        frames.append(d)
        print(f"  {season}: {len(d):,} props | over-rate rec={d.hit_rec.mean():.3f} "
              f"yds={d.hit_yards.mean():.3f}  (fair line => should sit near 0.50)")

    d = pd.concat(frames, ignore_index=True)
    print()

    for market, pcol, hcol, mcol in (
            ("RECEPTIONS", "p_rec", "hit_rec", "mkt_p_rec"),
            ("REC YARDS", "p_yards", "hit_yards", "mkt_p_yards")):
        brier, ece, cal = brier_and_calibration(d[pcol], d[hcol])
        base_rate = d[hcol].mean()
        brier_base = float(np.mean((base_rate - d[hcol]) ** 2))
        print(f"=== {market} ===")
        print(f"  n={len(d):,}  over-rate={base_rate:.4f}")
        print(f"  Brier {brier:.4f} vs constant {brier_base:.4f} "
              f"-> skill {1 - brier / brier_base:+.3%}   ECE {ece:.3%}")
        print(cal.to_string(index=False))
        simulate(d, pcol, hcol, mcol, vig=VIG)
        print()
    return d


def simulate(d, pcol, hcol, mcol, vig=0.045):
    """Bet into a market priced off the BASELINE's probability, with vig.
    Edge here means: information the form-only market did not have."""
    over_odds = prob_to_american(d[mcol].values, vig)
    under_odds = prob_to_american(1 - d[mcol].values, vig)
    do = american_to_decimal_vec(over_odds)
    du = american_to_decimal_vec(under_odds)
    p = d[pcol].values
    hit = d[hcol].values

    ev_over = p * (do - 1) - (1 - p)
    ev_under = (1 - p) * (du - 1) - p

    print(f"  {'min EV':>7} {'n':>6} {'win%':>7} {'95% CI':>17} {'ROI':>8} {'p':>7}")
    # BET-RATE IS THE SANITY CHECK. Against a real book a genuine prop edge
    # appears on a few percent of the board. A bet-rate above ~20% means the
    # opponent is weak, not that the model is strong.
    for min_ev in (0.00, 0.02, 0.04, 0.06):
        take_o = ev_over > min_ev
        take_u = ev_under > min_ev
        n = int(take_o.sum() + take_u.sum())
        if n < 100:
            print(f"  {min_ev:>7.2f} {n:>6,}   (too few bets to evaluate)")
            continue
        pnl = np.concatenate([
            np.where(hit[take_o] == 1, do[take_o] - 1, -1.0),
            np.where(hit[take_u] == 0, du[take_u] - 1, -1.0)])
        wins = int((hit[take_o] == 1).sum() + (hit[take_u] == 0).sum())
        wr = wins / n
        roi = pnl.mean()
        se_roi = pnl.std(ddof=1) / np.sqrt(n)
        se = np.sqrt(max(wr * (1 - wr), 1e-9) / n)
        pval = 1 - st.norm.cdf(roi / max(se_roi, 1e-9))
        print(f"  {min_ev:>7.2f} {n:>6,} {wr:>6.2%} "
              f"[{wr - 1.96 * se:>6.2%},{wr + 1.96 * se:>6.2%}] "
              f"{roi:>+7.2%} {pval:>7.3f}  bet-rate={n / len(d):.1%}")


if __name__ == "__main__":
    run()
