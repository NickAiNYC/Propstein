"""Paired market-relative evaluation and copycat diagnostics.

Evaluates model predictions against the de-vigged closing consensus on the exact
same outcomes using paired Brier scoring and cluster-robust bootstrapping.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True)
class PairedMarketComparison:
    n_pairs: int
    brier_model: float
    brier_market: float
    paired_diff: float  # model - market; negative = model better than market
    paired_diff_ci95: tuple[float, float]  # cluster bootstrap over event_id
    median_abs_gap_pts: float  # median |p_model - p_market| in percentage points
    corr_model_market: float  # Pearson correlation (copycat diagnostic)
    n_events: int
    is_copycat: bool  # True if corr_model_market > 0.99
    paired_win_rate: float  # fraction of pairs where model had smaller Brier loss than market

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_paired_market_comparison(
    observations: Sequence[dict[str, Any]],
    *,
    n_boot: int = 1000,
    seed: int = 42,
) -> PairedMarketComparison:
    """Compute paired market-relative Brier difference with event-clustered bootstrap.

    Each observation dict must supply:
      - p_model: float in [0, 1]
      - p_market: float in [0, 1] (de-vigged market consensus probability)
      - outcome: int or float (1 for hit, 0 for miss)
      - event_id: str (clustering key, e.g. game_id)
    """
    valid: list[tuple[float, float, float, str]] = []
    for obs in observations:
        pm = obs.get("p_model")
        pk = obs.get("p_market")
        y = obs.get("outcome")
        ev = obs.get("event_id")
        if (
            isinstance(pm, (int, float))
            and isinstance(pk, (int, float))
            and isinstance(y, (int, float))
            and isinstance(ev, str)
            and ev.strip()
            and not math.isnan(pm)
            and not math.isnan(pk)
            and not math.isnan(y)
        ):
            pm = max(0.0, min(1.0, float(pm)))
            pk = max(0.0, min(1.0, float(pk)))
            y = 1.0 if float(y) > 0.5 else 0.0
            valid.append((pm, pk, y, ev.strip()))

    n_pairs = len(valid)
    if n_pairs == 0:
        return PairedMarketComparison(
            n_pairs=0,
            brier_model=0.0,
            brier_market=0.0,
            paired_diff=0.0,
            paired_diff_ci95=(0.0, 0.0),
            median_abs_gap_pts=0.0,
            corr_model_market=0.0,
            n_events=0,
            is_copycat=False,
            paired_win_rate=0.0,
        )

    p_model = np.array([v[0] for v in valid], dtype=np.float64)
    p_market = np.array([v[1] for v in valid], dtype=np.float64)
    y = np.array([v[2] for v in valid], dtype=np.float64)
    events = np.array([v[3] for v in valid])

    loss_model = (p_model - y) ** 2
    loss_market = (p_market - y) ** 2
    diffs = loss_model - loss_market  # negative = model better

    brier_model = float(np.mean(loss_model))
    brier_market = float(np.mean(loss_market))
    paired_diff = float(np.mean(diffs))

    # Median absolute gap in probability percentage points
    abs_gap = np.abs(p_model - p_market) * 100.0
    median_abs_gap_pts = float(np.median(abs_gap))

    # Correlation between model and market implied probability
    if np.std(p_model) > 1e-9 and np.std(p_market) > 1e-9:
        corr_matrix = np.corrcoef(p_model, p_market)
        corr_model_market = float(corr_matrix[0, 1])
    else:
        corr_model_market = 1.0 if np.allclose(p_model, p_market, atol=1e-3) else 0.0

    is_copycat = bool(corr_model_market > 0.99)
    paired_wins = np.sum(loss_model < loss_market)
    paired_win_rate = float(paired_wins / n_pairs)

    # Event clustering for bootstrap confidence interval
    unique_events = np.unique(events)
    n_events = len(unique_events)

    if n_events <= 1:
        ci95 = (paired_diff, paired_diff)
    else:
        rng = np.random.default_rng(seed)
        event_indices: dict[str, list[int]] = {}
        for idx, ev in enumerate(events):
            event_indices.setdefault(ev, []).append(idx)

        boot_diffs = np.empty(n_boot, dtype=np.float64)
        for b in range(n_boot):
            sampled_clusters = rng.choice(unique_events, size=n_events, replace=True)
            sampled_idx: list[int] = []
            for ev in sampled_clusters:
                sampled_idx.extend(event_indices[ev])
            boot_diffs[b] = np.mean(diffs[sampled_idx])

        ci_lower = float(np.percentile(boot_diffs, 2.5))
        ci_upper = float(np.percentile(boot_diffs, 97.5))
        ci95 = (round(ci_lower, 6), round(ci_upper, 6))

    return PairedMarketComparison(
        n_pairs=n_pairs,
        brier_model=round(brier_model, 6),
        brier_market=round(brier_market, 6),
        paired_diff=round(paired_diff, 6),
        paired_diff_ci95=ci95,
        median_abs_gap_pts=round(median_abs_gap_pts, 3),
        corr_model_market=round(corr_model_market, 4),
        n_events=n_events,
        is_copycat=is_copycat,
        paired_win_rate=round(paired_win_rate, 4),
    )
