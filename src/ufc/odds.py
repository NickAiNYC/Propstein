"""The Odds API MMA odds (h2h + totals only - the only verified MMA markets,
see research/ufc-gate1/README.md §A). One region, one request per pull:
cost = markets x regions = 2 credits. Budget guard aborts before spending."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .common import consensus, names_match, no_vig_two_way

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "mma_mixed_martial_arts"
MARKETS = ("h2h", "totals")


class BudgetExceeded(RuntimeError):
    pass


class MeterMissing(RuntimeError):
    pass


def estimate_cost(markets=MARKETS, regions=("us",)) -> int:
    return len(markets) * len(regions)


def fetch_odds(api_key: str, start_iso: str, end_iso: str, max_credits: int = 4,
               region: str = "us", opener=urllib.request.urlopen) -> tuple[list, dict]:
    cost = estimate_cost(MARKETS, (region,))
    if cost > max_credits:
        raise BudgetExceeded(f"estimated {cost} credits > cap {max_credits}")
    q = urllib.parse.urlencode({
        "apiKey": api_key, "regions": region, "markets": ",".join(MARKETS),
        "oddsFormat": "american", "commenceTimeFrom": start_iso, "commenceTimeTo": end_iso,
    })
    with opener(f"{BASE_URL}/sports/{SPORT}/odds?{q}", timeout=30) as resp:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = json.load(resp)
    used_last = headers.get("x-requests-last")
    if used_last is None:
        raise MeterMissing("x-requests-last header missing - fail closed")
    meter = {"cost_measured": int(float(used_last)), "cost_estimated": cost,
             "remaining": headers.get("x-requests-remaining"), "used": headers.get("x-requests-used")}
    return body, meter


def match_event(card_fight: dict, events: list[dict]) -> Optional[dict]:
    a, b = (x["name"] for x in card_fight["fighters"])
    for ev in events:
        h, w = ev.get("home_team", ""), ev.get("away_team", "")
        if (names_match(a, h) and names_match(b, w)) or (names_match(a, w) and names_match(b, h)):
            return ev
    return None


def summarize_event(card_fight: dict, ev: dict) -> dict:
    """Per-fight market summary oriented to the card's fighter order."""
    a, b = (x["name"] for x in card_fight["fighters"])
    probs_a, best = [], [None, None]
    totals: dict[float, list] = {}
    books = []
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            outs = m.get("outcomes") or []
            if m.get("key") == "h2h" and len(outs) == 2:
                oa = next((o for o in outs if names_match(a, o["name"])), None)
                ob = next((o for o in outs if names_match(b, o["name"])), None)
                if not oa or not ob:
                    continue
                pa, _ = no_vig_two_way(oa["price"], ob["price"])
                probs_a.append(pa)
                books.append(bk["key"])
                for i, o in enumerate((oa, ob)):
                    if best[i] is None or o["price"] > best[i]["price"]:
                        best[i] = {"price": o["price"], "book": bk["key"]}
            elif m.get("key") == "totals":
                ov = next((o for o in outs if o["name"].lower() == "over"), None)
                un = next((o for o in outs if o["name"].lower() == "under"), None)
                if ov and un and ov.get("point") is not None:
                    po, _ = no_vig_two_way(ov["price"], un["price"])
                    totals.setdefault(float(ov["point"]), []).append(
                        {"book": bk["key"], "over": ov["price"], "under": un["price"], "p_over": po})
    pa = consensus(probs_a)
    tot = [{"line": ln, "p_over_novig": round(consensus(r["p_over"] for r in rows), 4),
            "books": rows} for ln, rows in sorted(totals.items())]
    return {"odds_event_id": ev.get("id"), "books": sorted(set(books)),
            "h2h_novig": [round(pa, 4), round(1 - pa, 4)] if pa is not None else None,
            "best": best, "totals": tot}
