"""De-vig utilities — the market's honest probability, not its posted one.

Two methods:
  multiplicative  scale implied probs to sum to 1 (standard, slightly
                  overrates favourites on long prices)
  power (odds-ratio)  solve (p_o)^xi + (p_u)^xi = 1 (fairer tail behaviour)

The consensus across books uses the POWER method per book and averages —
power is the closer approximation for NBA points props where prices sit
in a modest range, and the difference is recorded in the play receipt.
"""

from __future__ import annotations

from typing import Iterable

from ..model.distribution import american_to_prob


def devig_multiplicative(over_odds: float, under_odds: float) -> tuple[float, float]:
    po, pu = american_to_prob(over_odds), american_to_prob(under_odds)
    s = po + pu
    if s <= 0:
        raise ValueError(f"degenerate odds pair: {over_odds}/{under_odds}")
    return po / s, pu / s


def devig_power(over_odds: float, under_odds: float) -> tuple[float, float]:
    """Odds-ratio (power) de-vig via bisection on xi."""
    po, pu = american_to_prob(over_odds), american_to_prob(under_odds)
    lo, hi = 0.01, 5.0
    for _ in range(80):
        xi = (lo + hi) / 2
        if po ** xi + pu ** xi > 1.0:
            lo = xi
        else:
            hi = xi
    xi = (lo + hi) / 2
    num_o, num_u = po ** xi, pu ** xi
    s = num_o + num_u
    return num_o / s, num_u / s


def group_quotes(
    quotes: Iterable[dict],
    market: str = "points",
) -> dict[tuple[str, float], list[dict]]:
    """Group quote rows by (player_id, line) for one market.

    Lines are matched EXACTLY — a 28.5 at one book is not the 28.0 at
    another. The independent-quote gate then counts distinct books per
    exact line. Stale or duplicate-source rows are NOT filtered here;
    gates own that decision.
    """
    grouped: dict[tuple[str, float], list[dict]] = {}
    for q in quotes or []:
        if str(q.get("market", market)) != market:
            continue
        player_id = q.get("player_id")
        line = q.get("line")
        if player_id is None or line is None:
            continue
        grouped.setdefault((player_id, float(line)), []).append(q)
    return grouped


def market_consensus(quote_group: list[dict]) -> dict | None:
    """De-vigged consensus for one (player_id, line) group of quotes."""
    rows = [q for q in quote_group if q.get("over_odds") is not None
            and q.get("under_odds") is not None]
    if not rows:
        return None
    p_overs, books, sources = [], [], []
    latest_obs = None
    for q in rows:
        p_o, _ = devig_power(q["over_odds"], q["under_odds"])
        p_overs.append(p_o)
        books.append(str(q.get("book")))
        sources.append(str(q.get("source", "")))
        obs = q.get("observed_at")
        if obs and (latest_obs is None or str(obs) > str(latest_obs)):
            latest_obs = obs
    return {
        "p_over": sum(p_overs) / len(p_overs),
        "p_over_min": min(p_overs),
        "p_over_max": max(p_overs),
        "books": books,
        "n_books": len(set(books)),
        "distinct_sources": len(set(sources)),
        "latest_observed_at": latest_obs,
        "quotes": rows,
    }
