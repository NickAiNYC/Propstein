"""Decomposed CLV Attribution Engine.

Decomposes total Closing Line Value into:
1. Line Value (beating the number / spread movement)
2. Price Value (beating the juice / vig at the given line)
3. Timing Value (early market entry vs. last-minute noise)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class DecomposedSignalCLV:
    signal_id: str
    total_clv_pp: float
    line_value_pp: float
    price_value_pp: float
    hours_before_close: float
    timing_attributed_pp: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CohortDecompositionSummary:
    n_signals: int
    mean_total_clv_pp: float
    mean_line_value_pp: float
    mean_price_value_pp: float
    mean_timing_value_pp: float
    line_beat_rate: float
    price_beat_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def decompose_single_clv(
    signal_id: str,
    *,
    entry_line: float,
    close_line: float,
    entry_implied_prob: float,
    close_devig_prob: float,
    side: str = "OVER",
    hours_before_close: float = 2.0,
    line_sensitivity_pp_per_unit: float = 2.5,  # ~2.5 pp probability change per yard
) -> DecomposedSignalCLV:
    """Decompose CLV for one graded signal into line, price, and timing components."""
    side_mult = 1.0 if str(side).upper() == "OVER" else -1.0
    line_delta = (close_line - entry_line) * side_mult

    total_clv_pp = (close_devig_prob - entry_implied_prob) * 100.0

    # Line movement value
    line_val_pp = line_delta * line_sensitivity_pp_per_unit

    # Price value is total minus line shift
    price_val_pp = total_clv_pp - line_val_pp

    # Timing attribution: early entries (> 4h) capture early bookmaker unhedged variance
    h = max(0.0, float(hours_before_close))
    timing_factor = min(1.0, h / 12.0)
    timing_attributed = round(total_clv_pp * timing_factor * 0.25, 4)

    return DecomposedSignalCLV(
        signal_id=signal_id,
        total_clv_pp=round(total_clv_pp, 4),
        line_value_pp=round(line_val_pp, 4),
        price_value_pp=round(price_val_pp, 4),
        hours_before_close=round(h, 2),
        timing_attributed_pp=timing_attributed,
    )


def summarize_cohort_decomposition(
    decomposed_signals: Sequence[DecomposedSignalCLV],
) -> CohortDecompositionSummary:
    """Aggregate decomposed components across an entire cohort."""
    n = len(decomposed_signals)
    if n == 0:
        return CohortDecompositionSummary(
            n_signals=0,
            mean_total_clv_pp=0.0,
            mean_line_value_pp=0.0,
            mean_price_value_pp=0.0,
            mean_timing_value_pp=0.0,
            line_beat_rate=0.0,
            price_beat_rate=0.0,
        )

    mean_total = sum(s.total_clv_pp for s in decomposed_signals) / n
    mean_line = sum(s.line_value_pp for s in decomposed_signals) / n
    mean_price = sum(s.price_value_pp for s in decomposed_signals) / n
    mean_timing = sum(s.timing_attributed_pp for s in decomposed_signals) / n

    line_beats = sum(1 for s in decomposed_signals if s.line_value_pp > 0.0)
    price_beats = sum(1 for s in decomposed_signals if s.price_value_pp > 0.0)

    return CohortDecompositionSummary(
        n_signals=n,
        mean_total_clv_pp=round(mean_total, 4),
        mean_line_value_pp=round(mean_line, 4),
        mean_price_value_pp=round(mean_price, 4),
        mean_timing_value_pp=round(mean_timing, 4),
        line_beat_rate=round(line_beats / n, 4),
        price_beat_rate=round(price_beats / n, 4),
    )

