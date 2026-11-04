"""Calibrated Hierarchical Shrinkage Engine.

Replaces fixed static shrinkage weights with Empirical Bayes hierarchical
shrinkage across player, position/role, and league levels based on observed
sample size and signal-to-noise ratio.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True)
class ShrinkageEstimate:
    segment: str
    sample_size: int
    raw_delta: float
    shrunk_delta: float
    shrinkage_weight: float  # w in [0, 1]; 0 = completely market, 1 = completely model
    prior_mean: float
    se_estimated: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_empirical_bayes_weight(
    sample_size: int,
    within_variance: float = 0.04,  # sigma^2 (sampling noise)
    between_variance: float = 0.01,  # tau^2 (true dispersion across players/segments)
) -> float:
    """Calculate James-Stein / Empirical Bayes weight w in [0.0, 1.0].

    w = tau^2 / (tau^2 + sigma^2 / n)
    """
    n = max(0, int(sample_size))
    if n == 0:
        return 0.0
    tau2 = max(1e-6, float(between_variance))
    sigma2 = max(1e-6, float(within_variance))
    se2 = sigma2 / n
    w = tau2 / (tau2 + se2)
    return float(np.clip(w, 0.0, 1.0))


def apply_hierarchical_shrinkage(
    player_delta: float,
    sample_size: int,
    *,
    position_prior_delta: float = 0.0,
    segment: str = "all",
    within_variance: float = 0.04,
    between_variance: float = 0.01,
) -> ShrinkageEstimate:
    """Shrink a player-level model delta toward the position/market prior.

    shrunk_delta = w * player_delta + (1 - w) * position_prior_delta
    """
    n = max(0, int(sample_size))
    w = calculate_empirical_bayes_weight(
        n, within_variance=within_variance, between_variance=between_variance
    )
    shrunk = w * player_delta + (1.0 - w) * position_prior_delta
    se = math.sqrt(within_variance / max(1, n))

    return ShrinkageEstimate(
        segment=segment,
        sample_size=n,
        raw_delta=round(float(player_delta), 5),
        shrunk_delta=round(float(shrunk), 5),
        shrinkage_weight=round(float(w), 4),
        prior_mean=round(float(position_prior_delta), 5),
        se_estimated=round(float(se), 5),
    )


def pool_segments(
    segments_data: Sequence[dict[str, Any]],
) -> dict[str, ShrinkageEstimate]:
    """Fit global between-segment variance tau^2 and return shrunk estimates."""
    if not segments_data:
        return {}

    deltas = [float(s.get("raw_delta", 0.0)) for s in segments_data]
    tau2 = float(np.var(deltas, ddof=1)) if len(deltas) > 1 else 0.01
    tau2 = max(0.001, tau2)

    results: dict[str, ShrinkageEstimate] = {}
    for s in segments_data:
        seg_name = str(s.get("segment", "unknown"))
        raw = float(s.get("raw_delta", 0.0))
        n = int(s.get("sample_size", 0))
        sigma2 = float(s.get("within_variance", 0.04))
        results[seg_name] = apply_hierarchical_shrinkage(
            raw,
            n,
            position_prior_delta=0.0,
            segment=seg_name,
            within_variance=sigma2,
            between_variance=tau2,
        )

    return results

