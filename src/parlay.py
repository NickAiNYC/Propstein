"""
Alternate lines and parlays, priced correctly.

Two things people get wrong here, both expensive.

1) ALT LINES DO NOT CREATE EDGE.
   Taking "over 89.5 yards at +250" instead of "over 59.5 at -110" does not
   turn a small edge into a big one. The book prices the alt line off the same
   distribution you are modelling. What actually changes is that you move into
   the tail, where your model is LEAST reliable - tail probability is dominated
   by the Gamma shape parameter k, which is estimated from residual dispersion
   and is the shakiest number in the whole pipeline. A 10% error in the median
   is a 40%+ error in the 90th percentile. Longer odds concentrate your
   exposure exactly where your model is worst.

2) PARLAYS MULTIPLY EDGE, WHICH IS BAD IF YOUR EDGE IS UNCERTAIN.
   For independent legs with per-leg edge e, an n-leg parlay has edge
   (1+e)^n - 1 on a correctly-priced parlay - so parlays amplify a REAL edge.
   But they amplify estimation error by the same power, and books price
   parlays with per-leg hold, so the effective hold compounds too. At 4.5%
   hold per leg, a 4-leg parlay faces ~17% hold. You need a per-leg edge above
   roughly 4.5% just to break even before variance.

   Same-game parlays are worse. Receptions and receiving yards for the SAME
   player are strongly positively correlated - the sampler below measures it -
   and books apply a correlation adjustment that removes most of the value.
   Where they under-adjust there is real money, but that is a pricing-error
   hunt against a specific book's SGP engine, not a modelling exercise.

This module computes all of it honestly instead of assuming independence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from model import ReceivingModel, american_to_decimal, american_to_prob


@dataclass
class Leg:
    player: str
    market: str          # "receptions" | "receiving_yards"
    side: str            # "over" | "under"
    line: float
    odds: float
    mu_rec: float
    mu_ypr: float


class ParlayPricer:
    def __init__(self, model: ReceivingModel, n_sims: int = 200_000, seed: int = 7):
        self.m = model
        self.n = n_sims
        self.rng = np.random.default_rng(seed)

    def _leg_outcomes(self, leg: Leg, shared: dict) -> np.ndarray:
        """Draw (or reuse) this player's joint (receptions, yards) sample so
        that two legs on the same player share the same underlying game."""
        if leg.player not in shared:
            shared[leg.player] = self.m.sample_joint(
                leg.mu_rec, leg.mu_ypr, self.n, self.rng)
        n_rec, yards = shared[leg.player]
        val = n_rec if leg.market == "receptions" else yards
        return (val > leg.line) if leg.side == "over" else (val < leg.line)

    def price(self, legs: list[Leg]) -> dict:
        shared: dict = {}
        outcomes = np.stack([self._leg_outcomes(l, shared) for l in legs])

        p_joint = float(outcomes.all(axis=0).mean())
        p_indep = float(np.prod([o.mean() for o in outcomes]))

        dec = float(np.prod([american_to_decimal(l.odds) for l in legs]))
        ev = p_joint * (dec - 1) - (1 - p_joint)

        # What the book implies, and how much hold is stacked in.
        implied = 1.0 / dec
        per_leg_hold = [american_to_prob(l.odds) for l in legs]

        return {
            "n_legs": len(legs),
            "p_model_joint": p_joint,
            "p_model_independent": p_indep,
            "correlation_lift": p_joint / p_indep if p_indep > 0 else np.nan,
            "decimal_payout": dec,
            "implied_prob": implied,
            "ev_per_unit": ev,
            "stacked_hold": float(np.prod(per_leg_hold) / implied - 1.0),
        }

    def leg_correlation(self, mu_rec: float, mu_ypr: float,
                        rec_line: float, yd_line: float) -> float:
        """Phi coefficient between 'receptions over' and 'yards over' for the
        same player. This is the number an SGP engine has to price."""
        n, y = self.m.sample_joint(mu_rec, mu_ypr, self.n, self.rng)
        a = (n > rec_line).astype(float)
        b = (y > yd_line).astype(float)
        return float(np.corrcoef(a, b)[0, 1])


def breakeven_edge_for_parlay(n_legs: int, hold_per_leg: float = 0.045) -> float:
    """Minimum per-leg true edge needed for an n-leg parlay to break even."""
    return (1.0 / (1.0 - hold_per_leg)) ** 1.0 * ((1 + hold_per_leg) ** n_legs) ** (1 / n_legs) - 1
