# PropWire Edge Gate — Preregistered Statistical Specification

Status: **Preregistered governance document.** The parameters below are fixed
before any new prospective observations are collected for any sport. Any
change after registration is a protocol amendment, must be committed with its
own rationale BEFORE the affected data is examined, and never retroactively.

This document satisfies v3 directive TASK 2. It defines one evaluation per
sport (NFL, NBA, UFC). Nothing here authorizes commercial claims; passing a
gate is a necessary condition, and commercialization additionally requires
compliance approval (fail-closed, see §9).

---

## 1. Per-sport gates (summary)

| Parameter | Value |
|---|---|
| Confirmatory sample size | N = 600 independently evaluable qualifying signals **per sport** |
| Interim look at N = 300 | **Descriptive only** — no significance-based decision, no stopping |
| Effect threshold | Observed mean CLV ≥ **+1.0 percentage point** |
| Uncertainty rule | Lower confidence bound > 0 (see §6 for the exact bound) |
| Significance level | One-sided **α = 0.0125 per attempt** (see §5 multiplicity) |
| Attempts | **Maximum two prospective attempts per sport** |
| Second attempt | Must be registered before new observations are collected; the first dataset may NOT be reused as fresh confirmatory evidence |
| Clustering | Game-clustered bootstrap (cluster = game/event) with documented dependence and precision diagnostics |
| Cross-sport pooling | **Forbidden** for pass/fail decisions. NFL success authorizes nothing for NBA or UFC |
| Eligibility | Frozen at registration; no post-hoc modification |

## 2. CLV estimand (exact definition)

PropWire distinguishes two quantities that must never be blended:

1. **Price CLV (primary estimand — the gate statistic).** For a qualifying
   signal taken at side `s` of a market:

   ```
   CLV_i = p_fair(entry, s) − p_fair(close, s)
   ```

   where `p_fair(x, s)` is the **de-vigged (no-vig) implied probability** of
   side `s` at observation `x` on the same market, same line family, converted
   to a common line basis when the line moves (see §4). Positive `CLV_i` means
   the entry beat the close on the same side: the signal captured value before
   the market converged. The gate statistic is the arithmetic mean of `CLV_i`
   over evaluable signals, expressed in percentage points.

2. **Model-vs-close probability difference (diagnostic only).** The model
   fair probability minus the de-vigged market probability. This measures
   model disagreement with the market and is reported descriptively. It is
   NOT the gate statistic, is never substituted for price CLV, and never
   contributes to a pass decision.

De-vig method (prespecified): two-way proportional (multiplicative) removal
on the quoted pair; for markets with more than two outcomes, normalized
over-the-top removal is used and must be recorded per quote. American odds
convert to implied probability `p = a/(a+100)` for positive `a` and
`p = |a|/(|a|+100)` for negative `a` before de-vigging.

## 3. Qualification and evaluability

A signal qualifies when ALL of the following hold at registration time:

1. The candidate was registered by the Phase 1.5 ledger BEFORE the closing
   reference timestamp, with model-version and source provenance attached.
2. The entry quote comes from an **approved book** (list below) with a
   captured timestamp and an integrity hash.
3. The market is one of the sport's registered markets at registration.

A registered signal is **evaluable** only if an independent closing reference
exists for the same market/line basis:

- **Closing-source independence (mandatory):** the closing reference is
  captured from a source separate from the model's input feed — a later
  observation from the same input feed is NOT verification.
- Missing, stale (beyond the per-sport staleness threshold), or mutually
  disagreeing closes (beyond the prespecified disagreement tolerance) make
  the signal **unevaluable**. Unevaluable signals are excluded from N with a
  reason code and reported in the qualification-rate report — they are never
  silently dropped and never counted as zeros.
- Pushes, voids, cancellations, DNP/non-participation: excluded from N with
  a reason code (they carry no CLV information; counting them as zero would
  bias the mean toward the null).

**Preregistered operating parameters (fill before first observation; blanks
make the gate inactive for that sport):**

