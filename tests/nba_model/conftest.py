"""Shared fixtures for nba_model tests. All data is synthetic; no network."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SEASON_START = "2026-10-19"
SEASON_DAYS = 24


@pytest.fixture(scope="session")
def synthetic_world():
    """A deterministic mini-season: dataset + odds + injuries."""
    from nba_model.data.dataset import build_dataset
    from nba_model.data.providers import SyntheticSeasonProvider

    provider = SyntheticSeasonProvider(start_date=SEASON_START, n_days=SEASON_DAYS, seed=7)
    world = provider.fetch_range(None)
    df, meta = build_dataset(world["rows"], world["games"])
    return {
        "df": df,
        "meta": meta,
        "odds": world["odds"],
        "injuries": world["injuries"],
        "start": SEASON_START,
        "end": (pd.Timestamp(SEASON_START) + pd.Timedelta(days=SEASON_DAYS - 1)).strftime("%Y-%m-%d"),
    }


@pytest.fixture(scope="session")
def small_frame():
    """Hand-built player-game frame for feature unit tests (no provider)."""
    rows = []
    for i in range(10):
        minutes = 12.0 if i == 9 else 30.0        # last game is a blowout trim
        margin = 30.0 if i == 9 else 5.0
        ppm = 0.5 + 0.03 * i
        rows.append({
            "player_id": "P1", "game_id": f"g{i}",
            "game_date": f"2026-01-{i + 1:02d}",
            "team": "AAA", "opponent": "BBB", "position": "G1",
            "minutes": minutes, "pts": round(minutes * ppm, 1),
            "ppm": ppm, "margin": margin, "poss": 100.0, "dnp": False,
        })
    # a DNP row for another player
    rows.append({
        "player_id": "P2", "game_id": "g0", "game_date": "2026-01-01",
        "team": "BBB", "opponent": "AAA", "position": "W1",
        "minutes": 0.0, "pts": 0.0, "ppm": None, "margin": 3.0,
        "poss": 100.0, "dnp": True,
    })
    return pd.DataFrame(rows)
