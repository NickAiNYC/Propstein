"""Pricing-cutoff status for one research reference.

Uses the existing week-level capture check and the per-game cutoff assertion.
A failure marks the reference UNVERIFIED_CONTEXT. It does not invent timestamps.
"""

from __future__ import annotations

from datetime import datetime

VERIFIED_CONTEXT = "VERIFIED_CONTEXT"
UNVERIFIED_CONTEXT = "UNVERIFIED_CONTEXT"


def reference_context_status(game_id: str, pricing_cutoff: datetime) -> str:
    try:
        from scripts.autopilot import game_context_has_capture_times
        from src.features import assert_context_known_at_cutoff, load_games
        import pandas as pd

        if not game_context_has_capture_times():
            return UNVERIFIED_CONTEXT
        games = load_games()
        frame = pd.DataFrame([{
            "game_id": game_id,
            "pricing_cutoff_timestamp": pricing_cutoff.isoformat(),
        }])
        assert_context_known_at_cutoff(frame, games)
    except Exception:
        return UNVERIFIED_CONTEXT
    return VERIFIED_CONTEXT
