"""Vig-adjusted value boundaries for public player pages.

The frozen snapshot fields ``max_acceptable_over_line_at_minus_110`` and
``min_acceptable_under_line_at_minus_110`` are the 10% edge qualification
screen (see ``evaluate_price_boundaries``). They are not the lines where the
model's win probability equals the -110 breakeven, and public pages must not
present them as that.

Breakeven at -110 with no push is ``1 / decimal(-110) = 110/210``.

Push handling is the one already used to freeze probabilities
(``compute_yards_probs`` / ``compute_rec_probs``):

* Receiving yards, non-integer line: push is 0. P(over) is the compound
  Negative-Binomial/Gamma survival and P(under) = 1 - P(over).
* Receiving yards, integer line L: push is the mass in (L-0.5, L+0.5],
  P(over) = P(Y > L+0.5), P(under) = P(Y <= L-0.5). That window is a single
  point on the line axis, so the breakeven *root* is solved on the continuous
  branch (push 0). Whole-number lines still use the window when a fair line
  is displayed.
* Receptions: the count is discrete. A whole-number line pushes on that exact
  count; a half-point line does not. P(over) is constant between integers, so
  the boundary is the step where the side crosses 110/210, not a brentq root.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from scipy.optimize import brentq

from src.freeze_slate import (
    compute_rec_probs,
    compute_yards_probs,
    prob_to_american,
)
from src.model import ReceivingModel, american_to_decimal

# 1 / decimal(-110) == 110/210.
MINUS_110_BREAKEVEN = 1.0 / american_to_decimal(-110)


@dataclass(frozen=True)
class VigBoundaries:
    """Exact breakeven roots, plus the lines printed on public pages.

    Display lines are the roots rounded to 0.1. On the continuous (non-integer)
    branch, P(over) is at least the -110 breakeven below ``over_line`` and
    P(under) is at least the breakeven above ``under_line``. A whole-number
    line uses the half-yard push window, so its win probability can sit a
    fraction under the breakeven even when the continuous root is nearby.
    """

    over_exact: float | None
    under_exact: float | None
    over_line: float | None
    under_line: float | None
    breakeven: float


@dataclass(frozen=True)
class FairLineDisplay:
    """Hundredths of a percent. The three shares sum to 10000 (100.00%)."""

    over_hundredths: int
    under_hundredths: int
    push_hundredths: int
    over_odds: str
    under_odds: str

    @property
    def sums_to_100(self) -> bool:
        return (
            self.over_hundredths + self.under_hundredths + self.push_hundredths
            == 10000
        )


def _is_yards(market: str) -> bool:
    return market in ("receiving_yards", "yards")


@lru_cache(maxsize=16)
def _model(alpha: float, k: float) -> ReceivingModel:
    return ReceivingModel(
        rec_params=None,
        ypr_params=None,
        alpha=float(alpha),
        k=float(k),
        means=None,
        sds=None,
        cols=None,
    )


def side_probabilities(
    market: str,
    mu_rec: float,
    mu_ypr: float,
    line: float,
    alpha: float = 0.1097,
    k: float = 1.555,
) -> tuple[float, float, float]:
    """P(over), P(under), P(push) at ``line``, including integer pushes."""
    if _is_yards(market):
        return compute_yards_probs(_model(alpha, k), float(mu_rec), float(mu_ypr), float(line))
    if market == "receptions":
        return compute_rec_probs(float(mu_rec), float(line), alpha=float(alpha))
    raise ValueError(f"unsupported market: {market}")


def _continuous_yards(
    alpha: float,
    k: float,
    mu_rec: float,
    mu_ypr: float,
    line: float,
) -> tuple[float, float, float]:
    """Non-integer branch of ``compute_yards_probs`` (push is identically 0).

    Whole-number evaluations are nudged off the integer so the breakeven root
    sees the continuous survival rather than the single-point push window.
    """
    line = float(line)
    if abs(line - round(line)) < 1e-8:
        line += 1e-6
    return compute_yards_probs(_model(alpha, k), mu_rec, mu_ypr, line)


def _solve(gap, lo: float, hi: float, *, increasing: bool) -> float | None:
    """Root of a monotone gap function on an expandable bracket."""
    flo = gap(lo)
    fhi = gap(hi)
    limit = 800.0
    if increasing and flo >= 0:
        # Already clearing at the floor of the bracket; the root is lower.
        hi, fhi = lo, flo
        lo = 0.0
        flo = gap(lo)
        if flo >= 0:
            return 0.0
    elif not increasing and flo <= 0:
        return None
    else:
        while hi < limit and ((increasing and fhi < 0) or (not increasing and fhi > 0)):
            hi = min(limit, hi * 1.5 + 5.0)
            fhi = gap(hi)
    if increasing and fhi < 0:
        return None
    if not increasing and fhi > 0:
        return None
    if abs(flo) <= 1e-12:
        return float(lo)
    if abs(fhi) <= 1e-12:
        return float(hi)
    if flo * fhi > 0:
        return None
    return float(brentq(gap, lo, hi, xtol=1e-7, rtol=1e-8))


def _yards_boundaries(
    mu_rec: float,
    mu_ypr: float,
    alpha: float,
    k: float,
    breakeven: float,
) -> tuple[float | None, float | None]:
    hi = max(80.0, float(mu_rec) * float(mu_ypr) * 4.0 + 40.0)

    def over_gap(line: float) -> float:
        return _continuous_yards(alpha, k, mu_rec, mu_ypr, line)[0] - breakeven

    def under_gap(line: float) -> float:
        return _continuous_yards(alpha, k, mu_rec, mu_ypr, line)[1] - breakeven

    return (
        _solve(over_gap, 0.05, hi, increasing=False),
        _solve(under_gap, 0.05, hi, increasing=True),
    )


def _receptions_boundaries(
    mu_rec: float,
    alpha: float,
    breakeven: float,
) -> tuple[float | None, float | None]:
    """Step where each side crosses breakeven.

    P(over) is constant on [n, n+1) and drops at n. Value on the over is at
    lines below the first integer where P(over) < breakeven.

    P(under) on (n, n+1] first clears breakeven at the half-point n+0.5.
    Value on the under is at lines above that n (the integer itself still
    pushes, so its under probability is the previous step).
    """
    over_exact = None
    under_exact = None
    for n in range(0, 81):
        p_over, _, _ = compute_rec_probs(mu_rec, float(n), alpha=alpha)
        if p_over < breakeven:
            over_exact = float(n)
            break
    for n in range(0, 81):
        _, p_under, _ = compute_rec_probs(mu_rec, n + 0.5, alpha=alpha)
        if p_under >= breakeven:
            under_exact = float(n)
            break
    return over_exact, under_exact


def round_tenth(x: float) -> float:
    """Round to 0.1, nudging off binary midpoints that are not true ties."""
    return round(float(x) + 1e-12, 1)


def vig_boundaries(
    market: str,
    mu_rec: float,
    mu_ypr: float = 0.0,
    alpha: float = 0.1097,
    k: float = 1.555,
    breakeven: float = MINUS_110_BREAKEVEN,
) -> VigBoundaries:
    """Over/under lines where the model's win probability equals -110 breakeven."""
    mu_rec = float(mu_rec)
    mu_ypr = float(mu_ypr)
    alpha = float(alpha)
    k = float(k)
    if _is_yards(market):
        over_exact, under_exact = _yards_boundaries(mu_rec, mu_ypr, alpha, k, breakeven)
    elif market == "receptions":
        over_exact, under_exact = _receptions_boundaries(mu_rec, alpha, breakeven)
    else:
        raise ValueError(f"unsupported market: {market}")
    over_line = round_tenth(over_exact) if over_exact is not None else None
    under_line = round_tenth(under_exact) if under_exact is not None else None
    return VigBoundaries(
        over_exact=over_exact,
        under_exact=under_exact,
        over_line=over_line,
        under_line=under_line,
        breakeven=float(breakeven),
    )


