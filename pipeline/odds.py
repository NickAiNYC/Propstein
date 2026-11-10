"""PropStein pipeline — odds mathematics (parity with src/lib/domain/odds.ts)."""

from __future__ import annotations

from fractions import Fraction


def implied_probability(american_odds: int) -> float:
    """Break-even probability implied by American odds."""
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    if american_odds < 0:
        return (-american_odds) / (-american_odds + 100.0)
    raise ValueError("american odds must be non-zero")


def break_even_probability(american_odds: int) -> float:
    """Alias with the charter's hurdle vocabulary (parity with odds.ts)."""
    return implied_probability(american_odds)


def american_from_probability(p: float) -> int:
    """American odds for a raw (juiced) probability — mirrors sim-market.ts."""
    clamp = min(0.97, max(0.03, p))
    if clamp >= 0.5:
        return -round((100.0 * clamp) / (1.0 - clamp))
    return round((100.0 * (1.0 - clamp)) / clamp)


def devig_two_way(over_odds: int, under_odds: int) -> tuple[float, float]:
    """Two-way proportional devig: raw probabilities renormalized to sum to 1."""
    p_over = implied_probability(over_odds)
    p_under = implied_probability(under_odds)
    total = p_over + p_under
    if total <= 0:
        raise ValueError("degenerate two-way quote")
    return p_over / total, p_under / total


def fair_probability_for_side(over_odds: int, under_odds: int, selection: str) -> float:
    p_over, p_under = devig_two_way(over_odds, under_odds)
    return p_over if selection == "over" else p_under


def vig_fraction(over_odds: int, under_odds: int) -> float:
    """Total book margin as a fraction of the true pool."""
    p_over = implied_probability(over_odds)
    p_under = implied_probability(under_odds)
    return p_over + p_under - 1.0


def exact_implied_probability(american_odds: int) -> Fraction:
    """Exact rational implied probability (for test assertions)."""
    if american_odds > 0:
        return Fraction(100, american_odds + 100)
    return Fraction(-american_odds, -american_odds + 100)
