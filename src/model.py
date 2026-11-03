"""
Distributional models for receiving props.

Why a full distribution and not a point estimate:

A point estimate can only answer "is the projection above the line". That is
useless for alternate lines and actively dangerous for parlays, because both
depend on the SHAPE of the tail, not the mean. This module produces a proper
predictive distribution so that P(over L) is well defined at ANY L, and so
that receptions and yards can be sampled jointly with their real correlation.

Receptions:
    N ~ NegBin(mu_n, alpha)              mu_n from a NB2 GLM

Receiving yards (compound, not a normal approximation):
    Y | N = n ~ Gamma(shape = n*k, scale = mu_ypr / k),   Y | N = 0 = 0
    where mu_ypr comes from a Gamma GLM on yards-per-reception and k is the
    per-catch shape estimated from residual dispersion.

The compound form matters. Receiving yards has a point mass at zero, is
strongly right-skewed, and its variance grows with the mean. A Gaussian model
mis-prices every tail, which is precisely where alt lines and parlay legs live.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

try:
    from src.features import FEATURES
except ImportError:
    from features import FEATURES


# ----------------------------------------------------------------------------

def _design(df: pd.DataFrame, cols: list[str], means=None, sds=None):
    X = df[cols].astype(float).values
    if means is None:
        means, sds = X.mean(axis=0), X.std(axis=0)
        sds = np.where(sds < 1e-8, 1.0, sds)
    Xs = (X - means) / sds
    return sm.add_constant(Xs, has_constant="add"), means, sds


def _estimate_nb_alpha(y: np.ndarray, mu: np.ndarray) -> float:
    """Method-of-moments dispersion for NB2: Var = mu + alpha*mu^2."""
    resid = (y - mu) ** 2 - mu
    denom = (mu ** 2).sum()
    return float(max(resid.sum() / max(denom, 1e-9), 1e-3))


@dataclass
class ReceivingModel:
    rec_params: np.ndarray
    ypr_params: np.ndarray
    alpha: float           # NB dispersion for receptions
    k: float               # Gamma shape per reception
    means: np.ndarray
    sds: np.ndarray
    cols: list[str]

    # ---------------- fitting ----------------

    @classmethod
    def fit(cls, train: pd.DataFrame, cols: list[str] | None = None) -> "ReceivingModel":
        cols = cols or FEATURES
        X, means, sds = _design(train, cols)

        # --- receptions: Poisson fit for stable start, then NB2 ---
        pois = sm.GLM(train.receptions.values, X, family=sm.families.Poisson()).fit()
        alpha = _estimate_nb_alpha(train.receptions.values, pois.fittedvalues)
        nb = sm.GLM(train.receptions.values, X,
                    family=sm.families.NegativeBinomial(alpha=alpha)).fit()
        alpha = _estimate_nb_alpha(train.receptions.values, nb.fittedvalues)

        # --- yards per reception: Gamma GLM, weighted by receptions ---
        m = train.receptions.values > 0
        ypr = train.receiving_yards.values[m] / train.receptions.values[m]
        ypr = np.clip(ypr, 0.1, None)
        Xy = X[m]
        gam = sm.GLM(ypr, Xy, family=sm.families.Gamma(sm.families.links.Log()),
                     freq_weights=train.receptions.values[m]).fit()

        # Per-catch Gamma shape k from residual dispersion of game-level YPR.
        # Var(YPR_game) = mu^2 / (k * n)  =>  k = mu^2 / (n * Var)
        mu_hat = gam.fittedvalues
        n = train.receptions.values[m]
        disp = ((ypr - mu_hat) ** 2) * n / np.maximum(mu_hat ** 2, 1e-9)
        k = float(np.clip(1.0 / max(np.median(disp) / 0.4549, 1e-3), 0.2, 6.0))
        # (0.4549 = median of chi2_1 / 1, converting a median-based dispersion
        #  estimate to a mean-scale one; robust to the long YPR tail.)

        return cls(nb.params, gam.params, alpha, k, means, sds, cols)

    # ---------------- prediction ----------------

    def predict_params(self, df: pd.DataFrame) -> pd.DataFrame:
        X, _, _ = _design(df, self.cols, self.means, self.sds)
        mu_n = np.exp(np.clip(X @ self.rec_params, -6, 4))
        mu_ypr = np.exp(np.clip(X @ self.ypr_params, -2, 4.2))
        return pd.DataFrame({"mu_rec": mu_n, "mu_ypr": mu_ypr}, index=df.index)

    # -- receptions distribution --

    def _nb_rv(self, mu: float):
        r = 1.0 / self.alpha
        p = r / (r + mu)
        return stats.nbinom(r, p)

    def p_rec_over(self, mu_rec: float, line: float) -> float:
        """P(receptions > line). Half-point lines have no push; whole numbers do."""
        rv = self._nb_rv(mu_rec)
        return float(rv.sf(np.floor(line)))

    def p_rec_push(self, mu_rec: float, line: float) -> float:
        if abs(line - round(line)) > 1e-9:
            return 0.0
        return float(self._nb_rv(mu_rec).pmf(int(round(line))))

    # -- yards distribution (compound) --

    def p_yards_over(self, mu_rec: float, mu_ypr: float, line: float,
                     n_max: int | None = None) -> float:
        """Exact tail of the compound NB-Gamma: sum over reception counts."""
        rv = self._nb_rv(mu_rec)
        if n_max is None:
            n_max = int(max(20, rv.ppf(0.99995) + 5))
        ns = np.arange(1, n_max + 1)
        pn = rv.pmf(ns)
        scale = mu_ypr / self.k
        sf = stats.gamma.sf(line, a=ns * self.k, scale=scale)
        return float(np.dot(pn, sf))

    def yards_quantile(self, mu_rec: float, mu_ypr: float, q: float) -> float:
        lo, hi = 0.0, 400.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.p_yards_over(mu_rec, mu_ypr, mid) > (1 - q):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    # -- vectorised batch versions (the row-wise ones above are for clarity) --

    def p_rec_over_vec(self, mu_rec: np.ndarray, lines: np.ndarray) -> np.ndarray:
        r = 1.0 / self.alpha
        p = r / (r + np.asarray(mu_rec, float))
        return stats.nbinom.sf(np.floor(lines), r, p)

    def p_yards_over_vec(self, mu_rec: np.ndarray, mu_ypr: np.ndarray,
                         lines: np.ndarray, n_max: int = 36) -> np.ndarray:
        """Same compound sum as p_yards_over, evaluated for every row at once
        on a shared reception grid. n_max=36 prevents tail truncation even for
        elite target-earners with mu_rec ~ 10."""
        mu_rec = np.asarray(mu_rec, float)
        mu_ypr = np.asarray(mu_ypr, float)
        lines = np.asarray(lines, float)
        r = 1.0 / self.alpha
        p = r / (r + mu_rec)
        ns = np.arange(1, n_max + 1)
        pn = stats.nbinom.pmf(ns[None, :], r, p[:, None])          # (rows, n)
        scale = (mu_ypr / self.k)[:, None]
        sf = stats.gamma.sf(lines[:, None], a=(ns * self.k)[None, :], scale=scale)
        return (pn * sf).sum(axis=1)

    def yards_quantile_vec(self, mu_rec: np.ndarray, mu_ypr: np.ndarray,
                           q: float, iters: int = 28) -> np.ndarray:
        mu_rec = np.asarray(mu_rec, float)
        lo = np.zeros_like(mu_rec)
        hi = np.full_like(mu_rec, 400.0)
        for _ in range(iters):
            mid = (lo + hi) / 2
            over = self.p_yards_over_vec(mu_rec, mu_ypr, mid, n_max=36) > (1 - q)
            lo = np.where(over, mid, lo)
            hi = np.where(over, hi, mid)
        return (lo + hi) / 2

    # -- joint sampling, for parlays --

    def sample_joint(self, mu_rec: float, mu_ypr: float, size: int,
                     rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        r = 1.0 / self.alpha
        p = r / (r + mu_rec)
        n = rng.negative_binomial(r, p, size=size)
        scale = mu_ypr / self.k
        y = np.where(n > 0,
                     rng.gamma(shape=np.maximum(n, 1) * self.k, scale=scale, size=size),
                     0.0)
        return n, y


# ----------------------------------------------------------------------------
# Odds helpers
# ----------------------------------------------------------------------------

def american_to_prob(odds: float) -> float:
    """Implied probability INCLUDING vig."""
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def american_to_decimal(odds: float) -> float:
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def devig_two_way(over_odds: float, under_odds: float) -> tuple[float, float]:
    """Multiplicative de-vig. The de-vigged over price is the market's honest
    estimate; it is the number your model must beat, not the raw line."""
    po, pu = american_to_prob(over_odds), american_to_prob(under_odds)
    s = po + pu
    return po / s, pu / s


def ev_per_unit(p_win: float, odds: float, p_push: float = 0.0) -> float:
    d = american_to_decimal(odds)
    p_lose = max(1.0 - p_win - p_push, 0.0)
    return p_win * (d - 1.0) - p_lose


def kelly_fraction(p_win: float, odds: float, p_push: float = 0.0,
                   cap: float = 0.02) -> float:
    """Kelly, capped. The cap is not decoration: Kelly assumes your probability
    is correct, and a prop model's probability is an estimate with its own
    error. Full Kelly on an estimated edge is a fast route to ruin."""
    b = american_to_decimal(odds) - 1.0
    p = p_win / max(1.0 - p_push, 1e-9)
    q = 1.0 - p
    f = (b * p - q) / b
    return float(np.clip(f, 0.0, cap))


def prob_to_american(p: float | np.ndarray, vig: float = 0.045):
    """Convert a fair probability into a posted price with `vig` total hold
    split evenly across both sides. 4.5% is typical for a mainstream book's
    receiving props; sharper books run ~3%, recreational apps 6-8%."""
    p = np.asarray(p, float)
    p_posted = np.clip(p * (1 + vig / 2), 1e-4, 0.9999)
    dec = 1.0 / p_posted
    return np.where(dec >= 2.0, (dec - 1) * 100.0, -100.0 / (dec - 1))
