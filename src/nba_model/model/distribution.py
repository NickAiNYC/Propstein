"""PointsDistribution — predictive distribution for NBA game points.

v1 shape: discretized Gaussian with explicit integer handling. Points are
integer-valued (2s, 3s, 1s), so with continuity correction:

  P(X = k) ≈ P(k - 0.5 < N < k + 0.5),   N ~ Normal(mean, sd)

  "over line L"  ⇔  X ≥ floor(L) + 1  ⇔  N > floor(L) + 0.5
  integer L:     P(push) = P(X = L) = Φ((L+0.5-μ)/σ) - Φ((L-0.5-μ)/σ)

A DNP mass (rest / late scratch) sits at 0 points: it can never land over
a publishable line, so it rescales the over/push tails by (1 - dnp_prob).

HONESTY NOTE: the Gaussian shape is a v1 approximation documented as such;
the calibration gate (eval/calibration.py) is what decides whether this
shape is allowed to publish. Until that gate passes, everything is
UNCALIBRATED and the board refuses ranked plays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

from ..config import SD_FLOOR_PTS


def american_to_prob(odds: float) -> float:
    """Implied probability INCLUDING vig."""
    odds = float(odds)
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


@dataclass
class PointsDistribution:
    mean: float
    sd: float
    dnp_prob: float = 0.0

    def __post_init__(self):
        if not (math.isfinite(self.mean) and math.isfinite(self.sd)):
            raise ValueError(f"non-finite distribution params: mean={self.mean}, sd={self.sd}")
        if self.sd < SD_FLOOR_PTS:
            self.sd = SD_FLOOR_PTS
        if not (0.0 <= self.dnp_prob <= 1.0):
            raise ValueError(f"dnp_prob out of range: {self.dnp_prob}")
        if self.mean < 0:
            raise ValueError(f"negative mean: {self.mean}")

    # ── tails ───────────────────────────────────────────────────────────────
    def _over_threshold(self, line: float) -> float:
        """N-threshold t with P(over) = P(N > t) = P(X ≥ floor(line)+1)."""
        return math.floor(line + 1e-9) + 0.5

    def p_over(self, line: float) -> float:
        """P(scored points strictly greater than `line`)."""
        if line < 0:
            return 1.0  # even a DNP's 0 points clears a negative line
        t = self._over_threshold(line)
        p = float(stats.norm.sf((t - self.mean) / self.sd))
        return p * (1.0 - self.dnp_prob)

    def p_push(self, line: float) -> float:
        """P(score exactly `line`) — non-zero only for integer lines."""
        if abs(line - round(line)) > 1e-9:
            return 0.0
        line = round(line)
        hi = stats.norm.cdf((line + 0.5 - self.mean) / self.sd)
        lo = stats.norm.cdf((line - 0.5 - self.mean) / self.sd)
        return float(hi - lo) * (1.0 - self.dnp_prob)

    def p_under(self, line: float) -> float:
        """P(scored points strictly less than `line`).

        NOTE: a DNP's 0 points is NOT under a 0 line (0 < 0 is false), so
        the DNP mass only enters the under tail for lines > 0."""
        if line <= 0:
            return 0.0
        p_over, p_push = self.p_over(line), self.p_push(line)
        return max(0.0, (1.0 - self.dnp_prob) - p_over - p_push) + self.dnp_prob

    # ── fair price ──────────────────────────────────────────────────────────
    def fair_line(self) -> float:
        """Line at which the over is approximately a coin flip.

        For integer-scored points an exact 50/50 line usually does not exist
        on the book grid, so this is the nearest half-point line to the
        median (the normal mean). Documented approximation, not a promise."""
        return round(self.mean * 2.0) / 2.0

    def prob_to_american(self, p: float, vig: float = 0.0) -> int:
        """Fair probability -> American price at an optional total-hold vig.
        p = 0.5 posts as -100 (favourite convention)."""
        p = min(max(p, 1e-4), 1.0 - 1e-4)
        posted = min(max(p * (1 + vig / 2.0), 1e-4), 0.9999)
        dec = 1.0 / posted
        if dec > 2.0:
            return int(round((dec - 1) * 100.0))
        return int(round(-100.0 / (dec - 1)))
