"""
PropStein Live Agentic Sniper Terminal (NFL + NBA + Polymarket).

Exports the 6-agent topology, deterministic `price_prop` function,
`StaleKillSwitch`, `DurableRedisStreamBus`, `TruthStore`, and
`SniperTerminalEngine` (LangGraph `StateGraph(AgentState)`).
"""

from src.agents.graph import SniperTerminalEngine
from src.agents.injury_agent import InjuryEventAgent
from src.agents.lineup_agent import LineupAndSubstitutionAgent
from src.agents.market_agent import MarketIngestAgent
from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.agents.polymarket_agent import PolymarketSpecialistAgent, compute_clob_liquidity_score
from src.agents.polymarket_arb_agent import (
    PolymarketArbAgent,
    compute_cross_venue_arb,
    compute_fee_adjusted_yes_prices,
    compute_top3_orderbook_vwap,
)
from src.agents.recalc_agent import ProjectionRecalcAgent, price_prop
from src.agents.schemas import (
    MODEL_VERSION,
    AgentState,
    InjuryBeneficiary,
    InjuryEventPayload,
    LineupEventPayload,
    MarketMovePayload,
    PolymarketPropOpportunity,
    PropProjection,
    SniperAlert,
    SniperGateConfig,
    StaleThresholds,
    StructuredAgentLog,
    compute_dedup_hash,
    compute_source_hash,
)
from src.agents.sniper_agent import SniperAgent, narrate_locked_alert
from src.agents.stale_kill_switch import StaleKillSwitch

__all__ = [
    "MODEL_VERSION",
    "AgentState",
    "DurableRedisStreamBus",
    "InjuryBeneficiary",
    "InjuryEventAgent",
    "InjuryEventPayload",
    "LineupAndSubstitutionAgent",
    "LineupEventPayload",
    "MarketIngestAgent",
    "MarketMovePayload",
    "PolymarketPropOpportunity",
    "PolymarketSpecialistAgent",
    "ProjectionRecalcAgent",
    "PropProjection",
    "SniperAgent",
    "SniperAlert",
    "SniperGateConfig",
    "SniperTerminalEngine",
    "StaleKillSwitch",
    "StaleThresholds",
    "StructuredAgentLog",
    "TruthStore",
    "compute_clob_liquidity_score",
    "compute_dedup_hash",
    "compute_source_hash",
    "narrate_locked_alert",
    "price_prop",
]
