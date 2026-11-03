"""nba_model configuration — every threshold is explicit and auditable.

These are v1 TUNING CONSTANTS, each documented with its rationale. They are
reviewed after the first 500 walk-forward predictions (see DECISIONS.md).
"""

from __future__ import annotations

# ── Identity ────────────────────────────────────────────────────────────────
MODEL_ID = "nba-points-v1"
MODEL_VERSION = "nba-points-v1.0.0"
MARKET = "points"          # v1 scope: game points only; rebounds/assists plug in later
BOARD_SIZE = 8             # "publish eight plays" — hard cap, never padded

# ── Freshness gates (fail-closed) ───────────────────────────────────────────
# Box scores are historical evidence; a slate is modeled on data through
# yesterday ET. 30h allows for late tip-offs (~10pm ET finishes) plus ingest
# latency, and NOTHING older.
BOXSCORE_MAX_AGE_HOURS = 30.0
# Pre-game quotes are perishable (v177 banner work set pre-game staleness at
# 15-30 min; publishing wants the tight end of that band).
ODDS_MAX_AGE_SECONDS = 600.0
# Availability reports move fast on slate day.
AVAILABILITY_MAX_AGE_HOURS = 6.0

# ── Calibration gate ────────────────────────────────────────────────────────
# Below this many scored predictions the model is UNCALIBRATED by
# construction and the board refuses to rank plays (mirrors the viewer's
# UNCALIBRATED badge semantics).
MIN_PREDICTIONS = 300
# Reliability slope band: fitted p over observed frequency on a logit scale.
# 1.0 = perfectly calibrated; <1 over-confident; >1 under-confident.
SLOPE_MIN = 0.80
SLOPE_MAX = 1.25
# Model Brier must not be WORSE than the naive season-mean baseline. Beating
# the market is REPORTED (walk-forward step 5) but never gated on — a model
# that loses to the closing market should be visible, not silenced.
BRIER_VS_NAIVE_MARGIN = 0.0
SMALL_SAMPLE_N = 30  # honesty flag threshold, same as the CLV ledger rule

# ── Play qualification ──────────────────────────────────────────────────────
# Calibration hurdle on the de-vigged consensus probability. The NFL stack
# uses 0.10 for receiving props; NBA points carry heavier variance per play,
# so v1 starts at 0.08 and revisits after 500 predictions.
EDGE_HURDLE = 0.08
# Independent-quote gate: an exact market+line must be quoted by at least
# this many DISTINCT books inside the freshness window.
MIN_INDEPENDENT_BOOKS = 2

# ── Minutes / form model ────────────────────────────────────────────────────
NBA_MINUTES_CAP = 48.0
MINUTES_FLOOR = 8.0        # projections below this are bench noise; refuse to publish
FORM_WINDOWS = (5, 10, 20)
RECENT_WEIGHT = 0.5        # blend weight on last-5 minutes vs season mean
GARBAGE_MARGIN = 25.0      # |margin| >= this trims the game from minutes form

# ── Context adjustments (multipliers, all clipped) ──────────────────────────
PACE_MULT_BOUNDS = (0.90, 1.12)
OPP_MULT_BOUNDS = (0.85, 1.15)
FORM_MULT_BOUNDS = (0.92, 1.08)
B2B_MINUTES_MULT = 0.97    # back-to-back rest adjustment

# ── Injury / rotation adjustments ───────────────────────────────────────────
TEAMMATE_OUT_MINUTES_BOOST = 0.04   # per higher-usage teammate Out, share-based
TEAMMATE_OUT_BOOST_CAP = 0.12
QUESTIONABLE_VAR_INFLATION = 1.15   # status uncertainty widens the distribution

# ── Distribution ────────────────────────────────────────────────────────────
SD_FLOOR_PTS = 4.0         # NBA points never have a tighter predictive sd