def percent_shares(probs: tuple[float, ...] | list[float], digits: int = 2) -> list[int]:
    """Largest-remainder rounding, in units of 10**(-digits) percent.

    The returned integers sum to ``100 * 10**digits`` (100% exactly).
    Probabilities are normalized first so a stored 4-decimal triple that
    sums to 1.0001 still displays as 100%.
    """
    cleaned = [max(0.0, float(p)) for p in probs]
    total = sum(cleaned)
    if total <= 0:
        return [0 for _ in cleaned]
    cleaned = [p / total for p in cleaned]
    factor = 10 ** digits
    units = 100 * factor
    raw = [p * units for p in cleaned]
    floors = [int(math.floor(x + 1e-9)) for x in raw]
    leftover = units - sum(floors)
    if leftover > 0:
        order = sorted(
            range(len(raw)),
            key=lambda i: (raw[i] - floors[i], cleaned[i]),
            reverse=True,
        )
        for i in range(leftover):
            floors[order[i]] += 1
    elif leftover < 0:
        order = sorted(range(len(floors)), key=lambda i: floors[i], reverse=True)
        for i in range(-leftover):
            floors[order[i % len(floors)]] -= 1
    return floors


def format_percent(hundredths: int) -> str:
    """Format a ``percent_shares`` value (digits=2) as ``49.33%``."""
    sign = "-" if hundredths < 0 else ""
    hundredths = abs(int(hundredths))
    return f"{sign}{hundredths // 100}.{hundredths % 100:02d}%"


