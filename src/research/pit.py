"""Probability Integral Transform (PIT) Diagnostics.

Evaluates whether the distributional shape (compound Negative Binomial / Gamma)
is properly calibrated across the entire outcome support using randomized PIT
and uniformity goodness-of-fit testing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class PITDiagnosticReport:
    n_samples: int
    market: str
    ks_statistic: float
    ks_pvalue: float
    chisq_statistic: float
    chisq_pvalue: float
    is_uniform_at_05: bool
    decile_counts: list[int]
    decile_frequencies: list[float]
    shape_diagnosis: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_randomized_pit_discrete(
    actuals: Sequence[int],
    cdf_fn: Any,  # function(y, **params) -> P(Y <= y)
    params_list: Sequence[dict[str, Any]],
    *,
    seed: int = 42,
) -> np.ndarray:
    """Compute randomized PIT for discrete integer counts."""
    rng = np.random.default_rng(seed)
    u_vals = np.empty(len(actuals), dtype=np.float64)
    for i, (y, params) in enumerate(zip(actuals, params_list)):
        y = int(y)
        f_y = float(cdf_fn(y, **params))
        f_prev = float(cdf_fn(y - 1, **params)) if y > 0 else 0.0
        v = rng.uniform(0.0, 1.0)
        u = f_prev + v * (f_y - f_prev)
        u_vals[i] = max(0.0, min(1.0, u))
    return u_vals


def compute_pit_continuous(
    actuals: Sequence[float],
    cdf_fn: Any,  # function(y, **params) -> P(Y <= y)
    params_list: Sequence[dict[str, Any]],
) -> np.ndarray:
    """Compute standard continuous PIT."""
    u_vals = np.empty(len(actuals), dtype=np.float64)
    for i, (y, params) in enumerate(zip(actuals, params_list)):
        u = float(cdf_fn(float(y), **params))
        u_vals[i] = max(0.0, min(1.0, u))
    return u_vals


def evaluate_pit_uniformity(
    u_values: np.ndarray,
    *,
    market: str = "receiving_yards",
) -> PITDiagnosticReport:
    """Evaluate PIT sample against Uniform(0, 1) and diagnose tail misspecification."""
    n = len(u_values)
    if n == 0:
        return PITDiagnosticReport(
            n_samples=0,
            market=market,
            ks_statistic=1.0,
            ks_pvalue=0.0,
            chisq_statistic=0.0,
            chisq_pvalue=0.0,
            is_uniform_at_05=False,
            decile_counts=[0] * 10,
            decile_frequencies=[0.0] * 10,
            shape_diagnosis="INSUFFICIENT_SAMPLE",
        )

    # 1. Kolmogorov-Smirnov test against uniform
    ks_res = stats.kstest(u_values, "uniform")
    ks_stat = float(ks_res.statistic)
    ks_p = float(ks_res.pvalue)

    # 2. 10-decile histogram
    bins = np.linspace(0.0, 1.0, 11)
    counts, _ = np.histogram(u_values, bins=bins)
    freqs = counts / n

    # 3. Chi-square goodness-of-fit against expected uniform (10% per bin)
    expected = np.full(10, n / 10.0)
    chisq_stat, chisq_p = stats.chisquare(counts, f_exp=expected)

    # 4. Shape diagnosis
    tails_excess = (freqs[0] + freqs[-1]) - 0.20
    center_excess = (freqs[4] + freqs[5]) - 0.20

    if ks_p > 0.05:
        diagnosis = "CALIBRATED_UNIFORM_SHAPE"
    elif tails_excess > 0.08:
        diagnosis = "UNDERDISPERSED_LIGHT_TAILS (outcomes fall in extremes more than modeled)"
    elif center_excess > 0.08:
        diagnosis = "OVERDISPERSED_HEAVY_TAILS (outcomes bunch in center more than modeled)"
    elif freqs[0] > 0.20:
        diagnosis = "RIGHT_SKEWED_OVERESTIMATION (excessive low realized values)"
    elif freqs[-1] > 0.20:
        diagnosis = "LEFT_SKEWED_UNDERESTIMATION (excessive high realized values)"
    else:
        diagnosis = "MODERATE_SHAPE_DEFECT"

    return PITDiagnosticReport(
        n_samples=n,
        market=market,
        ks_statistic=round(ks_stat, 5),
        ks_pvalue=round(float(ks_p), 5),
        chisq_statistic=round(float(chisq_stat), 3),
        chisq_pvalue=round(float(chisq_p), 5),
        is_uniform_at_05=bool(ks_p > 0.05),
        decile_counts=counts.tolist(),
        decile_frequencies=[round(float(f), 4) for f in freqs],
        shape_diagnosis=diagnosis,
    )
