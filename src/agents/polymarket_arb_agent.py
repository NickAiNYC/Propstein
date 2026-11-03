"""
Polymarket CLOB Cross-Venue Mispricing & Arbitrage Agent (`src/agents/polymarket_arb_agent.py`).

Compares PropWire's calibrated Bayesian Fair Probability against both:
1. The best available Sportsbook line (DraftKings / FanDuel / Pinnacle), and
2. The live Polymarket CLOB orderbook (top-3 levels VWAP, adjusted for taker fees).

ARCHITECTURAL GUARANTEES:
- Fee-Adjusted Implied Probability:
    Effective_Ask_YES = Ask_Price + (Ask_Price * (1 - Ask_Price) * Fee_Rate)
    Effective_Bid_YES = Bid_Price - (Bid_Price * (1 - Bid_Price) * Fee_Rate)
    Implied_Prob = Effective_Ask_YES
- Top-3 Orderbook Levels VWAP & Liquidity Gate:
    Calculates Volume-Weighted Average Price (VWAP) across the top 3 levels of
    the CLOB orderbook. If total top-3 liquidity < $100, suppresses SniperAlert
    even if the edge is massive.
- Decoupled 5s PBP Trigger:
    When `ProjectionRecalcAgent` fires a 5s PBP substitution update, immediately
    re-evaluates the cached Polymarket orderbook without waiting for the 30s poll.
- Stale Orderbook Guard:
    If the Polymarket WebSocket disconnects (`ws_connected=False`) or orderbook age
    exceeds the live freshness limit, flags the Arb Board as `STALE` and suppresses alerts.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.agents.persistence import (
    STREAM_MARKET,
    STREAM_SNIPER,
    DurableRedisStreamBus,
    TruthStore,
)
from src.agents.polymarket_agent import prob_to_american_odds
from src.agents.schemas import (
    MODEL_VERSION,
    PropProjection,
    SniperAlert,
    StructuredAgentLog,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch
from src.model import devig_two_way, ev_per_unit, kelly_fraction
from src.services.webhook_dispatcher import WebhookDispatcher

logger = logging.getLogger("propwire.agent.polymarket_arb")

DEFAULT_POLYMARKET_FEE_RATE = 0.02  # 2.0% fee rate on net winning shares
MIN_TOP3_LIQUIDITY_USD = 100.0      # Hard $100 minimum liquidity across top 3 levels


def compute_fee_adjusted_yes_prices(
    ask_price: float,
    bid_price: float,
    fee_rate: float = DEFAULT_POLYMARKET_FEE_RATE,
) -> dict[str, float]:
    """
    Calculate fee-adjusted Polymarket CLOB execution prices for YES shares:
      - Effective_Ask_YES = Ask_Price + (Ask_Price * (1 - Ask_Price) * Fee_Rate)
      - Effective_Bid_YES = Bid_Price - (Bid_Price * (1 - Bid_Price) * Fee_Rate)
      - Implied_Prob = Effective_Ask_YES
    """
    ask = max(0.001, min(0.999, float(ask_price)))
    bid = max(0.001, min(0.999, float(bid_price)))
    rate = max(0.0, float(fee_rate))

    effective_ask_yes = ask + (ask * (1.0 - ask) * rate)
    effective_bid_yes = bid - (bid * (1.0 - bid) * rate)
    return {
        "ask_price": round(ask, 6),
        "bid_price": round(bid, 6),
        "fee_rate": round(rate, 6),
        "effective_ask_yes": round(effective_ask_yes, 6),
        "effective_bid_yes": round(effective_bid_yes, 6),
        "implied_prob": round(effective_ask_yes, 6),
    }


def compute_top3_orderbook_vwap(levels: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute Volume-Weighted Average Price (VWAP) and total USD liquidity across
    the top 3 levels of a Polymarket CLOB orderbook side.

    Each level dict may provide:
      - `price` (float in (0, 1))
      - `size_usd` or `usd` or `size` (USD notional at that level)
      - or `shares` (converted via `shares * price` if `size_usd` is absent)
    """
    top_levels = list(levels or [])[:3]
    if not top_levels:
        return {
            "vwap_price": 0.0,
            "total_liquidity_usd": 0.0,
            "top_price": 0.0,
            "levels_summary": [],
            "depth_tooltip": "No orderbook depth available",
        }

    weighted_sum = 0.0
    total_usd = 0.0
    normalized_levels: list[dict[str, float]] = []
    tooltip_parts: list[str] = []

    for lvl in top_levels:
        price = float(lvl.get("price", 0.0))
        if price <= 0.0:
            continue
        if "size_usd" in lvl and lvl["size_usd"] is not None:
            usd = float(lvl["size_usd"])
        elif "usd" in lvl and lvl["usd"] is not None:
            usd = float(lvl["usd"])
        elif "shares" in lvl and lvl["shares"] is not None:
            usd = float(lvl["shares"]) * price
        else:
            usd = float(lvl.get("size", 0.0))

        if usd <= 0.0:
            continue

        weighted_sum += price * usd
        total_usd += usd
        normalized_levels.append({"price": round(price, 4), "size_usd": round(usd, 2)})
        tooltip_parts.append(f"${usd:,.0f} available at ${price:.2f}")

    if total_usd <= 0.0:
        return {
            "vwap_price": 0.0,
            "total_liquidity_usd": 0.0,
            "top_price": 0.0,
            "levels_summary": [],
            "depth_tooltip": "No orderbook depth available",
        }

    vwap = weighted_sum / total_usd
    return {
        "vwap_price": round(vwap, 6),
        "total_liquidity_usd": round(total_usd, 2),
        "top_price": normalized_levels[0]["price"],
        "levels_summary": normalized_levels,
        "depth_tooltip": ", ".join(tooltip_parts),
    }


