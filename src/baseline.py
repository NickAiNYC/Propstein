"""
A naive-but-honest line setter.

To test whether the full model has skill, we need a line that is FAIR - one
that lands near the median of the outcome distribution, the way a real book's
line does. A rolling MEAN is not that: receiving yards and receptions are
right-skewed, so a mean-based line goes under ~63% of the time and any model
that leans under looks spectacular for entirely spurious reasons.

So the proxy line is the MEDIAN of a deliberately impoverished model that sees
only a player's own recent form - no defence, no game total, no spread. Any
edge the full model shows against it is edge from the extra information,
which is the only thing worth measuring here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from model import ReceivingModel

NAIVE_FEATURES = ["f_rec", "f_yards", "f_ypr", "f_catch_rate", "f_targets",
                  "pos_TE", "pos_RB"]   # WR is the reference category


class BaselineLineSetter:
    """Fits the same distributional form on form-only features, then reports
    the median of the predictive distribution as the line."""

    def __init__(self, model: ReceivingModel):
        self.m = model

    @classmethod
    def fit(cls, train: pd.DataFrame) -> "BaselineLineSetter":
        return cls(ReceivingModel.fit(train, cols=NAIVE_FEATURES))

    def lines(self, test: pd.DataFrame) -> pd.DataFrame:
        p = self.m.predict_params(test)
        mu_r, mu_y = p.mu_rec.values, p.mu_ypr.values
        r = 1.0 / self.m.alpha
        pp = r / (r + mu_r)
        # Median of the NB, placed on the hook so there is no push.
        # Pick the half-point L with P(X > L) closest to 0.50.
        n = stats.nbinom.ppf(0.5, r, pp).astype(int)
        lo = np.maximum(n - 1, 0)
        sf_lo = stats.nbinom.sf(lo, r, pp)
        sf_hi = stats.nbinom.sf(n, r, pp)
        rec_line = np.where(np.abs(sf_lo - 0.5) < np.abs(sf_hi - 0.5), lo + 0.5, n + 0.5)
        yd_line = np.round(self.m.yards_quantile_vec(mu_r, mu_y, 0.5) * 2) / 2
        rec_line = np.maximum(rec_line, 0.5)
        yd_line = np.maximum(yd_line, 5.5)
        # The market's OWN honest probability at the line it posted. This is
        # what gets priced into the odds, so the full model must beat this
        # number rather than a flat 50%. Without it, a whole-number receptions
        # line looks like free money purely because of discreteness.
        return pd.DataFrame({
            "line_rec": rec_line,
            "line_yards": yd_line,
            "mkt_p_rec": self.m.p_rec_over_vec(mu_r, rec_line),
            "mkt_p_yards": self.m.p_yards_over_vec(mu_r, mu_y, yd_line),
        }, index=test.index)
