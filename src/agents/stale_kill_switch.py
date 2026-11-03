"""
The Stale Kill Switch — Non-Negotiable Safety Invariant.

Every projection and market quote carries `feed_age_seconds`.
If `feed_age_seconds > threshold`:
  - Injury feed: 90s live / 300s pregame
  - Lineup feed: 45s live / 300s pregame
  - Odds / Market feed: 20s live / 60s pregame
we set `is_stale = True`, suppress `SniperAgent` firing, and emit a structured
suppression log. Never silently fire on stale data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from src.agents.schemas import StaleThresholds, StructuredAgentLog

logger = logging.getLogger("propwire.stale_kill_switch")


class StaleKillSwitch:
    """Enforces feed freshness invariants across all PropWire agents."""

    def __init__(self, thresholds: StaleThresholds | None = None):
        self.thresholds = thresholds or StaleThresholds()
        self.suppression_log: list[StructuredAgentLog] = []

    @staticmethod
    def compute_feed_age(fetched_at: datetime, now: datetime | None = None) -> float:
        now_utc = now or datetime.now(timezone.utc)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        return max(0.0, round((now_utc - fetched_at).total_seconds(), 3))

    @staticmethod
    def get_expected_cadence_seconds(sport: str, is_live: bool = False, in_game: bool = False) -> float:
        """
        Cadence varies by sport and game status:
        - NBA live: 5s
        - NFL during game / live: 30s
        - Off-hours / pregame: 15 min (900s)
        """
        s = (sport or "").strip().lower()
        if s == "nba" and is_live:
            return 5.0
        if s == "nfl" and (is_live or in_game):
            return 30.0
        return 900.0  # 15 minutes for pregame / off-hours

    def evaluate_cadence_freshness(
        self,
        *,
        last_update: datetime,
        last_expected_update: datetime | None = None,
        sport: str = "nfl",
        is_live: bool = False,
        in_game: bool = False,
        now: datetime | None = None,
    ) -> tuple[bool, float, float, str]:
        """
        Compare last_update vs last_expected_update.
        If stale > 2x expected cadence, trigger 'ODDS STALE' state and suppress alerts.
        Returns: (is_stale, elapsed_seconds, max_allowed_seconds, state_label)
        """
        now_utc = now or datetime.now(timezone.utc)
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        cadence = self.get_expected_cadence_seconds(sport=sport, is_live=is_live, in_game=in_game)
        max_allowed = 2.0 * cadence
        elapsed = max(0.0, (now_utc - last_update).total_seconds())

        is_stale = elapsed > max_allowed
        state_label = "ODDS STALE" if is_stale else "LIVE FRESH"
        return is_stale, elapsed, max_allowed, state_label

    def threshold_for(
        self,
        feed_type: Literal["injury", "lineup", "odds"],
        is_live: bool = False,
        user_max_age: float | None = None,
    ) -> float:
        if feed_type == "injury":
            limit = self.thresholds.injury_live_seconds if is_live else self.thresholds.injury_pregame_seconds
        elif feed_type == "lineup":
            limit = self.thresholds.lineup_live_seconds if is_live else self.thresholds.lineup_pregame_seconds
        else:
            limit = self.thresholds.odds_live_seconds if is_live else self.thresholds.odds_pregame_seconds

        if user_max_age is not None and user_max_age > 0:
            return min(limit, user_max_age)
        return limit

    def check_freshness(
        self,
        *,
        fetched_at: datetime,
        feed_type: Literal["injury", "lineup", "odds"] = "odds",
        is_live: bool = False,
        user_max_age: float | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, float, float]:
        """Lightweight freshness check returning `(is_stale, feed_age_seconds, limit_seconds)`."""
        age = self.compute_feed_age(fetched_at, now=now)
        limit = self.threshold_for(feed_type, is_live=is_live, user_max_age=user_max_age)
        return (age > limit), age, limit

    def evaluate(
        self,
        *,
        agent_name: str,
        event_type: str,
        prop_id: str,
        feed_type: Literal["injury", "lineup", "odds"],
        fetched_at: datetime,
        source_hash: str,
        is_live: bool = False,
        user_max_age: float | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, float, float, str]:
        """
        Returns (is_stale, feed_age_seconds, threshold_seconds, reason).
        Logs every stale suppression explicitly.
        """
        age = self.compute_feed_age(fetched_at, now=now)
        limit = self.threshold_for(feed_type, is_live=is_live, user_max_age=user_max_age)
        is_stale = age > limit
        mode = "live" if is_live else "pregame"
        if is_stale:
            reason = (
                f"STALE_KILL_SWITCH_TRIPPED: {feed_type} feed age {age:.1f}s exceeds "
                f"{mode} threshold {limit:.1f}s (source_hash={source_hash[:12]})"
            )
            log_entry = StructuredAgentLog(
                agent=agent_name,
                event_type=event_type,
                prop_id=prop_id,
                latency_ms=0.0,
                decision="HALTED_STALE",
                reason=reason,
                source_hash=source_hash,
                feed_age_seconds=age,
                is_stale=True,
            )
            self.suppression_log.append(log_entry)
            logger.warning(log_entry.model_dump_json())
        else:
            reason = f"FRESH ({feed_type} {mode}: {age:.1f}s <= {limit:.1f}s)"
        return is_stale, age, limit, reason
