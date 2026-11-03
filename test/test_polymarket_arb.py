"""
Verification Tests for the Polymarket Cross-Venue Mispricing Engine (`src/agents/polymarket_arb_agent.py`).

Tests:
1. Fee-adjustment math:
   - `Effective_Ask_YES = Ask_Price + (Ask_Price * (1 - Ask_Price) * Fee_Rate)`
   - `Effective_Bid_YES = Bid_Price - (Bid_Price * (1 - Bid_Price) * Fee_Rate)`
   - `Implied_Prob = Effective_Ask_YES`
2. Top-3 orderbook VWAP & Liquidity check:
   - A thin orderbook (< $100 liquidity across top 3 levels) does NOT trigger a SniperAlert,
     even if the edge is massive (+25%).
3. Player ID Mapping:
   - Verifies that `player_id_mapping` in `TruthStore` correctly links a Polymarket `token_id`
     to our internal canonical player and `prop_id`, and fails closed on unmapped tokens.
4. 5s PBP Recalc Trigger & Stale Orderbook Guard:
   - When `ProjectionRecalcAgent` fires a 5s PBP substitution update, `PolymarketArbAgent`
     immediately re-evaluates the cached Polymarket orderbook and emits a `SniperAlert`
     with `venue="Polymarket"` (`book="Polymarket"`, `venue_type="polymarket"`).
   - When the Polymarket WebSocket disconnects (`ws_connected=False`), the Arb Board is
     flagged `STALE` and alerts are suppressed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.agents.polymarket_arb_agent import (
    PolymarketArbAgent,
    compute_cross_venue_arb,
    compute_fee_adjusted_yes_prices,
    compute_top3_orderbook_vwap,
)
from src.agents.schemas import PropProjection


def test_fee_adjustment_math_exact_formula():
    """
    Verify exact fee-adjusted implied probability math:
      Effective_Ask_YES = Ask_Price + (Ask_Price * (1 - Ask_Price) * Fee_Rate)
      Effective_Bid_YES = Bid_Price - (Bid_Price * (1 - Bid_Price) * Fee_Rate)
      Implied_Prob = Effective_Ask_YES
    """
    ask_price = 0.58
    bid_price = 0.56
    fee_rate = 0.02

    res = compute_fee_adjusted_yes_prices(
        ask_price=ask_price,
        bid_price=bid_price,
        fee_rate=fee_rate,
    )

    expected_ask = 0.58 + (0.58 * (1.0 - 0.58) * 0.02)
    expected_bid = 0.56 - (0.56 * (1.0 - 0.56) * 0.02)

    assert res["effective_ask_yes"] == pytest.approx(expected_ask, abs=1e-6)
    assert res["effective_bid_yes"] == pytest.approx(expected_bid, abs=1e-6)
    assert res["implied_prob"] == pytest.approx(expected_ask, abs=1e-6)


def test_thin_orderbook_under_100_dollars_does_not_trigger_sniper_alert(tmp_path: Path):
    """
    Verify that a thin orderbook (< $100 across the top 3 levels) does NOT trigger
    a SniperAlert, even when the edge is massive (+25%).
    """
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    agent = PolymarketArbAgent(bus=bus, truth_store=truth)

    token_id = "0xpoly_thin_book_test"
    agent.register_token_mapping(
        token_id=token_id,
        polymarket_player_id="poly_nba_giannis_thin",
        canonical_player_id="nba_giannis",
        player_name="Giannis Antetokounmpo",
        team="MIL",
        position="PF",
        sport="nba",
        game_id="2026_nba_mil_bos",
        prop_id="nba_giannis_pts_thin",
        market="points",
        line=31.5,
        sportsbook_book="DraftKings",
        sportsbook_odds=-110,
        sportsbook_implied_prob=0.62,
        fair_prob=0.80,  # Massive +25% edge over $0.52 ask!
    )

    # Top 3 levels sum to $85.00 (< $100 threshold)
    thin_asks = [
        {"price": 0.52, "size_usd": 30.0},
        {"price": 0.53, "size_usd": 30.0},
        {"price": 0.54, "size_usd": 25.0},
        {"price": 0.55, "size_usd": 5000.0},  # 4th level ignored by top-3 VWAP
    ]
    thin_bids = [
        {"price": 0.50, "size_usd": 40.0},
        {"price": 0.49, "size_usd": 30.0},
        {"price": 0.48, "size_usd": 20.0},
    ]
    vwap_info = compute_top3_orderbook_vwap(thin_asks)
    assert vwap_info["total_liquidity_usd"] == pytest.approx(85.0, abs=1e-2)

    agent.cache_orderbook(token_id=token_id, asks=thin_asks, bids=thin_bids)
    card, alert = agent.evaluate_token_arb(
        token_id,
        fair_prob=0.80,
        sportsbook_implied_prob=0.62,
        user_gate=0.03,
    )

    assert card is not None
    assert card["liquidity_usd"] == pytest.approx(85.0, abs=1e-2)
    assert card["poly_edge"] > 0.20  # Edge is > 20%
    assert alert is None  # Strictly suppressed due to < $100 liquidity!

    suppressions = truth.get_recent_suppressions(limit=5)
    assert any("THIN_ORDERBOOK" in s["reason"] for s in suppressions)


def test_player_id_mapping_links_polymarket_token_to_internal_player(tmp_path: Path):
    """
    Verify that `player_id_mapping` in `TruthStore` links a Polymarket `token_id`
    to our internal `canonical_player_id` and `prop_id`, and fails closed for unknown tokens.
    """
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    agent = PolymarketArbAgent(bus=bus, truth_store=truth)

    token_id = "0xpoly_brunson_token_77"
    agent.register_token_mapping(
        token_id=token_id,
        polymarket_player_id="poly_slug_jalen_brunson",
        canonical_player_id="nba_jalen_brunson",
        player_name="Jalen Brunson",
        team="NYK",
        position="PG",
        sport="nba",
        game_id="nba_20261029_nyk_mia",
        prop_id="nba_jalen_brunson_pts",
        market="points",
        line=27.5,
    )

    resolved = agent.resolve_token_to_player(token_id)
    assert resolved is not None
    assert resolved["canonical_player_id"] == "nba_jalen_brunson"
    assert resolved["prop_id"] == "nba_jalen_brunson_pts"

    # Unregistered token must fail closed
    assert agent.resolve_token_to_player("0xunknown_token_999") is None


def test_5s_pbp_recalc_triggers_immediate_cached_polymarket_arb_and_stale_guard(tmp_path: Path):
    """
    Verify:
    1. When `ProjectionRecalcAgent` produces an updated `PropProjection` on a 5s PBP
       substitution, `on_projection_recalc_5s_update` immediately re-evaluates the
       cached Polymarket orderbook and emits a `SniperAlert` with `book="Polymarket"`
       and `venue_type="polymarket"` when `Poly_Edge > user_gate` and `Liquidity >= $100`.
    2. When the Polymarket WebSocket disconnects (`set_ws_connection_state(False)`),
       the Arb Board is flagged `is_stale=True` and no alert is emitted.
    """
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    agent = PolymarketArbAgent(bus=bus, truth_store=truth)

    now_dt = datetime.now(timezone.utc)
    proj = PropProjection(
        prop_id="nba_giannis_pts",
        sport="nba",
        game_id="2026_nba_mil_bos",
        player_id="nba_giannis",
        player_name="Giannis Antetokounmpo",
        team="MIL",
        opponent="BOS",
        position="PF",
        market="points",
        line=31.5,
        mu=34.8,
        sd=5.9,
        fair_line=34.5,
        fair_prob_over=0.66,
        fair_prob_under=0.34,
        ci_80_low=27.0,
        ci_80_high=42.0,
        confidence_score=0.86,
        minutes_projection=36.0,
        minutes_remaining=18.5,
        usage_rate=0.36,
        remaining_opportunities=14.0,
        catalyst_reason="substitution",
        catalyst_detail="Damian Lillard subbed out -> Giannis +4.8% usage",
        source_hash="a" * 64,
        fetched_at=now_dt,
        computed_at=now_dt,
    )

    results = agent.on_projection_recalc_5s_update(proj, user_gate=0.03, now=now_dt)
    assert len(results) == 1
    card, alert = results[0]
    assert card["is_stale"] is False
    assert card["liquidity_usd"] >= 100.0
    assert card["poly_edge"] > 0.03
    assert alert is not None
    assert alert.book == "Polymarket"
    assert alert.venue_type == "polymarket"
    assert alert.side == "YES"

    # Now simulate Polymarket WebSocket disconnect -> Stale Orderbook Guard
    agent.set_ws_connection_state(False, reason="Polymarket CLOB WebSocket dropped")
    stale_results = agent.on_projection_recalc_5s_update(proj, user_gate=0.03, now=now_dt)
    assert len(stale_results) == 1
    stale_card, stale_alert = stale_results[0]
    assert stale_card["is_stale"] is True
    assert stale_alert is None

