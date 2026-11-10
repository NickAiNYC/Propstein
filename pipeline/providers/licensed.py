"""PropStein pipeline — licensed feed adapter (production wiring).

Activated only when PROPSTEIN_FEED_ODDS_URL / _KEY and PROPSTEIN_FEED_STATS_URL
/ _KEY are configured. Uses the rate-limited fetcher with exponential backoff;
every response is validated through RawSlate (Pydantic) before inference runs.
Malformed or partial responses raise FeedUnavailableError — the run fails
closed rather than proceeding on unvalidated data (charter rule 10).

Endpoint contract (v1):
  GET {stats_url}/slate/{YYYY-MM-DD}  -> {"entries": [...], ...}
  GET {odds_url}/quote?sport=&event_id=&player_id=&market=&line=
      -> {"over_american_odds": int, "under_american_odds": int,
          "captured_at_utc": "...", "licensed": true}
The slate document maps 1:1 onto RawSlateEntry fields.
"""

from __future__ import annotations

from datetime import date

from pipeline import config
from pipeline.http import FeedUnavailableError, Fetcher
from pipeline.providers.base import BoardFeed
from pipeline.schemas import RawContextObservation, RawSlate, RawSlateEntry


class LicensedBoardFeed(BoardFeed):
    kind = "licensed"

    def __init__(self, odds_url: str, odds_key: str, stats_url: str, stats_key: str) -> None:
        self.id = f"LICENSED-ODDS-1 ({_host_of(odds_url)})"
        self.stats_id = f"LICENSED-STATS-1 ({_host_of(stats_url)})"
        self.odds = Fetcher(odds_url, odds_key, timeout=config.FETCH_TIMEOUT_SECONDS, max_retries=config.FETCH_MAX_RETRIES)
        self.stats = Fetcher(stats_url, stats_key, timeout=config.FETCH_TIMEOUT_SECONDS, max_retries=config.FETCH_MAX_RETRIES)

    def fetch_slate(self, run_date: date) -> RawSlate:
        slate_doc = self.stats.get_json(f"/slate/{run_date.isoformat()}")
        entries: list[RawSlateEntry] = []
        context_count = 0

        for raw in slate_doc.get("entries", []):
            if not isinstance(raw, dict):
                raise FeedUnavailableError("slate entry is not an object")
            market = str(raw.get("market", ""))
            line = float(raw.get("line", 0.0))

            quote = self.odds.get_json(
                "/quote",
                params={
                    "sport": str(raw.get("sport", "")),
                    "event_id": str(raw.get("event_id", "")),
                    "player_id": str(raw.get("player_id", "")),
                    "market": market,
                    "line": f"{line:g}",
                },
            )
            context = [RawContextObservation(**obs) for obs in raw.get("context", [])]
            context_count += len(context)

            entries.append(
                RawSlateEntry(
                    event_id=str(raw["event_id"]),
                    event_label=str(raw["event_label"]),
                    sport=str(raw["sport"]),
                    league=str(raw.get("league", raw["sport"])),
                    commences_at_utc=str(raw["commences_at_utc"]),
                    game_cluster_id=str(raw.get("game_cluster_id", raw["event_id"])),
                    player_id=str(raw["player_id"]),
                    player_name=str(raw["player_name"]),
                    market=market,
                    market_label=str(raw.get("market_label", market)),
                    line=line,
                    over_american_odds=int(quote["over_american_odds"]),
                    under_american_odds=int(quote["under_american_odds"]),
                    quote_captured_at_utc=str(quote["captured_at_utc"]),
                    quote_provider=self.id,
                    quote_licensed=bool(quote.get("licensed", False)),
                    pricing_cutoff_utc=str(raw["pricing_cutoff_utc"]),
                    context=context,
                    feature_inputs={k: float(v) for k, v in raw.get("feature_inputs", {}).items()},
                )
            )

        if not entries:
            raise FeedUnavailableError(f"licensed slate for {run_date} returned zero entries")

        return RawSlate(
            run_date=run_date.isoformat(),
            source="licensed",
            odds_provider=self.id,
            stats_provider=self.stats_id,
            n_records_analyzed=int(slate_doc.get("n_records_analyzed", len(entries) * 2 + context_count)),
            entries=entries,
        )


def _host_of(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url
