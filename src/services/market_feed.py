"""
Market Feed Bridge (`src/services/market_feed.py`)
==================================================

Mission W1 integration: push live DK/FD player-prop quotes (PropLine primary,
The Odds API / Bovada fallback) into the Sniper pipeline the moment they land:

  1. `MarketIngestAgent.ingest_quote(...)` — publishes `market.line_moved`
     (Stale Kill Switch + noise filter still apply; no LLM in the decision path).
  2. `TruthStore.upsert_last_known_odds(...)` — the table the Cross-Venue Arb
     engine compares `Fair_Prob` against (`Sportsbook_Edge = Fair_Prob -
     DraftKings_Implied_Prob`) and `scripts/grade_arb_history.py` reads closing
     lines from.

Failure policy (mission): each provider is isolated inside
`CompositeLiveOddsProvider`; the refresh loop additionally wraps each push so a
single bad quote or a down API can never block the MarketAgent loop.

Run in production (Railway service `market_feed`):
    python -m src.services.market_feed
"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any

from src.odds_adapter import CompositeLiveOddsProvider, PropQuote

logger = logging.getLogger("propwire.service.market_feed")

# market_agent docstring cadence: 10-20s live, 60s pregame. The feed loop uses
# a conservative 60s default (override with MARKET_FEED_INTERVAL_SECONDS).
DEFAULT_INTERVAL_SECONDS = int(os.environ.get("MARKET_FEED_INTERVAL_SECONDS", "60"))

# Basketball player-prop markets imply NBA; reception/yard markets imply NFL.
NBA_MARKETS = {"points", "rebounds", "assists", "threes"}


def player_key(player_raw_name: str) -> str:
    """Stable slug for a player name ('Giannis Antetokounmpo' -> 'giannis_antetokounmpo')."""
    slug = str(player_raw_name or "unknown_player").strip().lower()
    for ch in (".", "'", ","):
        slug = slug.replace(ch, "")
    return "_".join(slug.split()) or "unknown_player"


def quote_sport(quote: PropQuote) -> str:
    return "nba" if quote.market in NBA_MARKETS else "nfl"


def quote_prop_id(quote: PropQuote) -> str:
    """Stable prop id used by both ingest and last_known_odds (matches the
    arb-ledger fallback lookup shape `{player_id}:{market}`)."""
    return f"{player_key(quote.player_raw_name)}:{quote.market}"


def quote_source_hash(quote: PropQuote) -> str:
    basis = f"{quote.quote_id}:{quote.observed_at}:{quote.line}:{quote.over_odds}:{quote.under_odds}"
    return hashlib.sha256(basis.encode()).hexdigest()


def quote_to_raw_ingest(quote: PropQuote, *, now: datetime | None = None) -> dict[str, Any]:
    """Pure mapper: PropQuote -> MarketIngestAgent.ingest_quote raw dict."""
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "prop_id": quote_prop_id(quote),
        "sport": quote_sport(quote),
        "game_id": "",  # PropLine event ids are feed-scoped; pipeline keys on player:market
        "player_id": player_key(quote.player_raw_name),
        "player_name": quote.player_raw_name,
        "team": quote.team or "UNK",
        "opponent": quote.opponent or "UNK",
        "market": quote.market,
        "venue_type": "sportsbook",
        "book": quote.book,
        "line": float(quote.line),
        "over_odds": int(quote.over_odds),
        "under_odds": int(quote.under_odds) if quote.under_odds is not None else -110,
        "liquidity_score": 0.90,
        "deep_link": quote.source_url,
        "is_live": True,
        "fetched_at": quote.observed_at or now_iso,
        "source_hash": quote_source_hash(quote),
    }


def push_quotes_to_truth(
    quotes: list[PropQuote],
    *,
    truth: Any,
    market_agent: Any | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """
    Dual-write every fresh quote into `last_known_odds` (arb engine + grader)
    and, when a MarketIngestAgent is supplied, the event pipeline. Per-quote
    try/except: one malformed quote never blocks the rest of the batch.
    """
    now_dt = now or datetime.now(timezone.utc)
    ingested = skipped = failed = 0

    for quote in quotes:
        try:
            raw = quote_to_raw_ingest(quote, now=now_dt)
            truth.upsert_last_known_odds(
                {
                    "prop_id": raw["prop_id"],
                    "sport": raw["sport"],
                    "game_id": raw["game_id"],
                    "player_id": raw["player_id"],
                    "market": raw["market"],
                    "book": raw["book"],
                    "venue_type": "sportsbook",
                    "line": raw["line"],
                    "over_odds": raw["over_odds"],
                    "under_odds": raw["under_odds"],
                    "liquidity_score": raw["liquidity_score"],
                    "source_hash": raw["source_hash"],
                    "fetched_at": now_dt.isoformat(),
                }
            )
            if market_agent is not None:
                market_agent.ingest_quote(raw, now=now_dt)
            ingested += 1
        except Exception as exc:
            failed += 1
            logger.warning("market_feed: quote push failed for %s: %s", getattr(quote, "quote_id", "?"), exc)
            continue

    return {"ingested": ingested, "skipped": skipped, "failed": failed}


def fetch_and_refresh(
    *,
    season: int,
    week: int | None = None,
    game_id: str | None = None,
    truth: Any = None,
    market_agent: Any | None = None,
    provider: CompositeLiveOddsProvider | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    One refresh cycle: composite fetch (PropLine -> selected/Odds API -> Bovada,
    provider-failure isolated) + dual-write push. Returns a small summary dict.
    """
    comp = provider or CompositeLiveOddsProvider()
    quotes = comp.fetch_quotes(season, week, game_id)
    summary: dict[str, Any] = {"fetched": len(quotes), "books": sorted({q.book for q in quotes})}
    if truth is not None:
        summary.update(push_quotes_to_truth(quotes, truth=truth, market_agent=market_agent, now=now))
    return summary


def main() -> int:
    """Standalone production loop. A failure in any cycle is logged and the
    loop continues — the feed never dies because one API had a bad minute."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    running = True

    def _sig_handler(signum: int, _frame: Any) -> None:
        nonlocal running
        logger.info("Signal %d received, market feed shutting down gracefully", signum)
        running = False

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    # Lazy engine imports keep this module importable without the agent graph.
    from src.agents.market_agent import MarketIngestAgent
    from src.agents.persistence import TruthStore

    truth = TruthStore()
    market_agent = MarketIngestAgent(stream_bus=None, truth_store=truth)
    season = int(os.environ.get("MARKET_FEED_SEASON", "2026"))
    week = os.environ.get("MARKET_FEED_WEEK") or None

    interval = max(10, DEFAULT_INTERVAL_SECONDS)
    logger.info("market_feed loop started (interval=%ds season=%s week=%s)", interval, season, week)
    while running:
        cycle_started = time.perf_counter()
        try:
            summary = fetch_and_refresh(
                season=season,
                week=int(week) if week else None,
                truth=truth,
                market_agent=market_agent,
            )
            logger.info(
                "market_feed cycle: fetched=%d ingested=%s failed=%s books=%s in %.1fs",
                summary.get("fetched", 0),
                summary.get("ingested", 0),
                summary.get("failed", 0),
                summary.get("books", []),
                time.perf_counter() - cycle_started,
            )
        except Exception as exc:
            logger.error("market_feed cycle failed (loop continues): %s", exc)

        sleep_remaining = interval
        while running and sleep_remaining > 0:
            time.sleep(1)
            sleep_remaining -= 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