def fair_line_display(
    market: str,
    mu_rec: float,
    mu_ypr: float,
    line: float,
    alpha: float = 0.1097,
    k: float = 1.555,
) -> FairLineDisplay:
    p_over, p_under, p_push = side_probabilities(
        market, mu_rec, mu_ypr, line, alpha=alpha, k=k,
    )
    over_h, under_h, push_h = percent_shares((p_over, p_under, p_push), digits=2)
    return FairLineDisplay(
        over_hundredths=over_h,
        under_hundredths=under_h,
        push_hundredths=push_h,
        over_odds=prob_to_american(p_over),
        under_odds=prob_to_american(p_under),
    )


def _html_odds(token: str) -> str:
    if token.startswith("-"):
        return "&minus;" + token[1:]
    return token


def _fmt_line(line: float) -> str:
    return f"{float(line):.1f}"


def render_value_paragraph(
    market: str,
    fair_line: float | None,
    mu_rec: float,
    mu_ypr: float,
    alpha: float = 0.1097,
    k: float = 1.555,
) -> str:
    """HTML (no wrapping ``<p>``) for the public-page value sentence.

    Snapshot qualification anchors are not an input. Both boundaries come
    from ``vig_boundaries``.
    """
    bounds = vig_boundaries(market, mu_rec, mu_ypr, alpha=alpha, k=k)
    if bounds.over_line is not None and bounds.under_line is not None:
        sentence = (
            "At &minus;110 vig, the model sees value on the OVER at lines "
            f"below <strong>{bounds.over_line:.1f}</strong> and on the UNDER "
            f"at lines above <strong>{bounds.under_line:.1f}</strong>. "
            "Between those boundaries, neither side clears the vig-adjusted "
            "breakeven."
        )
    elif bounds.over_line is not None:
        sentence = (
            "At &minus;110 vig, the model sees value on the OVER at lines "
            f"below <strong>{bounds.over_line:.1f}</strong>. The UNDER does "
            "not clear the vig-adjusted breakeven inside the modeled line range."
        )
    elif bounds.under_line is not None:
        sentence = (
            "At &minus;110 vig, the model sees value on the UNDER at lines "
            f"above <strong>{bounds.under_line:.1f}</strong>. The OVER does "
            "not clear the vig-adjusted breakeven at any modeled line."
        )
    else:
        sentence = (
            "At &minus;110 vig, neither side clears the vig-adjusted "
            "breakeven inside the modeled line range."
        )
    if fair_line is None:
        return sentence
    shown = fair_line_display(
        market, mu_rec, mu_ypr, float(fair_line), alpha=alpha, k=k,
    )
    fair = (
        f" At the fair line (<strong>{_fmt_line(fair_line)}</strong>), "
        f"no-vig breakeven odds are "
        f"<strong>{_html_odds(shown.over_odds)} on the OVER</strong> "
        f"({format_percent(shown.over_hundredths)} win prob) and "
        f"<strong>{_html_odds(shown.under_odds)} on the UNDER</strong> "
        f"({format_percent(shown.under_hundredths)} win prob)"
    )
    if shown.push_hundredths > 0:
        fair += f", with a <strong>{format_percent(shown.push_hundredths)} push</strong>"
    fair += "."
    return sentence + fair
