"""
Live odds ingestion (The Odds API) plus a no-vig consensus line.

Player props are a PREMIUM endpoint on The Odds API and are billed per market
per event, not per request. A full NFL slate of receptions + receiving yards
across ~8 books is roughly 250-450 credits per pull. Budget for it, and cache.

The single most valuable thing in here is `no_vig_consensus`. Your model
should never be compared against one book's price. It should be compared
against the de-vigged consensus of the sharpest books available, because that
consensus IS the market's best estimate and it is what you have to beat.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# Markets. Note the alternate variants - these are what alt lines come from.
MARKETS = ["player_receptions", "player_reception_yds"]
ALT_MARKETS = ["player_receptions_alternate", "player_reception_yds_alternate"]

# Books whose prices actually carry information. Recreational books are useful
# to BET into but their prices should not move your estimate.
SHARP_BOOKS = ["pinnacle", "betonlineag", "lowvig", "circasports"]


@dataclass
class PropQuote:
    event_id: str
    commence_time: str
    book: str
    player: str
    market: str
    line: float
    over_odds: float
    under_odds: float | None


class OddsClient:
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.key = api_key or os.environ.get("ODDS_API_KEY")
        if not self.key:
            raise RuntimeError(
                "ODDS_API_KEY not set. Player props require a paid tier; "
                "there is no free path to this data.")
        self.timeout = timeout
        self.credits_remaining: int | None = None

    def _get(self, path: str, **params):
        params["apiKey"] = self.key
        r = requests.get(f"{BASE}{path}", params=params, timeout=self.timeout)
        self.credits_remaining = int(r.headers.get("x-requests-remaining", -1))
        if r.status_code == 401:
            raise RuntimeError("Odds API rejected the key (401).")
        if r.status_code == 422:
            raise RuntimeError(f"Odds API 422 - market likely not on your plan: {r.text[:200]}")
        r.raise_for_status()
        return r.json()

    def events(self):
        return self._get(f"/sports/{SPORT}/events")

    def props_for_event(self, event_id: str, markets=None, regions="us",
                        odds_format="american") -> list[PropQuote]:
        markets = markets or MARKETS
        data = self._get(f"/sports/{SPORT}/events/{event_id}/odds",
                         regions=regions, markets=",".join(markets),
                         oddsFormat=odds_format)
        out: list[PropQuote] = []
        for bm in data.get("bookmakers", []):
            for mk in bm.get("markets", []):
                by_player: dict[tuple[str, float], dict] = {}
                for oc in mk.get("outcomes", []):
                    name = oc.get("description") or oc.get("name")
                    pt = oc.get("point")
                    if name is None or pt is None:
                        continue
                    slot = by_player.setdefault((name, float(pt)), {})
                    slot[oc["name"].lower()] = float(oc["price"])
                for (player, pt), sides in by_player.items():
                    if "over" not in sides:
                        continue
                    out.append(PropQuote(
                        event_id=data["id"], commence_time=data["commence_time"],
                        book=bm["key"], player=player, market=mk["key"],
                        line=pt, over_odds=sides["over"],
                        under_odds=sides.get("under")))
        return out

    def slate(self, markets=None, sleep: float = 0.25) -> list[PropQuote]:
        quotes = []
        for ev in self.events():
            try:
                quotes.extend(self.props_for_event(ev["id"], markets))
            except Exception as e:  # one bad event should not kill the slate
                print(f"  [odds] {ev.get('id')}: {e}")
            time.sleep(sleep)
        return quotes


def no_vig_consensus(quotes: list[PropQuote], prefer=SHARP_BOOKS) -> dict:
    """De-vig each two-sided quote, then average across books at the modal
    line, weighting sharp books more heavily. Returns
    {(player, market, line): {"p_over": float, "n_books": int, "best_over": ...}}"""
    from collections import defaultdict
    import numpy as np
    from model import devig_two_way, american_to_decimal

    buckets = defaultdict(list)
    for q in quotes:
        if q.under_odds is None:
            continue
        p_over, _ = devig_two_way(q.over_odds, q.under_odds)
        w = 3.0 if q.book in prefer else 1.0
        buckets[(q.player, q.market, q.line)].append((p_over, w, q))

    out = {}
    for key, rows in buckets.items():
        ps = np.array([r[0] for r in rows])
        ws = np.array([r[1] for r in rows])
        best_over = max(rows, key=lambda r: american_to_decimal(r[2].over_odds))[2]
        best_under = max(rows, key=lambda r: american_to_decimal(
            r[2].under_odds if r[2].under_odds else -100000))[2]
        out[key] = {
            "p_over": float(np.average(ps, weights=ws)),
            "n_books": len(rows),
            "best_over_odds": best_over.over_odds, "best_over_book": best_over.book,
            "best_under_odds": best_under.under_odds, "best_under_book": best_under.book,
        }
    return out
