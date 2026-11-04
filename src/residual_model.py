"""Residual-First Prop Pricing Architecture.

Inverts the traditional level-projection paradigm:
1. Treats the sharp de-vigged market consensus probability as the ground level.
2. Directly estimates the market residual error Delta p based on structural blindspots
   (band calibration curve, role/starter certainty, confirmed absence redistribution).
3. Regularizes Delta p with an L2 prior towards 0 so model uncertainty defaults
   fail-closed to market consensus rather than drifting into uncalibrated model errors.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class ResidualPrediction:
    p_market: float
    residual_delta: float
    p_final: float
    regularization_lambda: float
    band_adjustment: float
    role_adjustment: float
    absence_adjustment: float
    basis_attribution: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_probability_band(p: float) -> str:
    """Categorize probability into structural prop calibration bands."""
    p = max(0.0, min(1.0, float(p)))
    if p < 0.35:
        return "band_under_35"
    if p < 0.45:
        return "band_35_45"
    if p <= 0.55:
        return "band_neutral_50"
    if p <= 0.65:
        return "band_55_65"
    return "band_over_65"


# Empirical Market Calibration Dataset baseline tilts (in probability delta)
# Props have documented mean-reversion tilts in 35-45% and 55-65% bands
EMPIRICAL_BAND_TILT: Mapping[str, float] = {
    "band_under_35": -0.015,
    "band_35_45": -0.025,  # underdogs slightly overpriced by books
    "band_neutral_50": 0.000,
    "band_55_65": +0.025,   # favorites slightly underpriced by books
    "band_over_65": +0.015,
}


def predict_market_residual(
    p_market: float,
    *,
    is_starter: bool = True,
    target_share_trend: float = 0.0,  # e.g. +0.04 for trending up 4 pp
    teammate_vacated_targets: float = 0.0,  # target share vacated by out players
    regularization_lambda: float = 2.0,  # L2 shrinkage penalty toward 0
    max_abs_delta: float = 0.12,  # hard clamp on residual intervention
) -> ResidualPrediction:
    """Compute regularized residual correction Delta p over the market consensus."""
    p_mkt = max(0.01, min(0.99, float(p_market)))
    band = get_probability_band(p_mkt)

    # 1. Band-level calibration bias
    raw_band_adj = float(EMPIRICAL_BAND_TILT.get(band, 0.0))

    # 2. Role / minutes certainty adjustment
    # Bench players face high minute truncation risk -> negative residual on high lines
    if not is_starter:
        raw_role_adj = -0.040 if p_mkt > 0.45 else -0.015
    else:
        raw_role_adj = float(np.clip(target_share_trend * 0.5, -0.03, +0.03))

    # 3. Teammate absence shock (structural volume redistribution)
    # Vacated targets disproportionately benefit starting receivers
    raw_absence_adj = float(np.clip(teammate_vacated_targets * 0.35, 0.0, 0.05)) if is_starter else 0.0

    raw_sum = raw_band_adj + raw_role_adj + raw_absence_adj

    # Apply L2 shrinkage toward zero: delta = raw / (1 + lambda)
    reg_factor = 1.0 + max(0.0, float(regularization_lambda))
    shrunk_delta = raw_sum / reg_factor
    clamped_delta = float(np.clip(shrunk_delta, -max_abs_delta, max_abs_delta))

    # Calculate final calibrated probability
    p_final = float(np.clip(p_mkt + clamped_delta, 0.01, 0.99))

    band_adj = round(raw_band_adj / reg_factor, 4)
    role_adj = round(raw_role_adj / reg_factor, 4)
    abs_adj = round(raw_absence_adj / reg_factor, 4)

    basis = (
        f"Level anchored to market ({p_mkt:.3f}). "
        f"Residual correction ({clamped_delta:+.3f}): "
        f"band[{band}]={band_adj:+.3f}, role={role_adj:+.3f}, absence={abs_adj:+.3f} "
        f"(shrinkage reg={regularization_lambda:.1f})."
    )

    return ResidualPrediction(
        p_market=round(p_mkt, 4),
        residual_delta=round(clamped_delta, 4),
        p_final=round(p_final, 4),
        regularization_lambda=round(regularization_lambda, 2),
        band_adjustment=band_adj,
        role_adjustment=role_adj,
        absence_adjustment=abs_adj,
        basis_attribution=basis,
    )
