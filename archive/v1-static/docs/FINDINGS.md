# Findings

Real data: nflverse weekly stats 2016–2025, 33,549 qualifying player-weeks,
1,057 receivers. Walk-forward, train on all prior seasons, test 2022–2025.

## 1. The model is well calibrated

This is the genuine result and it needs no odds data.

| Market | Brier | vs constant | Skill | ECE |
|---|---|---|---|---|
| Receptions | 0.2312 | 0.2411 | **+4.1%** | **0.75%** |
| Receiving yards | 0.2465 | 0.2499 | **+1.4%** | **1.11%** |

Expected calibration error under 1.2% means when the model says 58%, it happens
about 58% of the time. That is the necessary foundation for any EV claim, and
it is real.

Note the asymmetry: receptions carries roughly 3× the skill of yards. Yards is
dominated by single long catches and is close to irreducible. **If you bet one
market, bet receptions.**

Calibration degrades above p≈0.60 (model says 63%, actual 58.5%). Isotonic
recalibration is fitted on a held-out prior season to correct this. Do not
disable it.

## 2. Two backtest artifacts I hit and corrected — watch for both

**Artifact A: mean-based proxy lines.** First run showed +21–29% ROI. The
proxy line was a rolling *mean*; receiving distributions are right-skewed, so
the over hit only 37% of the time. The model was hammering unders against a
line set 13 points too high. Real books set near the *median*.

**Artifact B: assuming −110/−110 on whole-number receptions lines.** After
switching to median lines, receptions still went over only 40.6%. That is
discreteness, not edge — a receptions line genuinely sits at P(over)≈0.41 and
books price it as over +105 / under −125. Assuming −110 both ways hands the
model free money.

Both artifacts individually produced double-digit fake ROI. If you fork any
public prop repo, check for these first.

## 3. The corrected result, and what it does not mean

Against a market priced off a form-only baseline's own de-vigged probability
with 4.5% hold:

| Market | Min EV | n | Win% | ROI | **Bet rate** |
|---|---|---|---|---|---|
| Receptions | 4% | 7,434 | 55.9% | +12.9% | **70%** |
| Rec yards | 4% | 7,795 | 56.6% | +10.8% | **74%** |

**The bet rate is the tell.** Firing on 70% of the board means the opponent is
weak, not that the model is strong. This measures "context beats form-only,"
which is true and worth knowing — defense adjustment, implied team total, and
aDOT carry real information beyond a rolling average. It does not measure
whether you beat DraftKings, who also has all of this plus injury reports and
everyone else's money.

**Expect live performance several points worse. Possibly below break-even.**

## 4. On parlays — you were more right than I was

I initially said parlays compound negative EV. That's half the story. The math:

| Legs | Effective hold | Payout | EV if true edge +3% | if 0% | if −2% |
|---|---|---|---|---|---|
| 1 | 4.3% | 1.87 | +3.0% | 0.0% | −2.0% |
| 3 | 12.4% | 6.53 | +9.3% | 0.0% | −5.9% |
| 5 | 19.8% | 22.84 | **+15.9%** | 0.0% | **−9.6%** |

Per-leg breakeven probability is **invariant** to leg count. Parlays are pure
leverage on the *sign* of your edge. Five legs turns a 3% edge into 15.9% —
and a −2% edge into −9.6%.

So parlays are the correct instrument *if* the edge is real, and the fastest
way to lose the bankroll if it isn't. Everything rests on step 3, which is
unverified. **Singles until CLV is positive; parlays after.**

### Same-game correlation is large

Measured on the joint NB–Gamma sampler: receptions-over and yards-over for the
same player have **φ ≈ 0.65**. A 2-leg same-player SGP has a true joint
probability of 58.6% versus 43.8% under independence — a **1.34× correlation
lift**.

Any book pricing that SGP as independent would be handing out ~100% EV. They
don't; SGP engines apply a correlation adjustment. But **under-adjustment is a
real and findable pricing error**, and it's the most promising angle in this
whole build. It's a hunt against a specific book's SGP pricing, not a
forecasting problem. `parlay.py` prices the true joint so you can measure it.

## 5. On alt lines — my claim was overstated, correcting it

I said the model would be least reliable in the tail. The data disagrees.
Perturbing the Gamma shape parameter k by ±15%:

| Line | P(over) | Fair odds | Relative error in P |
|---|---|---|---|
| 62.8 | 50.0% | +100 | 0.8% |
| 85.0 | 31.1% | +221 | 0.3% |
| 95.0 | 24.4% | +310 | 1.1% |
| 110.0 | 16.4% | +509 | 2.4% |
| 125.0 | 10.7% | +834 | 4.0% |

The compound NB–Gamma is stable out to roughly **+300**. Past +800 the shape
parameter starts to dominate and I would not trust it. So alt lines up to +300
are legitimate territory — my initial objection was wrong at the magnitudes you'd
actually use.

What remains true: alt lines don't *create* edge. The book prices them off the
same distribution. They're a way to express an existing edge at different
variance, not a way to manufacture one.

## 6. What I did not build, and why

- **X/Twitter scraping.** By the time target-share takes are posted, the line
  has moved. The fast information is inactives and beat-writer injury news —
  an RSS/API problem, not a sentiment problem. Hook is in `agent.py` via the
  `injuries` set; wire nflverse injuries or a beat-writer feed.
- **pro-football-reference scraping.** Sports Reference rate-limits and blocks
  scrapers, and their terms prohibit it. nflverse is free, licensed, and
  better — it's what the data actually comes from.
- **Vercel deployment.** Serverless execution ceiling and ephemeral filesystem;
  a statsmodels GLM fit and a persistent CLV log both break. Railway config is
  in the repo.