| Field | NFL | NBA | UFC |
|---|---|---|---|
| Closing reference provider | _TBD_ | _TBD_ | _TBD_ |
| Approved entry books | _TBD_ | _TBD_ | _TBD_ |
| Capture timestamps (entry / close) | _TBD_ | _TBD_ | _TBD_ |
| Line-change normalization rule | _TBD_ | _TBD_ | _TBD_ |
| Close-staleness threshold | _TBD_ | _TBD_ | _TBD_ |
| Source-disagreement tolerance | _TBD_ | _TBD_ | _TBD_ |

## 4. Line-change normalization

When the closing line differs from the entry line, the comparison uses the
closing line's market on the SAME side the signal took, evaluated at the
signal's recorded entry odds translated to the closing line via the standard
half-point/point-scaling rule for the market type (spread/total: interpolate
at 0.25-line granularity with documented pushes-to-zero handling; player
props: recompute from the closing de-vig pair at the closing line; discontinuous
markets where the line basis cannot be reconstructed are unevaluable). The
chosen rule per market family is recorded in the registration row so every
signal's normalization is auditable.

## 5. Multiplicity across attempts

Two prospective attempts per sport create a second false-positive
opportunity. To hold the overall one-sided family-wise error at 2.5%
(two-sided 5%) across both attempts, each attempt is tested at
**one-sided α = 0.0125**, equivalent to requiring the lower bound of the
98.75% one-sided confidence interval (a two-sided 97.5% interval) to exceed
zero. This is deliberately more conservative than applying 95% intervals
twice. A prespecified alternative multiplicity procedure may replace this
allocation only if documented and committed before the first attempt's data
is examined.

## 6. Decision rule

A sport's attempt PASSES iff, on the confirmatory N = 600 evaluable
signals:

1. observed mean price CLV ≥ +1.0 percentage point, AND
2. the lower bound of the game-clustered bootstrap interval (one-sided
   98.75%, i.e. the 1.25th percentile of the resampled mean distribution)
   is strictly greater than 0.

Any other outcome (including "inconclusive") **consumes the attempt**. A
second attempt requires a new registration, new observations, and may not
reuse the first attempt's dataset. If both confirmatory evaluations fail,
the sport's commercial actionable-signal product is retired; historical and
research features continue without claiming demonstrated predictive
advantage.

## 7. Interval construction and sensitivity analysis

- **Primary:** deterministic game-clustered bootstrap. Cluster = game/event
  id; resample clusters with replacement, 10,000 replicates, fixed seed
  `20261024`, percentile method. Because all signals within a game share
  game-script and availability dependence, cluster-level resampling keeps
  the interval honest; the same fixture re-runs bit-identically.
- **Sensitivity (mandatory, reported alongside):** (a) calendar-week block
  bootstrap (broader time blocks); (b) leave-one-cluster-out influence
  summary. If the primary conclusion does not survive the week-block
  sensitivity, the attempt is recorded as **inconclusive** (and therefore
  consumed).
- **Precision diagnostics (reported at the descriptive N=300 checkpoint and
  at N=600):** number of distinct clusters represented, signals per cluster
  distribution, effective sample size under cluster dependence, interval
  width. These exist to measure time-to-evidence honestly — they must never
  be used to loosen eligibility to finish faster (v3 §3).

## 8. Phase 1.5 reporting obligations

The weekly pipeline reports, per sport: rolling qualification rate
(qualified / screened), reason-code histogram for rejections, evaluable
percentage, clusters represented, current bootstrap interval width, and
model-version coverage. Weeks-to-evidence arithmetic (v3 §3) is monitored,
not engineered.

## 9. Commercialization gate (fail-closed)

No actionable signal offering may launch for a sport without: (1) that
sport's gate PASS recorded in this repository with reproducible fixtures,
and (2) explicit compliance approval recorded alongside it. Feature
authorization checks both flags and defaults to DENY. Cross-sport
aggregation never substitutes for a sport's own gate.

## 10. Required fixtures (evaluation harness)

The Phase 1.5 harness must ship deterministic fixtures proving each rule:

1. Push, void, DNP, cancellation → excluded from N with reason codes.
2. Missing or stale closing prices → unevaluable, reported not dropped.
3. Duplicate and correlated signals → deduplicated; correlation preserved
   in clustering; effective-n reported.
