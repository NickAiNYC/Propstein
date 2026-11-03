"""Propstein 2.0 — expected-value math (mirrors src/lib/ev.ts).

American odds <-> decimal <-> implied probability, Gaussian tail model
probability, fair odds, EV and full-Kelly (quarter-cap 25%).
"""

import math

KELLY_CAP = 0.25

# sigma floors / coefficients of variation per market
_SIGMA_FLOOR = {
    "receptions": 1.4,
    "receiving_yards": 9.5,
    "yards": 9.5,
    "points": 4.5,
    "rebounds": 3.2,
    "assists": 2.6,
    "threes": 1.2,
}
_SIGMA_CV = {
    "receptions": 0.34,
    "receiving_yards": 0.26,
    "yards": 0.26,
    "points": 0.24,
    "rebounds": 0.28,
    "assists": 0.30,
    "threes": 0.42,
}


def american_to_decimal(american: float) -> float:
    # +150: stake 100 to win 150 -> 2.50 | -110: stake 110 to win 100 -> 1.909
    return 1 + american / 100 if american > 0 else 1 + 100 / abs(american)


def decimal_to_american(decimal: float) -> int:
    if decimal >= 2:
        return round(100 * (decimal - 1))
    return -round(100 / (decimal - 1))


def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def prob_over(fair_line: float, line: float, market: str) -> float:
    key = market if market in _SIGMA_FLOOR else ("receptions" if "rec" in market else market)
    floor = _SIGMA_FLOOR.get(key, 4.0)
    cv = _SIGMA_CV.get(key, 0.30)
    sigma = max(floor, cv * max(fair_line, 1))
    z = (fair_line - line - 0.25) / sigma
    return normal_cdf(z)


def compute_edge(fair_line: float, line: float, market: str, over_odds, under_odds) -> dict:
    """Edge for one quote. Returns dict matching the Prop model columns."""
    p_over = prob_over(fair_line, line, market)
    p_under = 1 - p_over
    over_dec = american_to_decimal(over_odds) if over_odds is not None else 1.909
    under_dec = american_to_decimal(under_odds) if under_odds is not None else 1.909
    ev_over = p_over * over_dec - 1
    ev_under = p_under * under_dec - 1
    best_side = "OVER" if ev_over >= ev_under else "UNDER"
    prob_win = p_over if best_side == "OVER" else p_under
    dec = over_dec if best_side == "OVER" else under_dec
    b = dec - 1
    fair_odds = decimal_to_american(1 / prob_win)
    ev = (prob_win * dec - 1) * 100
    kelly_raw = (prob_win * dec - 1) / b if b > 0 else 0.0
    kelly = max(0.0, min(KELLY_CAP, kelly_raw))
    lean = "WATCH" if (ev >= 2 and kelly > 0.005) else "PASS"
    return {
        "best_side": best_side,
        "prob_win": round(prob_win, 4),
        "fair_odds": fair_odds,
        "ev": round(ev, 2),
        "kelly": round(kelly, 4),
        "lean": lean,
    }
