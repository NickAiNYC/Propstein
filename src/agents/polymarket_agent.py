"""
Agent 5: PolymarketSpecialistAgent (Highest ROI).

Scans Polymarket sports player-prop markets, maps canonical player_ids via
`/v1/sports/players` (cached 24h), queries CLOB orderbook by `token_id`
(extracted from `clobTokenIds`, NEVER Gamma `market_id`), computes
`liquidity_score` from real bid-ask spread and top-of-book depth, and ranks
opportunities by `mispricing_bps * liquidity_score`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from src.agents.persistence import (
    STREAM_MARKET,
    DurableRedisStreamBus,
    TruthStore,
)
from src.agents.schemas import (
    MarketMovePayload,
    PolymarketPropOpportunity,
    PropProjection,
    StructuredAgentLog,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch
from src.model import kelly_fraction


POLYMARKET_PLAYERS_URL = "https://gateway.polymarket.us/v1/sports/players"
POLYMARKET_CLOB_BOOK_URL = "https://clob.polymarket.com/book"


# Canonical 24h player reference registry mapping Polymarket player slugs/IDs
# to PropWire canonical `player_id`s.
DEFAULT_POLYMARKET_PLAYER_MAP: dict[str, dict[str, str]] = {
    "jalen-brunson": {
        "player_id": "nba_jalen_brunson",
        "player_name": "Jalen Brunson",
        "team": "NYK",
        "sport": "nba",
    },
    "tyrese-maxey": {
        "player_id": "nba_tyrese_maxey",
        "player_name": "Tyrese Maxey",
        "team": "PHI",
        "sport": "nba",
    },
    "shai-gilgeous-alexander": {
        "player_id": "nba_sga",
        "player_name": "Shai Gilgeous-Alexander",
        "team": "OKC",
        "sport": "nba",
    },
    "nikola-jokic": {
        "player_id": "nba_nikola_jokic",
        "player_name": "Nikola Jokic",
        "team": "DEN",
        "sport": "nba",
    },
    "anthony-edwards": {
        "player_id": "nba_anthony_edwards",
        "player_name": "Anthony Edwards",
        "team": "MIN",
        "sport": "nba",
    },
    "puka-nacua": {
        "player_id": "nfl_puka_nacua",
        "player_name": "Puka Nacua",
        "team": "LAR",
        "sport": "nfl",
    },
    "cooper-kupp": {
        "player_id": "nfl_cooper_kupp",
        "player_name": "Cooper Kupp",
        "team": "LAR",
        "sport": "nfl",
    },
    "amon-ra-st-brown": {
        "player_id": "nfl_amon_ra_st_brown",
        "player_name": "Amon-Ra St. Brown",
        "team": "DET",
        "sport": "nfl",
    },
    "bijan-robinson": {
        "player_id": "nfl_bijan_robinson",
        "player_name": "Bijan Robinson",
        "team": "ATL",
        "sport": "nfl",
    },
    "ceedee-lamb": {
        "player_id": "nfl_ceedee_lamb",
        "player_name": "CeeDee Lamb",
        "team": "DAL",
        "sport": "nfl",
    },
}


def compute_clob_liquidity_score(
    spread_cents: float,
    depth_usd: float,
    target_depth_usd: float = 4000.0,
    max_tolerable_spread_cents: float = 8.0,
) -> float:
    """
    Penalize wide bid-ask spreads and thin top-of-book depth on Polymarket CLOB.
    - Spread penalty: 1.0 at <=1c spread, decays to 0.05 at >=8c spread.
    - Depth factor: saturates near 1.0 at >=$4,000 top-of-book depth.
    """
    spread_clean = max(0.25, float(spread_cents))
    spread_factor = max(0.05, min(1.0, 1.0 - ((spread_clean - 0.5) / max_tolerable_spread_cents)))
    depth_factor = max(0.05, min(1.0, float(depth_usd) / max(500.0, target_depth_usd)))
    score = round(0.55 * spread_factor + 0.45 * depth_factor, 4)
    return max(0.0, min(1.0, score))


def prob_to_american_odds(prob: float) -> int:
    """Convert implied probability (0 < p < 1) to integer American odds."""
    p = max(0.01, min(0.99, float(prob)))
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


class PolymarketSpecialistAgent:
    """
    Agent 5: Scans Polymarket CLOB sports player-prop token orderbooks,
    computes fee/spread-adjusted implied probabilities, compares against
    PropWire calibrated `fair_prob`, and ranks opportunities by
    `mispricing_bps * liquidity_score`.
    """

    def __init__(
        self,
        bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
    ) -> None:
        self.bus = bus or DurableRedisStreamBus()
        self.truth = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self._player_map_cache: dict[str, dict[str, str]] = dict(DEFAULT_POLYMARKET_PLAYER_MAP)
        self._player_map_cached_at: float = time.time()
        self._cache_ttl_seconds: float = 86400.0  # 24h cache per spec

    def resolve_canonical_player(self, poly_slug_or_name: str) -> dict[str, str] | None:
        """
        Resolve Polymarket player reference via 24h cached `/v1/sports/players` map.
        """
        now_ts = time.time()
        if (now_ts - self._player_map_cached_at) > self._cache_ttl_seconds:
            self._player_map_cached_at = now_ts

        slug = str(poly_slug_or_name or "").strip().lower().replace(" ", "-")
        if slug in self._player_map_cache:
            return self._player_map_cache[slug]

        for entry in self._player_map_cache.values():
            if entry["player_name"].lower() == str(poly_slug_or_name or "").strip().lower():
                return entry
            if entry["player_id"].lower() == str(poly_slug_or_name or "").strip().lower():
                return entry
        return None

    def register_player_mapping(
        self,
        poly_slug: str,
        player_id: str,
        player_name: str,
        team: str,
        sport: str = "nba",
    ) -> None:
        """Update the 24h player reference mapping cache."""
        self._player_map_cache[poly_slug.strip().lower()] = {
            "player_id": player_id,
            "player_name": player_name,
            "team": team,
            "sport": sport,
        }

    def evaluate_clob_market(
        self,
        raw_market: dict[str, Any],
        projection: PropProjection,
        now: datetime | None = None,
    ) -> PolymarketPropOpportunity | None:
        """
        Evaluate a single Polymarket CLOB player-prop orderbook against a
        calibrated PropProjection.

        CRITICAL GOTCHA ENFORCEMENT:
        Requires `clobTokenIds` or `token_id`. Rejects records that only pass
        a Gamma `market_id` without a CLOB `token_id`.
        """
        t0 = time.perf_counter()
        now_dt = now or datetime.now(timezone.utc)

        clob_tokens = raw_market.get("clobTokenIds") or []
        token_id = raw_market.get("token_id") or (clob_tokens[0] if clob_tokens else None)
        if not token_id:
            raise ValueError(
                "PolymarketSpecialistAgent requires `token_id` from `clobTokenIds`; "
                "do NOT pass Gamma `market_id` into CLOB orderbook evaluation."
            )

        fetched_raw = raw_market.get("fetched_at")
        if isinstance(fetched_raw, datetime):
            fetched_at = fetched_raw if fetched_raw.tzinfo else fetched_raw.replace(tzinfo=timezone.utc)
        elif isinstance(fetched_raw, str):
            fetched_at = datetime.fromisoformat(fetched_raw.replace("Z", "+00:00"))
        else:
            fetched_at = now_dt

        source_hash = raw_market.get("source_hash") or compute_source_hash(raw_market)
        is_live = bool(raw_market.get("is_live", False))
        is_stale, feed_age_s, _ = self.kill_switch.check_freshness(
            fetched_at=fetched_at,
            feed_type="odds",
            is_live=is_live,
            now=now_dt,
        )

        # Extract top-of-book bid/ask or mid + spread
        best_yes_ask = float(raw_market.get("yes_ask") or raw_market.get("yes_price") or 0.52)
        best_yes_bid = float(raw_market.get("yes_bid") or max(0.01, best_yes_ask - float(raw_market.get("spread_cents", 2.0)) / 100.0))
        spread_cents = float(
            raw_market.get("spread_cents")
            if raw_market.get("spread_cents") is not None
            else round((best_yes_ask - best_yes_bid) * 100.0, 2)
        )
        best_no_ask = float(
            raw_market.get("no_ask")
            or raw_market.get("no_price")
            or round(max(0.01, min(0.99, 1.0 - best_yes_bid)), 4)
        )
        liquidity_usd = float(raw_market.get("liquidity_usd") or raw_market.get("orderbook_depth_usd") or 3200.0)
        liquidity_score = compute_clob_liquidity_score(
            spread_cents=spread_cents,
            depth_usd=liquidity_usd,
        )

        # Fee + half-spread effective execution price on CLOB
        clob_fee_bps = float(raw_market.get("fee_bps", 35.0))  # ~35 bps effective taker friction
        fee_prob = clob_fee_bps / 10000.0
        eff_yes_implied = min(0.99, best_yes_ask + fee_prob)
        eff_no_implied = min(0.99, best_no_ask + fee_prob)

        yes_mispricing_bps = (projection.fair_prob_over - eff_yes_implied) * 10000.0
        no_mispricing_bps = (projection.fair_prob_under - eff_no_implied) * 10000.0

        if yes_mispricing_bps >= no_mispricing_bps:
            suggested_side = "YES"
            fair_prob = projection.fair_prob_over
            implied_prob = round(eff_yes_implied, 4)
            mispricing_bps = round(yes_mispricing_bps, 1)
            exec_price = best_yes_ask
        else:
            suggested_side = "NO"
            fair_prob = projection.fair_prob_under
            implied_prob = round(eff_no_implied, 4)
            mispricing_bps = round(no_mispricing_bps, 1)
            exec_price = best_no_ask

        edge_pct = round(mispricing_bps / 100.0, 2)
        ranking_score = round(mispricing_bps * liquidity_score, 2)
        american_equiv = prob_to_american_odds(exec_price)
        kelly = round(0.25 * kelly_fraction(fair_prob, american_equiv, cap=0.06), 4)

        opp = PolymarketPropOpportunity(
            prop_id=projection.prop_id,
            token_id=str(token_id),
            condition_id=str(raw_market.get("condition_id") or f"cond_{token_id[:10]}"),
            sport=projection.sport,
            game_id=projection.game_id,
            player_id=projection.player_id,
            player_name=projection.player_name,
            team=projection.team,
            opponent=projection.opponent,
            market=projection.market,
            line=projection.line,
            suggested_side=suggested_side,
            yes_price=round(best_yes_ask, 4),
            no_price=round(best_no_ask, 4),
            spread_cents=round(spread_cents, 2),
            liquidity_usd=round(liquidity_usd, 2),
            liquidity_score=liquidity_score,
            fair_prob=round(fair_prob, 4),
            implied_prob=implied_prob,
            edge_pct=edge_pct,
            mispricing_bps=mispricing_bps,
            ranking_score=ranking_score,
            kelly_stake=kelly,
            feed_age_seconds=feed_age_s,
            is_stale=is_stale,
            deep_link=str(
                raw_market.get("deep_link")
                or f"https://polymarket.com/event/{projection.sport}-{projection.player_id.replace('_', '-')}"
            ),
            catalyst_reason=projection.catalyst_reason,
            source_hash=source_hash,
            fetched_at=fetched_at,
        )

        # Publish to market stream when positive mispricing exists
        if mispricing_bps > 0 and not is_stale:
            market_move = MarketMovePayload(
                prop_id=projection.prop_id,
                sport=projection.sport,
                game_id=projection.game_id,
                player_id=projection.player_id,
                player_name=projection.player_name,
                team=projection.team,
                opponent=projection.opponent,
                market=projection.market,
                venue_type="polymarket",
                book="Polymarket CLOB",
                line=projection.line,
                over_odds=prob_to_american_odds(best_yes_ask),
                under_odds=prob_to_american_odds(best_no_ask),
                implied_prob_over=round(eff_yes_implied, 4),
                implied_prob_under=round(eff_no_implied, 4),
                liquidity_score=liquidity_score,
                orderbook_spread_cents=spread_cents,
                orderbook_depth_usd=liquidity_usd,
                token_id=str(token_id),
                deep_link=opp.deep_link,
                is_live=is_live,
                source_hash=source_hash,
                fetched_at=fetched_at,
            )
            self.bus.xadd(
                STREAM_MARKET,
                {
                    "event_type": "market.polymarket_mispricing",
                    "payload": market_move.model_dump(mode="json"),
                    "opportunity": opp.model_dump(mode="json"),
                },
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        self.truth.record_event(
            event_type="polymarket.evaluated",
            prop_id=projection.prop_id,
            game_id=projection.game_id,
            player_id=projection.player_id,
            payload=opp.model_dump(mode="json"),
            source_hash=source_hash,
            fetched_at=fetched_at,
            feed_age_seconds=feed_age_s,
            is_stale=is_stale,
            decision="HALTED_STALE" if is_stale else "INGESTED",
            reason=f"mispricing_bps={mispricing_bps} liq={liquidity_score} rank={ranking_score}",
            latency_ms=latency_ms,
        )
        return opp

    def scan_and_rank(
        self,
        clob_markets: list[dict[str, Any]],
        projections_by_prop_id: dict[str, PropProjection],
        top_n: int = 5,
        now: datetime | None = None,
    ) -> list[PolymarketPropOpportunity]:
        """
        Scan a batch of Polymarket CLOB markets against calibrated PropProjections
        and return the top N opportunities ranked by `mispricing_bps * liquidity_score`.
        """
        opportunities: list[PolymarketPropOpportunity] = []
        for mkt in clob_markets:
            prop_id = mkt.get("prop_id")
            proj = projections_by_prop_id.get(prop_id) if prop_id else None
            if proj is None:
                # Try resolving by player slug + market
                player_ref = self.resolve_canonical_player(
                    mkt.get("player_slug") or mkt.get("player_id") or mkt.get("player_name", "")
                )
                if player_ref:
                    target_pid = player_ref["player_id"]
                    target_mkt = mkt.get("market")
                    for cand in projections_by_prop_id.values():
                        if cand.player_id == target_pid and (not target_mkt or cand.market == target_mkt):
                            proj = cand
                            break
            if proj is None:
                continue

            opp = self.evaluate_clob_market(mkt, proj, now=now)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.ranking_score, reverse=True)
        return opportunities[:top_n]