def compute_cross_venue_arb(
    *,
    fair_prob: float,
    implied_prob: float,
    sportsbook_implied_prob: float,
) -> dict[str, float]:
    """
    Compute cross-venue edge and spread metrics:
      - Poly_Edge = Fair_Prob - Implied_Prob
      - Sportsbook_Edge = Fair_Prob - Sportsbook_Implied_Prob
      - Cross_Venue_Spread = Sportsbook_Implied_Prob - Implied_Prob
    """
    poly_edge = float(fair_prob) - float(implied_prob)
    sb_edge = float(fair_prob) - float(sportsbook_implied_prob)
    spread = float(sportsbook_implied_prob) - float(implied_prob)
    return {
        "poly_edge": round(poly_edge, 6),
        "poly_edge_pct": round(poly_edge * 100.0, 2),
        "sportsbook_edge": round(sb_edge, 6),
        "sportsbook_edge_pct": round(sb_edge * 100.0, 2),
        "cross_venue_spread": round(spread, 6),
        "cross_venue_spread_pct": round(spread * 100.0, 2),
    }


DEFAULT_ARB_TOKEN_CATALOG: dict[str, dict[str, Any]] = {
    "0xpoly_giannis_pts_31_5": {
        "token_id": "0xpoly_giannis_pts_31_5",
        "polymarket_player_id": "poly_nba_giannis",
        "canonical_player_id": "nba_giannis",
        "player_name": "Giannis Antetokounmpo",
        "team": "MIL",
        "opponent": "BOS",
        "position": "PF",
        "sport": "nba",
        "game_id": "2026_nba_mil_bos",
        "prop_id": "nba_giannis_pts",
        "market": "points",
        "market_label": "PTS Over 31.5",
        "line": 31.5,
        "fair_prob": 0.64,
        "sportsbook_book": "DraftKings",
        "sportsbook_odds": -110,
        "sportsbook_implied_prob": 0.62,
        "asks": [
            {"price": 0.58, "size_usd": 500.0},
            {"price": 0.59, "size_usd": 1200.0},
            {"price": 0.60, "size_usd": 850.0},
        ],
        "bids": [
            {"price": 0.56, "size_usd": 650.0},
            {"price": 0.55, "size_usd": 900.0},
            {"price": 0.54, "size_usd": 1100.0},
        ],
        "deep_link": "https://polymarket.com/event/nba-giannis-antetokounmpo-points-over-31-5",
        "sportsbook_deep_link": "https://sportsbook.draftkings.com/leagues/basketball/nba",
    },
    "0x91a4f8b20c71e84d3a109c77f62b10e489a31c01": {
        "token_id": "0x91a4f8b20c71e84d3a109c77f62b10e489a31c01",
        "polymarket_player_id": "poly_nba_tyrese_maxey",
        "canonical_player_id": "nba_tyrese_maxey",
        "player_name": "Tyrese Maxey",
        "team": "PHI",
        "opponent": "DET",
        "position": "PG",
        "sport": "nba",
        "game_id": "nba_20261029_det_phi",
        "prop_id": "nba_tyrese_maxey_pts",
        "market": "points",
        "market_label": "PTS Over 26.5",
        "line": 26.5,
        "fair_prob": 0.63,
        "sportsbook_book": "DraftKings",
        "sportsbook_odds": -115,
        "sportsbook_implied_prob": 0.60,
        "asks": [
            {"price": 0.55, "size_usd": 620.0},
            {"price": 0.56, "size_usd": 1400.0},
            {"price": 0.57, "size_usd": 980.0},
        ],
        "bids": [
            {"price": 0.53, "size_usd": 700.0},
            {"price": 0.52, "size_usd": 1100.0},
            {"price": 0.51, "size_usd": 900.0},
        ],
        "deep_link": "https://polymarket.com/event/nba-tyrese-maxey-points-over-26-5",
        "sportsbook_deep_link": "https://sportsbook.draftkings.com/leagues/basketball/nba?prop=tyrese-maxey-pts",
    },
    "0xpoly_tatum_pts_28_5": {
        "token_id": "0xpoly_tatum_pts_28_5",
        "polymarket_player_id": "poly_nba_tatum",
        "canonical_player_id": "nba_tatum",
        "player_name": "Jayson Tatum",
        "team": "BOS",
        "opponent": "MIL",
        "position": "SF",
        "sport": "nba",
        "game_id": "2026_nba_mil_bos",
        "prop_id": "nba_tatum_pts",
        "market": "points",
        "market_label": "PTS Over 28.5",
        "line": 28.5,
        "fair_prob": 0.61,
        "sportsbook_book": "FanDuel",
        "sportsbook_odds": -108,
        "sportsbook_implied_prob": 0.54,
        "asks": [
            {"price": 0.59, "size_usd": 450.0},
            {"price": 0.60, "size_usd": 950.0},
            {"price": 0.61, "size_usd": 1100.0},
        ],
        "bids": [
            {"price": 0.57, "size_usd": 500.0},
            {"price": 0.56, "size_usd": 800.0},
            {"price": 0.55, "size_usd": 1000.0},
        ],
        "deep_link": "https://polymarket.com/event/nba-jayson-tatum-points-over-28-5",
        "sportsbook_deep_link": "https://sportsbook.fanduel.com/navigation/nba",
    },
    "0x53d8a7129f04e63b11208a49c73e19d802a74b22": {
        "token_id": "0x53d8a7129f04e63b11208a49c73e19d802a74b22",
        "polymarket_player_id": "poly_nba_jalen_brunson",
        "canonical_player_id": "nba_jalen_brunson",
        "player_name": "Jalen Brunson",
        "team": "NYK",
        "opponent": "MIA",
        "position": "PG",
        "sport": "nba",
        "game_id": "nba_20261029_nyk_mia",
        "prop_id": "nba_jalen_brunson_pts",
        "market": "points",
        "market_label": "PTS Over 27.5",
        "line": 27.5,
        "fair_prob": 0.62,
        "sportsbook_book": "FanDuel",
        "sportsbook_odds": -112,
        "sportsbook_implied_prob": 0.59,
        "asks": [
            {"price": 0.54, "size_usd": 780.0},
            {"price": 0.55, "size_usd": 1350.0},
            {"price": 0.56, "size_usd": 920.0},
        ],
        "bids": [
            {"price": 0.52, "size_usd": 640.0},
            {"price": 0.51, "size_usd": 980.0},
            {"price": 0.50, "size_usd": 1150.0},
        ],
        "deep_link": "https://polymarket.com/event/nba-jalen-brunson-points-over-27-5",
        "sportsbook_deep_link": "https://sportsbook.fanduel.com/navigation/nba?prop=jalen-brunson-pts",
    },
}


