"""PropStein pipeline — configuration.

Every tunable lives here. Determinism: the master seed is fixed
(20261024, the preregistered bootstrap seed); PYTHONHASHSEED is pinned
by the CLI entrypoint before any hashing runs.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- identity ---------------------------------------------------------------

PIPELINE_VERSION = "1.0.0"
PIPELINE_ID = "propstein-pipeline"

# Preregistered master seed (also the game-cluster bootstrap seed in the charter).
MASTER_SEED = 20261024

# Determinism note: canonical JSON sorts all keys and the pipeline never
# iterates sets, so PYTHONHASHSEED does not affect any stored number. The
# entrypoint still recommends PYTHONHASHSEED=0 for belt-and-braces parity.

# --- paths ------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PROPSTEIN_DATA_DIR", str(REPO_ROOT / "data")))
RUNS_DIR = DATA_DIR / "runs"
LATEST_PATH = DATA_DIR / "latest_predictions.json"
INDEX_PATH = DATA_DIR / "runs_index.json"


def ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- providers --------------------------------------------------------------

SYNTHETIC_ODDS_PROVIDER_ID = "PIPE-SYNTH-ODDS-1 (simulated)"
SYNTHETIC_STATS_PROVIDER_ID = "PIPE-SYNTH-STATS-1 (simulated)"
SYNTHETIC_SETTLE_PROVIDER_ID = "PIPE-SYNTH-SETTLE-1 (simulated)"

# Licensed feeds activate automatically when both URL and key are present.
LICENSED_ODDS_URL = os.environ.get("PROPSTEIN_FEED_ODDS_URL", "")
LICENSED_ODDS_KEY = os.environ.get("PROPSTEIN_FEED_ODDS_KEY", "")
LICENSED_STATS_URL = os.environ.get("PROPSTEIN_FEED_STATS_URL", "")
LICENSED_STATS_KEY = os.environ.get("PROPSTEIN_FEED_STATS_KEY", "")


def licensed_configured() -> bool:
    return bool(LICENSED_ODDS_URL and LICENSED_ODDS_KEY and LICENSED_STATS_URL and LICENSED_STATS_KEY)


# --- board shape ------------------------------------------------------------

# Board horizon: events commencing within this many days of the run date.
BOARD_HORIZON_DAYS = 3
# Series length embedded per prediction for sparklines.
SERIES_WINDOW = 7
# Scoring window: how many past runs feed self-scoring history.
SCORING_WINDOW_RUNS = 14

# --- sanity thresholds (Phase 4 gate) ----------------------------------------

MIN_PREDICTIONS = 40
MIN_EVENTS = 12
MAX_BOARD_AGE_HOURS = 48.0

# --- freshness (parity with src/lib/domain/freshness.ts) --------------------

MARKET_COMPARISON_SECONDS = 300
CLOSING_WINDOW_SECONDS = 900
CLOSING_SOURCE_TOLERANCE_PP = 1.5

# --- HTTP fetcher ------------------------------------------------------------

FETCH_TIMEOUT_SECONDS = 10.0
FETCH_MAX_RETRIES = 5
FETCH_BASE_DELAY_SECONDS = 0.5
FETCH_MAX_DELAY_SECONDS = 30.0
FETCH_RATE_PER_SECOND = 2.0

# --- exit codes --------------------------------------------------------------

EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_CONFLICT = 3
EXIT_FEED = 4