4. Source disagreement beyond tolerance → unevaluable.
5. Post-registration mutation attempts → rejected; append-only revision
   history with integrity hashes survives.
6. Model-version changes mid-evaluation → signals stratified by version;
   mixed-version confirmatory sets are unevaluable as registered.
7. Failing statistical gate and passing statistical gate → exact verdict
   outputs.
8. Insufficient effective information (few clusters) → inconclusive verdict
   path.
9. Second-attempt failure → mandatory retirement of the sport's
   commercial flag (authorization check denies).

## 11. Reproducibility

Every evaluation run records: input snapshot hashes, seed (20261024),
replicate count, cluster assignment table, the exact interval bounds, and
the decision. Re-running the recorded snapshot must reproduce the recorded
decision bit-for-bit.

## 12. Time-to-evidence arithmetic under the registered hurdle
(Addendum 2026-10-25, committed BEFORE any prospective observation was
collected — permitted by the header rule. No registered parameter in §§1–11
is modified by this section.)

**What the hurdle is.** The qualification hurdle `EDGE_HURDLE = 0.10`
(`src/freeze_slate.py:40`) is **10 percentage points of de-vig implied
probability**: a signal qualifies only when the model's probability for a
side exceeds the market's de-vig probability for the same side by ≥ 0.10
(and EV > 0, and the quote carries a receipt). It is deliberately
conservative: a calibrated model against a liquid book rarely shows gaps
above 3–5pp; 10pp gaps are dominated by data errors and thin books. That is
the intended behavior for a fail-closed qualification gate — and it has a
calendar consequence that must be stated, not discovered later.

**Expected qualification rate.** Under the 10pp hurdle, the expected share
of screened props that qualify is low single digits at best. The table below
converts an assumed qualification rate X into weeks-to-N, holding two
assumptions explicit: 200 NFL props screened per week (single sport), and
100% evaluability of qualifying signals (§3 exclusions — pushes, stale
closes, source disagreement — only make these numbers worse, proportionally
to 1/evaluable-rate).

| Qualification rate X | Qualified / week | Weeks to N=300 (descriptive look) | Weeks to N=600 (confirmatory) |
|---|---|---|---|
| 0.5% | 1 | 300 | 600 |
| 1% | 2 | 150 | 300 |
| 2% | 4 | 75 | 150 |
| 5% | 10 | 30 | 60 |

**Read this table before making calendar claims.** At X = 1%, the
confirmatory N=600 gate is ~300 weeks (~5.8 seasons) for NFL alone; any
roadmap assumption of a Q1 2027 verdict is not supported by this arithmetic
unless the observed qualification rate is materially above the low single
digits. Gates are per-sport and cross-sport pooling is forbidden (§1), so
other sports do not shorten NFL's calendar.

**Preregistered review point.** At the descriptive N=300 checkpoint (or
after 10,000 screened signals, whichever comes first), the observed
qualification rate is reported per §8. If it is below 1%, a hurdle
recalibration MAY be proposed as a protocol amendment under the header rule:
committed with rationale before further data collection, never applied
retroactively, and never applied to already-collected signals. The first
confirmatory attempt consumes an attempt regardless (§6).

**Related constant, no coupling (verified 2026-10-25).**
`src/grade_clv.py` defines its own `edge_hurdle: float = 0.10` (line 95) and
`--hurdle` default 0.10 (line 248). `grep -n '0\.10' src/grade_clv.py
src/freeze_slate.py` shows they are two independent literals — grade_clv
imports nothing from freeze_slate, so there is no shared constant to drift.
They are, however, the same quantity in the same units (the snapshot
evaluator's de-vig probability gap; `grade_clv.py:139` re-qualifies on
`edge >= edge_hurdle`), i.e. a duplicated threshold that must be tuned
together by hand. Tuning one without the other is a protocol amendment and
must be committed as such. (The external auditor's reading of `--hurdle` as
"CLV in points" was incorrect: CLV is aggregated separately and is not
gated by this parameter.)