class PolymarketArbAgent:
    """
    Cross-Venue Mispricing & Arbitrage Engine comparing PropWire's Bayesian
    Fair Probability against Sportsbook lines and the Polymarket CLOB orderbook.
    """

    AGENT_NAME = "PolymarketArbAgent"

    def __init__(
        self,
        bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
        clob_client: Any = None,
        fee_rate: float = DEFAULT_POLYMARKET_FEE_RATE,
        min_liquidity_usd: float = MIN_TOP3_LIQUIDITY_USD,
        webhook_dispatcher: WebhookDispatcher | None = None,
    ) -> None:
        self.bus = bus or DurableRedisStreamBus()
        self.truth = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self.clob_client = clob_client
        self.fee_rate = float(fee_rate)
        self.min_liquidity_usd = float(min_liquidity_usd)
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(
            truth_store=self.truth,
            bus=self.bus,
        )

        # WebSocket health state for Stale Orderbook Guard
        self.ws_connected: bool = True
        self.stale_reason: str = ""

        # Token registry and cached live orderbooks
        self.token_registry: dict[str, dict[str, Any]] = {}
        self.prop_to_token: dict[str, str] = {}
        self.player_to_tokens: dict[str, list[str]] = {}
        self.cached_orderbooks: dict[str, dict[str, Any]] = {}

        self._seed_default_mappings()

    def _seed_default_mappings(self) -> None:
        for token_id, meta in DEFAULT_ARB_TOKEN_CATALOG.items():
            self.register_token_mapping(
                token_id=token_id,
                polymarket_player_id=meta["polymarket_player_id"],
                canonical_player_id=meta["canonical_player_id"],
                player_name=meta["player_name"],
                team=meta["team"],
                opponent=meta.get("opponent", ""),
                position=meta.get("position", "G"),
                sport=meta.get("sport", "nba"),
                game_id=meta.get("game_id", "2026_nba_mil_bos"),
                prop_id=meta["prop_id"],
                market=meta.get("market", "points"),
                market_label=meta.get("market_label", f"PTS Over {meta['line']}"),
                line=float(meta["line"]),
                sportsbook_book=meta.get("sportsbook_book", "DraftKings"),
                sportsbook_odds=int(meta.get("sportsbook_odds", -110)),
                sportsbook_implied_prob=float(meta.get("sportsbook_implied_prob", 0.55)),
                fair_prob=float(meta.get("fair_prob", 0.60)),
                deep_link=meta.get("deep_link", "https://polymarket.com"),
                sportsbook_deep_link=meta.get("sportsbook_deep_link", "https://sportsbook.draftkings.com"),
            )
            self.cache_orderbook(
                token_id=token_id,
                asks=meta["asks"],
                bids=meta["bids"],
            )

    def register_token_mapping(
        self,
        *,
        token_id: str,
        polymarket_player_id: str,
        canonical_player_id: str,
        player_name: str,
        team: str,
        position: str = "G",
        opponent: str = "",
        sport: str = "nba",
        game_id: str = "2026_nba_mil_bos",
        prop_id: str | None = None,
        market: str = "points",
        market_label: str | None = None,
        line: float = 24.5,
        sportsbook_book: str = "DraftKings",
        sportsbook_odds: int = -110,
        sportsbook_implied_prob: float | None = None,
        fair_prob: float = 0.60,
        deep_link: str = "https://polymarket.com",
        sportsbook_deep_link: str = "https://sportsbook.draftkings.com",
    ) -> None:
        """
        Link a Polymarket CLOB `token_id` to `player_id_mapping` in `TruthStore`
        and register its internal `prop_id`.
        """
        resolved_prop_id = prop_id or f"{canonical_player_id}_{market}"
        self.truth.upsert_player_mapping(
            canonical_player_id=canonical_player_id,
            sport=sport,
            player_name=player_name,
            team=team,
            position=position,
            polymarket_player_id=polymarket_player_id,
        )
        if sportsbook_implied_prob is None:
            sb_over, _ = devig_two_way(sportsbook_odds, -110)
            sportsbook_implied_prob = round(sb_over, 4)

        mkt_short = (
            "PTS"
            if market == "points"
            else "REB"
            if market == "rebounds"
            else "AST"
            if market == "assists"
            else "3PT"
            if market == "threes"
            else market.upper()
        )
        meta = {
            "token_id": token_id,
            "polymarket_player_id": polymarket_player_id,
            "canonical_player_id": canonical_player_id,
            "player_name": player_name,
            "team": team,
            "opponent": opponent,
            "position": position,
            "sport": sport,
            "game_id": game_id,
            "prop_id": resolved_prop_id,
            "market": market,
            "market_label": market_label or f"{mkt_short} Over {line:.1f}",
            "line": float(line),
            "fair_prob": float(fair_prob),
            "sportsbook_book": sportsbook_book,
            "sportsbook_odds": int(sportsbook_odds),
            "sportsbook_implied_prob": float(sportsbook_implied_prob),
            "deep_link": deep_link,
            "sportsbook_deep_link": sportsbook_deep_link,
        }
        self.token_registry[token_id] = meta
        self.prop_to_token[resolved_prop_id] = token_id
        tokens = self.player_to_tokens.setdefault(canonical_player_id, [])
        if token_id not in tokens:
            tokens.append(token_id)

    def resolve_token_to_player(self, token_id: str) -> dict[str, Any] | None:
        """
        Resolve a Polymarket `token_id` to our canonical player and `prop_id`
        strictly via `TruthStore.resolve_canonical_player_id` (`player_id_mapping`).
        Fails closed (`None`) if the token or player mapping is missing.
        """
        meta = self.token_registry.get(token_id)
        if not meta:
            return None
        canonical_id = self.truth.resolve_canonical_player_id(
            polymarket_player_id=meta["polymarket_player_id"],
            sport=meta.get("sport", "nba"),
        )
        if not canonical_id or canonical_id != meta["canonical_player_id"]:
            return None
        return dict(meta)

    def cache_orderbook(
        self,
        *,
        token_id: str,
        asks: list[dict[str, Any]],
        bids: list[dict[str, Any]],
        fetched_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Cache a live Polymarket CLOB orderbook snapshot for instant 5s PBP re-evaluation."""
        now_dt = fetched_at or datetime.now(timezone.utc)
        book = {
            "token_id": token_id,
            "asks": list(asks),
            "bids": list(bids),
            "fetched_at": now_dt,
            "source_hash": compute_source_hash({"token_id": token_id, "asks": asks, "bids": bids}),
        }
        self.cached_orderbooks[token_id] = book
        return book

    def fetch_live_orderbook(self, token_id: str) -> dict[str, Any] | None:
        """
        Fetch live CLOB orderbook via injected `dr-manhattan` / `py-clob-client`
        client if configured, falling back to the cached WebSocket orderbook.
        """
        if self.clob_client is not None:
            try:
                if hasattr(self.clob_client, "get_order_book"):
                    raw = self.clob_client.get_order_book(token_id)
                elif hasattr(self.clob_client, "fetch_orderbook"):
                    raw = self.clob_client.fetch_orderbook(token_id)
                else:
                    raw = None
                if isinstance(raw, dict):
                    return self.cache_orderbook(
                        token_id=token_id,
                        asks=raw.get("asks", []),
                        bids=raw.get("bids", []),
                    )
            except Exception as exc:
                logger.warning("CLOB fetch failed for token_id=%s: %s", token_id, exc)
        return self.cached_orderbooks.get(token_id)

    def set_ws_connection_state(self, connected: bool, reason: str = "") -> None:
        """
        Update Polymarket CLOB WebSocket connection health.
        When `connected=False`, marks the Arb Board as `STALE` and suppresses alerts.
        """
        self.ws_connected = bool(connected)
        self.stale_reason = "" if connected else (reason or "Polymarket CLOB WebSocket disconnected")

    def evaluate_token_arb(
        self,
        token_id: str,
        *,
        fair_prob: float | None = None,
        sportsbook_implied_prob: float | None = None,
        sportsbook_odds: int | None = None,
        sportsbook_book: str | None = None,
        user_gate: float = 0.03,
        use_top_of_book_price: bool = False,
        catalyst_reason: str = "substitution",
        trigger_detail: str = "",
        now: datetime | None = None,
    ) -> tuple[dict[str, Any] | None, SniperAlert | None]:
        """
        Evaluate a Polymarket CLOB orderbook against the Bayesian Fair Probability
        and Sportsbook Implied Probability.

        Returns `(arb_card_dict, sniper_alert_or_none)`.
        """
        now_dt = now or datetime.now(timezone.utc)
        player_meta = self.resolve_token_to_player(token_id)
        if player_meta is None:
            return None, None

        book = self.cached_orderbooks.get(token_id) or self.fetch_live_orderbook(token_id)
        if not book:
            return None, None

        asks_vwap = compute_top3_orderbook_vwap(book.get("asks", []))
        bids_vwap = compute_top3_orderbook_vwap(book.get("bids", []))

        liquidity_usd = asks_vwap["total_liquidity_usd"]
        raw_ask_price = asks_vwap["top_price"] if use_top_of_book_price else asks_vwap["vwap_price"]
        raw_bid_price = bids_vwap["top_price"] if use_top_of_book_price else (bids_vwap["vwap_price"] or max(0.01, raw_ask_price - 0.02))

        if raw_ask_price <= 0.0:
            return None, None

        fee_prices = compute_fee_adjusted_yes_prices(
            ask_price=raw_ask_price,
            bid_price=raw_bid_price,
            fee_rate=self.fee_rate,
        )
        implied_prob = fee_prices["implied_prob"]

        eff_fair_prob = float(fair_prob if fair_prob is not None else player_meta.get("fair_prob", 0.60))
        eff_sb_prob = float(
            sportsbook_implied_prob
            if sportsbook_implied_prob is not None
            else player_meta.get("sportsbook_implied_prob", 0.55)
        )
        eff_sb_odds = int(sportsbook_odds if sportsbook_odds is not None else player_meta.get("sportsbook_odds", -110))
        eff_sb_book = str(sportsbook_book or player_meta.get("sportsbook_book", "DraftKings"))

        arb_metrics = compute_cross_venue_arb(
            fair_prob=eff_fair_prob,
            implied_prob=implied_prob,
            sportsbook_implied_prob=eff_sb_prob,
        )

        fetched_at = book.get("fetched_at") or now_dt
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        feed_age_s = max(0.0, round((now_dt - fetched_at).total_seconds(), 2))
        is_stale = (not self.ws_connected) or (feed_age_s > 90.0)

        # Determine which venue offers the best buyer edge (lowest implied cost to buy OVER/YES)
        poly_is_best = arb_metrics["poly_edge"] >= arb_metrics["sportsbook_edge"]
        best_venue = "Polymarket" if poly_is_best else eff_sb_book
        actionable_poly = (
            (not is_stale)
            and (liquidity_usd >= self.min_liquidity_usd)
            and (arb_metrics["poly_edge"] > float(user_gate))
        )

        arb_card = {
            "token_id": token_id,
            "prop_id": player_meta["prop_id"],
            "sport": player_meta["sport"],
            "game_id": player_meta["game_id"],
            "player_id": player_meta["canonical_player_id"],
            "player_name": player_meta["player_name"],
            "team": player_meta["team"],
            "opponent": player_meta["opponent"],
            "market": player_meta["market"],
            "market_label": player_meta["market_label"],
            "line": player_meta["line"],
            "fair_prob": round(eff_fair_prob, 4),
            "fair_prob_pct": round(eff_fair_prob * 100.0, 1),
            "poly_ask_price": round(asks_vwap["top_price"], 2),
            "poly_vwap_ask": round(asks_vwap["vwap_price"], 4),
            "effective_ask_yes": round(fee_prices["effective_ask_yes"], 4),
            "effective_bid_yes": round(fee_prices["effective_bid_yes"], 4),
            "implied_prob": round(implied_prob, 4),
            "implied_prob_pct": round(implied_prob * 100.0, 1),
            "sportsbook_book": eff_sb_book,
            "sportsbook_odds": eff_sb_odds,
            "sportsbook_implied_prob": round(eff_sb_prob, 4),
            "sportsbook_implied_prob_pct": round(eff_sb_prob * 100.0, 1),
            "poly_edge": arb_metrics["poly_edge"],
            "poly_edge_pct": arb_metrics["poly_edge_pct"],
            "sportsbook_edge": arb_metrics["sportsbook_edge"],
            "sportsbook_edge_pct": arb_metrics["sportsbook_edge_pct"],
            "cross_venue_spread": arb_metrics["cross_venue_spread"],
            "cross_venue_spread_pct": arb_metrics["cross_venue_spread_pct"],
            "liquidity_usd": liquidity_usd,
            "depth_levels": asks_vwap["levels_summary"],
            "depth_tooltip": asks_vwap["depth_tooltip"],
            "best_venue": best_venue,
            "action_label": (
                f"BUY YES on Polymarket"
                if poly_is_best
                else f"BET OVER on {eff_sb_book}"
            ),
            "action_url": player_meta["deep_link"] if poly_is_best else player_meta["sportsbook_deep_link"],
            "deep_link": player_meta["deep_link"],
            "sportsbook_deep_link": player_meta["sportsbook_deep_link"],
            "is_actionable_lime": actionable_poly,
            "is_stale": is_stale,
            "stale_reason": self.stale_reason if is_stale else "",
            "feed_age_seconds": feed_age_s,
            "trigger_detail": trigger_detail,
            "source_hash": book["source_hash"],
        }

        # Check guards before firing a SniperAlert
        if is_stale:
            self.truth.record_event(
                event_type="polymarket_arb.suppressed",
                prop_id=player_meta["prop_id"],
                game_id=player_meta["game_id"],
                player_id=player_meta["canonical_player_id"],
                payload=arb_card,
                source_hash=book["source_hash"],
                fetched_at=fetched_at,
                feed_age_seconds=feed_age_s,
                is_stale=True,
                decision="HALTED_STALE",
                reason=self.stale_reason or "Polymarket orderbook stale / WebSocket disconnected",
                agent_name=self.AGENT_NAME,
                sport=player_meta["sport"],
            )
            return arb_card, None

        if liquidity_usd < self.min_liquidity_usd:
            self.truth.record_event(
                event_type="polymarket_arb.suppressed",
                prop_id=player_meta["prop_id"],
                game_id=player_meta["game_id"],
                player_id=player_meta["canonical_player_id"],
                payload=arb_card,
                source_hash=book["source_hash"],
                fetched_at=fetched_at,
                feed_age_seconds=feed_age_s,
                is_stale=False,
                decision="SUPPRESSED",
                reason=f"THIN_ORDERBOOK(liquidity_usd=${liquidity_usd:.2f} < min=${self.min_liquidity_usd:.2f})",
                agent_name=self.AGENT_NAME,
                sport=player_meta["sport"],
            )
            return arb_card, None

        if arb_metrics["poly_edge"] <= float(user_gate):
            return arb_card, None

        # Fire SniperAlert with venue="Polymarket"
        american_odds = prob_to_american_odds(implied_prob)
        ev_unit = round(ev_per_unit(eff_fair_prob, american_odds), 4)
        kelly = round(0.25 * kelly_fraction(eff_fair_prob, american_odds, cap=0.06), 4)
        liq_score = min(1.0, round(liquidity_usd / 2500.0, 4))

        alert = SniperAlert(
            alert_id=f"sniper_poly_{player_meta['prop_id']}_{book['source_hash'][:8]}",
            prop_id=player_meta["prop_id"],
            sport=player_meta["sport"],
            game_id=player_meta["game_id"],
            player_id=player_meta["canonical_player_id"],
            player_name=player_meta["player_name"],
            team=player_meta["team"],
            opponent=player_meta["opponent"],
            market=player_meta["market"],
            side="YES",
            venue_type="polymarket",
            book="Polymarket",
            line=player_meta["line"],
            odds_american=american_odds,
            fair_line=round(player_meta["line"] + arb_metrics["poly_edge"] * 18.0, 1),
            fair_prob=round(eff_fair_prob, 4),
            implied_prob=round(implied_prob, 4),
            edge_pct=arb_metrics["poly_edge_pct"],
            mispricing_bps=round(arb_metrics["poly_edge"] * 10000.0, 1),
            ev_per_unit=ev_unit,
            kelly_stake=max(0.005, kelly),
            confidence_score=0.86,
            liquidity_score=max(0.25, liq_score),
            clv_expectation=round(arb_metrics["poly_edge"] * 0.65, 4),
            feed_age_seconds=feed_age_s,
            is_stale=False,
            deep_link=player_meta["deep_link"],
            catalyst_reason=catalyst_reason,
            reasoning_chain=(
                f"[CROSS-VENUE ARB] {player_meta['player_name']} {player_meta['market_label']}: "
                f"Fair Prob {eff_fair_prob * 100:.1f}% vs Polymarket Fee-Adj Ask {implied_prob * 100:.1f}% "
                f"(+${asks_vwap['top_price']:.2f}, Poly Edge +{arb_metrics['poly_edge_pct']:.2f}%) "
                f"and {eff_sb_book} {eff_sb_prob * 100:.1f}% ({eff_sb_odds:+d}). "
                f"Top-3 Depth: {asks_vwap['depth_tooltip']}."
            ),
            source_hash=book["source_hash"],
            model_version=MODEL_VERSION,
            created_at=now_dt,
        )
        self.truth.save_sniper_alert(alert)
        self.bus.xadd(
            STREAM_SNIPER,
            {
                "event_type": "sniper.polymarket_arb_fired",
                "venue": "Polymarket",
                "alert_id": alert.alert_id,
                "prop_id": alert.prop_id,
                "payload": alert.model_dump(mode="json"),
                "arb_card": arb_card,
            },
        )
        if self.webhook_dispatcher is not None:
            self.webhook_dispatcher.dispatch_alert(
                alert,
                arb_card=arb_card,
                async_dispatch=True,
            )
        return arb_card, alert

    def on_projection_recalc_5s_update(
        self,
        projection: PropProjection,
        *,
        user_gate: float = 0.03,
        sportsbook_implied_prob: float | None = None,
        now: datetime | None = None,
    ) -> list[tuple[dict[str, Any], SniperAlert | None]]:
        """
        Triggered immediately when `ProjectionRecalcAgent` fires a 5s PBP substitution
        update. Re-evaluates the cached Polymarket orderbook for the affected player/prop
        without waiting for the next 30-second poll.
        """
        candidate_tokens: list[str] = []
        if projection.prop_id in self.prop_to_token:
            candidate_tokens.append(self.prop_to_token[projection.prop_id])
        for tok in self.player_to_tokens.get(projection.player_id, []):
            if tok not in candidate_tokens:
                candidate_tokens.append(tok)

        results: list[tuple[dict[str, Any], SniperAlert | None]] = []
        for token_id in candidate_tokens:
            card, alert = self.evaluate_token_arb(
                token_id,
                fair_prob=projection.fair_prob_over,
                sportsbook_implied_prob=sportsbook_implied_prob,
                user_gate=user_gate,
                catalyst_reason=projection.catalyst_reason,
                trigger_detail=projection.catalyst_detail,
                now=now,
            )
            if card is not None:
                results.append((card, alert))
        return results

    def get_arb_board_snapshot(
        self,
        *,
        user_gate: float = 0.03,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return all active Cross-Venue Arb Board cards ranked by `poly_edge_pct` descending."""
        cards: list[dict[str, Any]] = []
        for token_id in self.token_registry:
            card, _ = self.evaluate_token_arb(
                token_id,
                user_gate=user_gate,
                now=now,
            )
            if card is not None:
                cards.append(card)
        cards.sort(key=lambda c: float(c.get("poly_edge_pct", 0.0)), reverse=True)
        return cards

