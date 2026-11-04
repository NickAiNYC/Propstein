"""Pre-Registered False Discovery Battery & FDR Control.

Enforces pre-registration of all tested model hypotheses, performs Benjamini-Hochberg
FDR correction across the battery, and simulates the Null Discovery Rate (NDR).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml


@dataclass(frozen=True)
class BatteryResult:
    battery_id: str
    battery_sha256: str
    n_variants_registered: int
    raw_p_values: dict[str, float]
    adjusted_q_values: dict[str, float]
    discoveries_raw: list[str]
    discoveries_fdr_corrected: list[str]
    null_discovery_rate_raw: float
    null_discovery_rate_fdr: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> list[tuple[float, bool]]:
    """Apply the Benjamini-Hochberg procedure to control False Discovery Rate.

    Returns list of tuples: (adjusted_q_value, is_significant) matching original order.
    """
    n = len(p_values)
    if n == 0:
        return []

    # Sort indices by p-value
    sorted_indices = sorted(range(n), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in sorted_indices]

    # Calculate adjusted p-values (q-values)
    # q_(i) = min(1.0, min_{j >= i} (n / j * p_(j)))
    q_sorted = [0.0] * n
    running_min = 1.0
    for rank in range(n, 0, -1):
        idx = rank - 1
        q_val = min(1.0, (n / rank) * sorted_p[idx])
        running_min = min(running_min, q_val)
        q_sorted[idx] = running_min

    # Map back to original order
    results = [0.0] * n
    for rank, orig_idx in enumerate(sorted_indices):
        results[orig_idx] = round(q_sorted[rank], 5)

    return [(q, q <= alpha) for q in results]


def run_null_world_simulation(
    n_variants: int,
    n_samples: int = 300,
    n_reps: int = 500,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Simulate battery testing on markets with ZERO edge.

    Returns (null_discovery_rate_raw, null_discovery_rate_fdr).
    """
    rng = np.random.default_rng(seed)
    raw_discoveries = 0
    fdr_discoveries = 0

    for _ in range(n_reps):
        # Generate K independent t-test / z-test p-values under pure null
        z_scores = rng.standard_normal(n_variants)
        # One-sided p-values: P(Z > z)
        from scipy import stats

        p_vals = [float(1.0 - stats.norm.cdf(z)) for z in z_scores]

        # Raw discovery: any single variant p < alpha
        if any(p < alpha for p in p_vals):
            raw_discoveries += 1

        # FDR corrected discovery
        bh_res = benjamini_hochberg(p_vals, alpha=alpha)
        if any(is_sig for _, is_sig in bh_res):
            fdr_discoveries += 1

    return (
        round(raw_discoveries / n_reps, 4),
        round(fdr_discoveries / n_reps, 4),
    )


def evaluate_battery(
    battery_yaml_path: Path,
    observed_p_values: dict[str, float],
    *,
    n_null_reps: int = 500,
) -> BatteryResult:
    """Evaluate observed variant p-values against the frozen registered battery."""
    raw_bytes = battery_yaml_path.read_bytes()
    file_sha = hashlib.sha256(raw_bytes).hexdigest()
    spec = yaml.safe_load(raw_bytes.decode("utf-8"))

    battery_id = str(spec.get("battery_id", "unnamed"))
    registered_variants = [v["id"] for v in spec.get("variants", [])]
    n_reg = len(registered_variants)
    alpha = float(spec.get("fdr_nominal_alpha", 0.05))

    p_list = [float(observed_p_values.get(vid, 1.0)) for vid in registered_variants]
    bh_results = benjamini_hochberg(p_list, alpha=alpha)

    adjusted_q: dict[str, float] = {}
    raw_disc: list[str] = []
    fdr_disc: list[str] = []

    for vid, p, (q, is_sig) in zip(registered_variants, p_list, bh_results):
        adjusted_q[vid] = q
        if p <= alpha:
            raw_disc.append(vid)
        if is_sig:
            fdr_disc.append(vid)

    ndr_raw, ndr_fdr = run_null_world_simulation(
        n_variants=n_reg,
        n_reps=n_null_reps,
        alpha=alpha,
    )

    return BatteryResult(
        battery_id=battery_id,
        battery_sha256=file_sha,
        n_variants_registered=n_reg,
        raw_p_values={vid: round(p, 5) for vid, p in zip(registered_variants, p_list)},
        adjusted_q_values=adjusted_q,
        discoveries_raw=raw_disc,
        discoveries_fdr_corrected=fdr_disc,
        null_discovery_rate_raw=ndr_raw,
        null_discovery_rate_fdr=ndr_fdr,
    )

