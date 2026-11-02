"""
Agent 4: MarketIngestAgent

Inputs:
  - PropLine API (DraftKings, FanDuel, Pinnacle, PrizePicks player props)
  - Odds-API.io (415+ bookmakers)
  - Polymarket CLOB + Sports Data API (`/v1/sports/players` for player mapping,
    `token_id` for orderbook)

Cadence: 10-20s live, 60s pregame.
Noise Filter: Emits `market.line_moved` ONLY when line shifts >= 0.5 units
or de-vigged implied probability shifts >= 1.2% (120 bps), preventing noisy ticks.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from src.agents.persistence import TOPIC_MARKET, DurableRedisStreamBus, TruthStore
from src.agents.schemas import (
    MarketMovePayload,
    StructuredAgentLog,
    compute_dedup_hash,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch
from src.model import devig_two_way

logger = logging.getLogger("propwire.agent.market")

BOOK_DEEP_LINKS = {
    "draftkings": "https://sportsbook.draftkings.com",
    "fanduel": "https://sportsbook.fanduel.com",
    "pinnacle": "https://www.pinnacle.com/en/basketball/nba/matchups",
    "prizepicks": "https://app.prizepicks.com",
    "betmgm": "https://sports.betmgm.com",
    "caesars": "https://sportsbook.caesars.com",
    "polymarket": "https://polymarket.com/sports",
}


class MarketIngestAgent:
    """
    Ingests sportsbook and prediction market player prop quotes, filters sub-threshold
    noise ticks, checks the Stale Kill Switch, and publishes `market.line_moved`
    to `propwire.events.market`.
    """

    AGENT_NAME = "MarketIngestAgent"

    def __init__(
        self,
        stream_bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
        line_noise_threshold: float = 0.5,
        prob_noise_threshold: float = 0.012,
        bus: DurableRedisStreamBus | None = None,
        propline_api_key: str | None = None,
        odds_api_key: str | None = None,
    ):
        self.stream_bus = stream_bus or bus or DurableRedisStreamBus()
        self.truth_store = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self.line_noise_threshold = line_noise_threshold
        self.prob_noise_threshold = prob_noise_threshold
        self.propline_api_key = propline_api_key or os.environ.get("PROPLINE_API_KEY")
        self.odds_api_key = odds_api_key or os.environ.get("ODDS_API_KEY")
        self._last_seen_quotes: dict[str, tuple[float, float]] = {}

    def fetch_and_ingest_props(
        self,
        *,
        season: int = 2026,
        week: int = 7,
        game_id: str | None = None,
        sport: str = "nfl",
        provider_override: Any | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Ingest live player props via PropLine (with automatic failover to The Odds API)
        into market_state and the event stream.
        """
        from src.odds_adapter import PropLineProvider
        provider = provider_override or PropLineProvider(api_key=self.propline_api_key)
        quotes = provider.fetch_quotes(season=season, week=week, game_id=game_id)

        results = []
        for q in quotes:
            raw = {
                "sport": sport,
                "game_id": game_id or f"{season}_w{week}",
                "player_id": q.player_raw_name.lower().replace(" ", "_"),
                "player_name": q.player_raw_name,
                "team": q.team or "UNK",
                "opponent": q.opponent or "UNK",
                "market": q.market,
                "venue_type": "sportsbook",
                "book": q.book,
                "line": q.line,
                "over_odds": q.over_odds,
                "under_odds": q.under_odds if q.under_odds is not None else -110,
                "is_live": False,
                "fetched_at": q.observed_at,
            }
            res = self.ingest_quote(raw, now=now)
            results.append(res)
        return results

    def ingest_quote(
        self,
        raw_quote: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        source_hash = raw_quote.get("source_hash") or compute_source_hash(raw_quote)
        fetched_at = raw_quote.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        elif not isinstance(fetched_at, datetime):
            fetched_at = datetime.now(timezone.utc)

        sport = str(raw_quote.get("sport", "nba")).lower()
        game_id = str(raw_quote.get("game_id", "live_game"))
        player_id = str(raw_quote.get("player_id", ""))
        market = str(raw_quote.get("market", "points" if sport == "nba" else "receiving_yards"))
        prop_id = raw_quote.get("prop_id") or f"{game_id}::{player_id}::{market}"
        book = str(raw_quote.get("book", "DraftKings"))
        venue_type = "polymarket" if book.lower() == "polymarket" or raw_quote.get("venue_type") == "polymarket" else "sportsbook"

        line = float(raw_quote.get("line", 0.0))
        over_odds = int(raw_quote.get("over_odds", -110))
        under_odds = int(raw_quote.get("under_odds", -110))

        if "implied_prob_over" in raw_quote and raw_quote["implied_prob_over"] is not None:
            p_over = float(raw_quote["implied_prob_over"])
            p_under = float(raw_quote.get("implied_prob_under", round(1.0 - p_over, 4)))
        else:
            p_over, p_under = devig_two_way(over_odds, under_odds)
            p_over = round(float(p_over), 4)
            p_under = round(float(p_under), 4)

        book_key = f"{prop_id}::{book.lower()}"
        prev = self._last_seen_quotes.get(book_key)
        if prev is not None:
            prev_line, prev_prob = prev
            if abs(line - prev_line) < self.line_noise_threshold and abs(p_over - prev_prob) < self.prob_noise_threshold:
                return {
                    "emitted": False,
                    "decision": "DEDUP_SKIPPED",
                    "reason": f"Sub-threshold market noise: d_line={abs(line - prev_line):.2f}, d_prob={abs(p_over - prev_prob):.4f}",
                    "prop_id": prop_id,
                    "source_hash": source_hash,
                }

        self._last_seen_quotes[book_key] = (line, p_over)
        deep_link = raw_quote.get("deep_link") or BOOK_DEEP_LINKS.get(book.lower(), "https://propstein.vercel.app")

        payload = MarketMovePayload(
            prop_id=prop_id,
            sport=sport,  # type: ignore[arg-type]
            game_id=game_id,
            player_id=player_id,
            player_name=raw_quote.get("player_name", player_id),
            team=raw_quote.get("team", "UNK"),
            opponent=raw_quote.get("opponent", "UNK"),
            market=market,
            venue_type=venue_type,  # type: ignore[arg-type]
            book=book,
            line=line,
            over_odds=over_odds,
            under_odds=under_odds,
            implied_prob_over=p_over,
            implied_prob_under=p_under,
            liquidity_score=float(raw_quote.get("liquidity_score", 0.90 if venue_type == "sportsbook" else 0.65)),
            orderbook_spread_cents=float(raw_quote.get("orderbook_spread_cents", 1.5)),
            orderbook_depth_usd=float(raw_quote.get("orderbook_depth_usd", 10000.0)),
            token_id=raw_quote.get("token_id"),
            deep_link=deep_link,
            is_live=bool(raw_quote.get("is_live", False)),
            source_hash=source_hash,
            fetched_at=fetched_at,
        )

        is_stale, age_s, _, stale_reason = self.kill_switch.evaluate(
            agent_name=self.AGENT_NAME,
            event_type="market.line_moved",
            prop_id=prop_id,
            feed_type="odds",
            fetched_at=payload.fetched_at,
            source_hash=source_hash,
            is_live=payload.is_live,
            now=now,
        )

        dedup_key = compute_dedup_hash(prop_id, book, f"{line:.1f}", f"{p_over:.4f}")
        decision = "HALTED_STALE" if is_stale else "INGESTED"
        event_dict = {
            "event_type": "market.line_moved",
            "payload": payload.model_dump(mode="json"),
            "affected_player_ids": [player_id],
            "affected_game_id": game_id,
            "dedup_key": dedup_key,
            "source_hash": source_hash,
            "fetched_at": payload.fetched_at.isoformat(),
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
        }

        stream_id = self.stream_bus.xadd(TOPIC_MARKET, event_dict, source_hash=source_hash)
        self.truth_store.record_agent_event(
            stream_topic=TOPIC_MARKET,
            agent_name=self.AGENT_NAME,
            event_type="market.line_moved",
            sport=sport,
            affected_game_id=game_id,
            affected_player_ids=[player_id],
            dedup_key=dedup_key,
            event_payload=payload.model_dump(mode="json"),
            source_hash=source_hash,
            fetched_at=payload.fetched_at,
            feed_age_seconds=age_s,
            is_stale=is_stale,
            decision=decision,
            reason=stale_reason,
        )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(
            StructuredAgentLog(
                agent=self.AGENT_NAME,
                event_type="market.line_moved",
                prop_id=prop_id,
                latency_ms=latency_ms,
                decision=decision,
                reason=stale_reason,
                source_hash=source_hash,
                feed_age_seconds=age_s,
                is_stale=is_stale,
            ).model_dump_json()
        )

        return {
            "emitted": True,
            "stream_id": stream_id,
            "decision": decision,
            "prop_id": prop_id,
            "source_hash": source_hash,
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
            "payload": payload,
        }
