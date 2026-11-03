"""
Strict Pydantic v2 schemas and TypedDict definitions for PropWire's
Live Agentic Sniper Terminal (NFL + NBA + Polymarket).

ARCHITECTURAL LAW:
- No LLM in the decision path.
- Every external payload and agent output carries `source_hash` (SHA-256)
  and `fetched_at` (UTC datetime) plus `feed_age_seconds`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypedDict, Union

from pydantic import BaseModel, ConfigDict, Field


MODEL_VERSION = "2026.10.29-nb-gamma-v2"


def compute_source_hash(payload: dict[str, Any] | list[Any] | str | bytes) -> str:
    """Compute canonical SHA-256 digest of any raw external payload."""
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_dedup_hash(*parts: str) -> str:
    """Compute deterministic SHA-256 dedup key for normalized tuples."""
    normalized = "|".join(str(p or "").strip().lower() for p in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class StaleThresholds(BaseModel):
    """Stale Kill Switch maximum age thresholds in seconds."""
    model_config = ConfigDict(frozen=True)

    injury_live_seconds: float = 90.0
    injury_pregame_seconds: float = 300.0
    lineup_live_seconds: float = 45.0
    lineup_pregame_seconds: float = 300.0
    odds_live_seconds: float = 20.0
    odds_pregame_seconds: float = 60.0


class SniperGateConfig(BaseModel):
    """User-configurable 5-gate thresholds for SniperAgent."""
    sport: Literal["nfl", "nba"] = "nfl"
    is_week_1: bool = False
    is_live: bool = False
    min_edge_pct: float = Field(default=3.0, description="3.0% normal, 10.0% NFL Week 1")
    min_confidence_score: float = Field(default=0.60, ge=0.0, le=1.0)
    max_feed_age_seconds: float = Field(default=60.0, gt=0.0)
    min_liquidity_score: float = Field(default=0.25, ge=0.0, le=1.0)
    min_clv_expectation: float = Field(default=0.005, ge=-1.0, le=1.0)
    kelly_cap: float = Field(default=0.015, gt=0.0, le=0.05)

    def effective_edge_gate_pct(self) -> float:
        """Preserve the existing Week-1 10% gate logic when is_week_1 is True."""
        if self.is_week_1 and self.sport == "nfl":
            return max(self.min_edge_pct, 10.0)
        return self.min_edge_pct

    def effective_feed_age_limit(self, feed_type: Literal["injury", "lineup", "odds"] = "odds") -> float:
        thresholds = StaleThresholds()
        if feed_type == "injury":
            limit = thresholds.injury_live_seconds if self.is_live else thresholds.injury_pregame_seconds
        elif feed_type == "lineup":
            limit = thresholds.lineup_live_seconds if self.is_live else thresholds.lineup_pregame_seconds
        else:
            limit = thresholds.odds_live_seconds if self.is_live else thresholds.odds_pregame_seconds
        return min(self.max_feed_age_seconds, limit) if self.is_live else limit


class InjuryBeneficiary(BaseModel):
    player_id: str
    player_name: str
    team: str
    position: str = "WR"
    added_minutes: float = 0.0
    added_targets: float = 0.0
    added_usage_rate: float = 0.0
    absorption_share: float = 0.0


class InjuryEventPayload(BaseModel):
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    status: Literal["OUT", "DOUBTFUL", "QUESTIONABLE", "ACTIVE", "SCRATCHED", "STARTING"]
    body_part: str = "undisclosed"
    source_provider: Literal["official_report", "sportfeeds_webhook", "xflux_beat_writer"] = "official_report"
    vacated_minutes: float = 0.0
    vacated_targets: float = 0.0
    vacated_usage: float = 0.0
    beneficiaries: list[InjuryBeneficiary] = Field(default_factory=list)
    is_live: bool = False
    notes: str = ""
    source_hash: str
    fetched_at: datetime


class LineupEventPayload(BaseModel):
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    sub_type: Literal["substitution", "foul_trouble", "confirmed_starter", "bench_rotation"]
    is_substitution: bool = False
    is_foul: bool = False
    personal_fouls: int = 0
    period: int = 1
    clock_remaining_minutes: float = 48.0
    minutes_projection_delta: float = 0.0
    usage_rate_delta: float = 0.0
    remaining_opportunities_delta: float = 0.0
    beneficiaries: list[InjuryBeneficiary] = Field(default_factory=list)
    is_live: bool = True
    source_hash: str
    fetched_at: datetime


class MarketMovePayload(BaseModel):
    prop_id: str
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str = ""
    market: str
    venue_type: Literal["sportsbook", "polymarket"] = "sportsbook"
    book: str
    line: float
    over_odds: int = -110
    under_odds: int = -110
    implied_prob_over: float
    implied_prob_under: float
    liquidity_score: float = Field(default=0.85, ge=0.0, le=1.0)
    orderbook_spread_cents: float = 2.0
    orderbook_depth_usd: float = 5000.0
    token_id: Optional[str] = None
    deep_link: str = "https://propstein.com"
    is_live: bool = False
    source_hash: str
    fetched_at: datetime


class PropProjection(BaseModel):
    prop_id: str
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    position: str = "WR"
    market: str
    line: float
    mu: float
    sd: float
    alpha: Optional[float] = None
    k: Optional[float] = None
    mu_rec: Optional[float] = None
    mu_ypr: Optional[float] = None
    fair_line: float
    fair_prob_over: float
    fair_prob_under: float
    ci_80_low: float = 0.0
    ci_80_high: float = 0.0
    confidence_score: float = 0.75
    minutes_projection: float = 32.0
    minutes_remaining: float = 32.0
    usage_rate: float = 0.24
    remaining_opportunities: float = 8.0
    catalyst_reason: Literal[
        "baseline",
        "injury_vacancy",
        "usage_surge",
        "foul_trouble",
        "substitution",
        "live_pace",
    ] = "baseline"
    catalyst_detail: str = ""
    model_version: str = MODEL_VERSION
    source_hash: str
    fetched_at: datetime
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    feed_age_seconds: float = 0.0
    is_stale: bool = False


class SniperAlert(BaseModel):
    alert_id: str
    prop_id: str
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str = ""
    market: str
    side: Literal["OVER", "UNDER", "YES", "NO"]
    venue_type: Literal["sportsbook", "polymarket"] = "sportsbook"
    book: str
    line: float
    odds_american: int
    fair_line: float
    fair_prob: float
    implied_prob: float
    edge_pct: float
    mispricing_bps: float
    ev_per_unit: float
    kelly_stake: float
    confidence_score: float
    liquidity_score: float
    clv_expectation: float
    feed_age_seconds: float
    is_stale: bool = False
    deep_link: str
    catalyst_reason: str = "baseline"
    reasoning_chain: str = ""
    source_hash: str
    model_version: str = MODEL_VERSION
    urgency_score: float = 0.0
    edge_tier: str = "BASE"
    is_decaying: bool = False
    minutes_until_kickoff: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PolymarketPropOpportunity(BaseModel):
    prop_id: str
    token_id: str
    condition_id: str
    sport: Literal["nfl", "nba"]
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    market: str
    line: float
    suggested_side: Literal["YES", "NO"]
    yes_price: float = Field(ge=0.01, le=0.99)
    no_price: float = Field(ge=0.01, le=0.99)
    spread_cents: float
    liquidity_usd: float
    liquidity_score: float = Field(ge=0.0, le=1.0)
    fair_prob: float
    implied_prob: float
    edge_pct: float
    mispricing_bps: float
    ranking_score: float  # mispricing_bps * liquidity_score
    kelly_stake: float
    feed_age_seconds: float
    is_stale: bool = False
    deep_link: str
    catalyst_reason: str = "baseline"
    source_hash: str
    fetched_at: datetime


class StructuredAgentLog(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent: str
    event_type: str
    prop_id: str
    latency_ms: float
    decision: Literal["FIRED", "SUPPRESSED", "RECALCULATED", "INGESTED", "DEDUP_SKIPPED", "HALTED_STALE"]
    reason: str
    source_hash: str
    feed_age_seconds: float
    is_stale: bool = False


class AgentState(TypedDict):
    event_type: Literal["injury", "lineup", "substitution", "foul", "market_move", "game_clock"]
    event_payload: dict[str, Any]
    affected_player_ids: list[str]
    affected_game_id: str
    source_hash: str
    fetched_at: datetime
    is_stale: bool
    projections: dict[str, PropProjection]  # keyed by prop_id
    alerts: list[SniperAlert]
