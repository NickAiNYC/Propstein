"""Every static player page is reproducible from the parameters it prints.

PR #107 already solves the -110 roots from those parameters. This contract
also locks the fair line (the median, not the mean) and the two P(over)
tiles. A page with no parameters fails closed.

Rounding:
- Receiving yards fair line: continuous compound median, displayed on the
  half-yard grid (nearest 0.5). Tolerance is 0.001 yard against that grid,
  which is smaller than one grid step, so a stale median such as 30.0 versus
  45.66 fails.
- Receptions fair line: the .5 hook whose Negative-Binomial P(over) is
  closest to one half. Exact match.
- -110 boundaries: lines where the win probability equals 110/210 (52.38%),
  printed to 0.1. The rendered tenth must sit within 0.05 of the independent
  root (the maximum error of one-decimal rounding).
- P(over) tiles: one-decimal percentages, within 0.06 points of the
  probability at that line. "P(over) at quote" is an em dash when the page
  has no captured quote.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from scipy import stats
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parent.parent
PLAYERS = ROOT / "viewer" / "nfl" / "players"
BREAKEVEN = 110 / 210

PARAMS_RE = re.compile(
    r"mu_rec (?P<mu_rec>None|[0-9]+(?:\.[0-9]+)?), "
    r"mu_ypr (?P<mu_ypr>None|[0-9]+(?:\.[0-9]+)?), "
    r"alpha (?P<alpha>None|[0-9]+(?:\.[0-9]+)?), "
    r"k (?P<k>None|[0-9]+(?:\.[0-9]+)?)\."
)
FAIR_RE = re.compile(
    r"<dt>Fair line</dt><dd>([0-9]+(?:\.[0-9]+)?) (?:yds|rec)</dd>"
)
VOLUME_RE = re.compile(
    r"<dt>Projected volume</dt><dd>([0-9]+(?:\.[0-9]+)?) (?:yds|rec)</dd>"
)
FAIR_P_RE = re.compile(r"<dt>P\(over\) at fair line</dt><dd>([^<]+)</dd>")
QUOTE_P_RE = re.compile(r"<dt>P\(over\) at quote</dt><dd>([^<]+)</dd>")
OLD_TILE_RE = re.compile(r"<dt>P\(over\) at fair</dt>")
OVER_RE = re.compile(
    r"OVER at lines below <strong>([0-9]+(?:\.[0-9]+)?)</strong>"
)
UNDER_RE = re.compile(
    r"UNDER at lines above <strong>([0-9]+(?:\.[0-9]+)?)</strong>"
)
SENTENCE_FAIR_RE = re.compile(
    r"At the fair line \(<strong>([0-9]+(?:\.[0-9]+)?)</strong>\)"
)
QUOTE_LINE_RE = re.compile(
    r"pub-status-quoted'>Latest captured quote:.*?</strong>\s*"
    r"([0-9]+(?:\.[0-9]+)?)",
    re.DOTALL,
)
FAIR_ODDS_RE = re.compile(
    r"push-adjusted fair odds are <strong>((?:&minus;|-|\+)\d+) on the OVER</strong> "
    r".*?<strong>((?:&minus;|-|\+)\d+) on the UNDER</strong>",
    re.DOTALL,
)
EM_DASHES = {"—", "&mdash;", "&#8212;", "–"}


def _pages():
    return sorted(PLAYERS.glob("*/*/index.html"))


def _num(token: str) -> float:
    if token == "None":
        raise ValueError("published parameter is missing")
    return float(token)


def _p_yards_over(mu_rec: float, mu_ypr: float, line: float, alpha: float, k: float) -> float:
    """Compound NB-Gamma survival, P(Y > line). Point mass at zero catches is included."""
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    n_max = int(max(20, stats.nbinom.ppf(0.99995, r, p) + 5))
    ns = np.arange(1, n_max + 1)
    pn = stats.nbinom.pmf(ns, r, p)
    sf = stats.gamma.sf(line, a=ns * k, scale=mu_ypr / k)
    return float(np.dot(pn, sf))


def _yards_median(mu_rec, mu_ypr, alpha, k) -> float:
    lo, hi = 0.0, 400.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _p_yards_over(mu_rec, mu_ypr, mid, alpha, k) > 0.5:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _receptions_fair(mu_rec: float, alpha: float) -> float:
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    n = int(stats.nbinom.ppf(0.5, r, p))
    lo = max(n - 1, 0)
    sf_lo = float(stats.nbinom.sf(lo, r, p))
    sf_hi = float(stats.nbinom.sf(n, r, p))
    if abs(sf_lo - 0.5) < abs(sf_hi - 0.5):
        return float(lo + 0.5)
    return float(n + 0.5)


def _p_over(market: str, mu_rec, mu_ypr, alpha, k, line: float) -> float:
    """P(over) at a printed line, including the integer push window."""
    if market == "receiving_yards":
        if abs(line - round(line)) < 1e-8:
            whole = round(line)
            return _p_yards_over(mu_rec, mu_ypr, whole + 0.5, alpha, k)
        return _p_yards_over(mu_rec, mu_ypr, line, alpha, k)
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    return float(stats.nbinom.sf(np.floor(line), r, p))


def _side_probs(market: str, mu_rec, mu_ypr, alpha, k, line: float) -> tuple[float, float]:
    """Independent win/loss probabilities, excluding the refunded push."""
    if market == "receiving_yards":
        if abs(line - round(line)) < 1e-8:
            return (
                _p_yards_over(mu_rec, mu_ypr, line + 0.5, alpha, k),
                1.0 - _p_yards_over(mu_rec, mu_ypr, line - 0.5, alpha, k),
            )
        over = _p_yards_over(mu_rec, mu_ypr, line, alpha, k)
        return over, 1.0 - over
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    over = float(stats.nbinom.sf(np.floor(line), r, p))
    under = float(stats.nbinom.cdf(np.ceil(line) - 1, r, p))
    return over, under


def _fair_american(win: float, lose: float) -> str:
    if win >= lose:
        return str(-round(100 * win / lose))
    return f"+{round(100 * lose / win)}"


def _solve(gap, lo: float, hi: float, *, increasing: bool) -> float | None:
    flo = gap(lo)
    fhi = gap(hi)
    limit = 800.0
    if increasing and flo >= 0:
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


def _yards_roots(mu_rec, mu_ypr, alpha, k) -> tuple[float | None, float | None]:
    hi = max(80.0, mu_rec * mu_ypr * 4.0 + 40.0)

    def p_over(line: float) -> float:
        probed = line + 1e-6 if abs(line - round(line)) < 1e-8 else line
        return _p_yards_over(mu_rec, mu_ypr, probed, alpha, k)

    return (
        _solve(lambda line: p_over(line) - BREAKEVEN, 0.05, hi, increasing=False),
        _solve(lambda line: (1.0 - p_over(line)) - BREAKEVEN, 0.05, hi, increasing=True),
    )


def _receptions_roots(mu_rec, alpha) -> tuple[float | None, float | None]:
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    over = under = None
    for n in range(0, 81):
        if float(stats.nbinom.sf(n, r, p)) < BREAKEVEN:
            over = float(n)
            break
    for n in range(0, 81):
        # P(under) on the half-point n+0.5 is 1 - P(N > n).
        if 1.0 - float(stats.nbinom.sf(n, r, p)) >= BREAKEVEN:
            under = float(n)
            break
    return over, under


def _percent(text: str) -> float | None:
    token = text.strip()
    if token in EM_DASHES:
        return None
    if token.endswith("%"):
        return float(token[:-1])
    raise ValueError(f"not a percentage or em dash: {token!r}")


def _check(path: Path) -> list[str]:
    rel = str(path.relative_to(ROOT / "viewer"))
    market = "receiving_yards" if path.parent.name == "receiving-yards" else "receptions"
    text = path.read_text()
    failures = []
    found = PARAMS_RE.search(text)
    if not found:
        return [f"{rel}: missing distribution parameters (fail closed)"]
    try:
        mu_rec = _num(found.group("mu_rec"))
        mu_ypr = _num(found.group("mu_ypr"))
        alpha = _num(found.group("alpha"))
        k = _num(found.group("k"))
    except ValueError:
        return [f"{rel}: a published parameter is missing (fail closed)"]
    if market == "receiving_yards" and not np.isfinite(mu_ypr):
        return [f"{rel}: mu_ypr missing (fail closed)"]

    fair_m = FAIR_RE.search(text)
    if not fair_m:
        failures.append(f"{rel}: fair line tile missing")
        rendered_fair = None
    else:
        rendered_fair = float(fair_m.group(1))
        if market == "receiving_yards":
            median = _yards_median(mu_rec, mu_ypr, alpha, k)
            expected = float(np.round(median * 2.0) / 2.0)
        else:
            median = expected = _receptions_fair(mu_rec, alpha)
        if abs(rendered_fair - expected) > 0.001:
            failures.append(
                f"{rel}: fair line {rendered_fair} != median {median:.4f} "
                f"displayed as {expected}"
            )
        sentence = SENTENCE_FAIR_RE.search(text)
        if sentence is None or abs(float(sentence.group(1)) - rendered_fair) > 1e-9:
            failures.append(f"{rel}: value sentence fair line does not match the tile")

    volume_m = VOLUME_RE.search(text)
    if volume_m:
        rendered_volume = float(volume_m.group(1))
        expected_volume = round(mu_rec * mu_ypr, 2) if market == "receiving_yards" else round(mu_rec, 2)
        if abs(rendered_volume - expected_volume) > 0.001:
            failures.append(
                f"{rel}: projected volume {rendered_volume} != mean {expected_volume}"
            )
    else:
        failures.append(f"{rel}: projected volume tile missing")

    if market == "receiving_yards":
        over_root, under_root = _yards_roots(mu_rec, mu_ypr, alpha, k)
    else:
        over_root, under_root = _receptions_roots(mu_rec, alpha)
    over_m = OVER_RE.search(text)
    under_m = UNDER_RE.search(text)
    for label, rendered_m, root in (
        ("over", over_m, over_root),
        ("under", under_m, under_root),
    ):
        rendered = float(rendered_m.group(1)) if rendered_m else None
        if root is None:
            if rendered is not None:
                failures.append(
                    f"{rel}: printed {label} boundary {rendered} but P never "
                    f"clears {BREAKEVEN:.4f}"
                )
            elif label == "over" and "OVER does not clear" not in text and "neither side clears" not in text:
                failures.append(f"{rel}: over has no root and the page does not say so")
            elif label == "under" and "UNDER does not clear" not in text and "neither side clears" not in text:
                failures.append(f"{rel}: under has no root and the page does not say so")
        elif rendered is None:
            failures.append(f"{rel}: missing {label} boundary; root {root:.4f}")
        elif abs(rendered - root) > 0.05 + 1e-9:
            failures.append(
                f"{rel}: {label} boundary {rendered} is not within 0.05 of root {root:.4f}"
            )

    if OLD_TILE_RE.search(text):
        failures.append(f"{rel}: ambiguous 'P(over) at fair' tile is still present")
    fair_p = FAIR_P_RE.search(text)
    quote_p = QUOTE_P_RE.search(text)
    if fair_p is None or quote_p is None:
        failures.append(f"{rel}: missing 'P(over) at fair line' or 'P(over) at quote'")
        return failures
    quote_line_m = QUOTE_LINE_RE.search(text)
    unquoted = "pub-status-unquoted" in text
    try:
        fair_pct = _percent(fair_p.group(1))
        quote_pct = _percent(quote_p.group(1))
    except ValueError as exc:
        failures.append(f"{rel}: {exc}")
        return failures
    if rendered_fair is not None and fair_pct is not None:
        expected_pct = 100.0 * _p_over(market, mu_rec, mu_ypr, alpha, k, rendered_fair)
        if abs(fair_pct - expected_pct) > 0.06:
            failures.append(
                f"{rel}: P(over) at fair line {fair_pct}% != {expected_pct:.2f}% "
                f"at {rendered_fair}"
            )
        odds_m = FAIR_ODDS_RE.search(text)
        if odds_m is None:
            failures.append(f"{rel}: push-adjusted fair odds missing")
        else:
            over_win, under_win = _side_probs(
                market, mu_rec, mu_ypr, alpha, k, rendered_fair,
            )
            expected_over = _fair_american(over_win, under_win)
            expected_under = _fair_american(under_win, over_win)
            printed = tuple(token.replace("&minus;", "-") for token in odds_m.groups())
            if printed != (expected_over, expected_under):
                failures.append(
                    f"{rel}: fair odds {printed} != push-adjusted "
                    f"{(expected_over, expected_under)}"
                )
    if unquoted or quote_line_m is None:
        if quote_pct is not None:
            failures.append(
                f"{rel}: no captured quote but P(over) at quote is {quote_p.group(1)}"
            )
    else:
        quote_line = float(quote_line_m.group(1))
        expected_quote = 100.0 * _p_over(market, mu_rec, mu_ypr, alpha, k, quote_line)
        if quote_pct is None:
            failures.append(f"{rel}: captured quote {quote_line} but the quote tile is an em dash")
        elif abs(quote_pct - expected_quote) > 0.06:
            failures.append(
                f"{rel}: P(over) at quote {quote_pct}% != {expected_quote:.2f}% at {quote_line}"
            )
    return failures


def test_player_pages_exist():
    pages = _pages()
    assert len(pages) >= 780


def test_every_player_page_recomputes_from_published_parameters():
    pages = _pages()
    failures = []
    for path in pages:
        failures.extend(_check(path))
    assert failures == [], (
        f"{len(failures)} player-page contract failures\n" + "\n".join(failures[:30])
    )


def test_aj_brown_receiving_yards_matches_the_worked_example():
    """Reference that already agreed with the published parameters."""
    text = (PLAYERS / "a-j-brown" / "receiving-yards" / "index.html").read_text()
    found = PARAMS_RE.search(text)
    assert found is not None
    mu_rec = float(found.group("mu_rec"))
    mu_ypr = float(found.group("mu_ypr"))
    assert round(mu_rec * mu_ypr, 2) == pytest.approx(67.93, abs=1e-9)
    fair = float(FAIR_RE.search(text).group(1))
    median = _yards_median(mu_rec, mu_ypr, float(found.group("alpha")), float(found.group("k")))
    assert fair == pytest.approx(61.0, abs=1e-9)
    assert abs(fair - median) <= 0.25
    over_root, under_root = _yards_roots(
        mu_rec, mu_ypr, float(found.group("alpha")), float(found.group("k")),
    )
    assert over_root == pytest.approx(58.23, abs=0.02)
    assert under_root == pytest.approx(63.37, abs=0.02)
    assert float(OVER_RE.search(text).group(1)) == pytest.approx(58.2, abs=1e-9)
    assert float(UNDER_RE.search(text).group(1)) == pytest.approx(63.4, abs=1e-9)
    assert FAIR_P_RE.search(text)
    assert QUOTE_P_RE.search(text)
