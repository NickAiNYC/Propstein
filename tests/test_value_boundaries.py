"""Public-page -110 value boundaries are solved from each player's distribution.

The frozen snapshot anchors (A.J. Brown receiving yards: 49.0 / 73.0, drawn as
a 49.5-72.5 dead band) are the 10% edge qualification screen. At -110 the
breakeven win probability is 110/210. An independent check of A.J. Brown
(mu_rec=5.2319, mu_ypr=12.9847, alpha=0.1097, k=1.555) puts the over root
near 58.2. The under root is near 64.4 if a flat ~0.9% push is subtracted
from every line; this repo's push model assigns that mass only on whole-number
lines (a half-yard window) and zero elsewhere, so the under root lands about
a yard inside 64.4. Both must be far from 49 and 73.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.value_boundaries import (
    MINUS_110_BREAKEVEN,
    fair_line_display,
    fair_line_from_params,
    render_value_paragraph,
    side_probabilities,
    vig_boundaries,
    yards_median,
)

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
AJ = dict(mu_rec=5.2319, mu_ypr=12.9847, alpha=0.1097, k=1.555)

# Old static dead-band copy. A player's true boundary may coincidentally be
# 49.0; this phrase is the published error, not a number that can occur.
STATIC_DEAD_BAND = "49.5&ndash;72.5"
BOUNDARY_RE = re.compile(
    r"lines below <strong>([0-9]+(?:\.[0-9]+)?)</strong> and on the UNDER "
    r"at lines above <strong>([0-9]+(?:\.[0-9]+)?)</strong>"
)
WIN_RE = re.compile(r"(\d+\.\d{2})% win prob")
PUSH_RE = re.compile(r"(\d+\.\d{2})% push")


def test_minus_110_breakeven_is_110_over_210():
    assert MINUS_110_BREAKEVEN == pytest.approx(110 / 210, abs=1e-12)


def test_aj_brown_yards_boundaries_near_58_2_and_64_4():
    bounds = vig_boundaries("receiving_yards", **AJ)
    assert bounds.over_exact == pytest.approx(58.2, abs=0.5)
    assert bounds.under_exact == pytest.approx(64.4, abs=1.25)
    # The roots are where the model probabilities equal the breakeven,
    # not the old 49.0 / 73.0 qualification anchors.
    assert abs(bounds.over_exact - 49.0) > 5
    assert abs(bounds.under_exact - 73.0) > 5
    p_over, _, _ = side_probabilities("receiving_yards", line=bounds.over_exact, **AJ)
    _, p_under, _ = side_probabilities("receiving_yards", line=bounds.under_exact, **AJ)
    assert p_over == pytest.approx(MINUS_110_BREAKEVEN, abs=1e-4)
    assert p_under == pytest.approx(MINUS_110_BREAKEVEN, abs=1e-4)
    # Pages print the roots to a tenth of a yard.
    assert bounds.over_line == pytest.approx(round(bounds.over_exact, 1), abs=1e-9)
    assert bounds.under_line == pytest.approx(round(bounds.under_exact, 1), abs=1e-9)
    assert bounds.over_line == pytest.approx(58.2, abs=1e-9)
    assert bounds.under_line == pytest.approx(63.4, abs=1e-9)


def test_aj_brown_integer_push_matches_frozen_probability_shape():
    """Whole-number yards use the half-yard window, and the three probs sum to 1."""
    p_over, p_under, p_push = side_probabilities("receiving_yards", line=61.0, **AJ)
    assert p_push == pytest.approx(0.00925, abs=2e-4)
    assert p_over + p_under + p_push == pytest.approx(1.0, abs=1e-12)
    # Continuous survival at 61 is not the push-adjusted over (that is P(Y > 61.5)).
    continuous, _, push_off = side_probabilities("receiving_yards", line=61.5, **AJ)
    assert push_off == 0.0
    assert p_over == pytest.approx(continuous, abs=1e-12)


def test_aj_brown_fair_line_display_sums_to_100():
    shown = fair_line_display("receiving_yards", line=61.0, **AJ)
    assert shown.sums_to_100
    assert shown.over_hundredths == 4933
    assert shown.under_hundredths == 4975
    assert shown.push_hundredths == 92
    # Favorite/underdog sign follows the probability. Both sides are dogs here.
    assert shown.over_odds.startswith("+")
    assert shown.under_odds.startswith("+")


def test_aj_brown_receptions_are_not_the_old_3_5_6_5_anchors():
    bounds = vig_boundaries("receptions", mu_rec=AJ["mu_rec"], alpha=AJ["alpha"])
    assert bounds.over_line == pytest.approx(5.0)
    assert bounds.under_line == pytest.approx(5.0)
    shown = fair_line_display("receptions", mu_rec=AJ["mu_rec"], mu_ypr=0.0, line=4.5, alpha=AJ["alpha"])
    assert shown.sums_to_100
    assert shown.push_hundredths == 0
    # 55% over is a favorite: negative American odds, not the old "+81".
    assert shown.over_odds.startswith("-")


def test_rendered_paragraph_ignores_static_anchors():
    text = render_value_paragraph(
        "receiving_yards", fair_line=61.0, **AJ,
    )
    assert "dead band" not in text
    assert "49.0" not in text
    assert "73.0" not in text
    assert "49.5" not in text
    assert "72.5" not in text
    assert "below <strong>58.2</strong>" in text
    assert "above <strong>63.4</strong>" in text
    wins = [float(x) for x in WIN_RE.findall(text)]
    pushes = [float(x) for x in PUSH_RE.findall(text)]
    assert len(wins) == 2
    assert abs(sum(wins) + sum(pushes) - 100.0) < 1e-9


def test_different_players_do_not_share_one_static_band():
    brown = vig_boundaries("receiving_yards", **AJ)
    other = vig_boundaries(
        "receiving_yards", mu_rec=2.1, mu_ypr=8.4, alpha=0.1097, k=1.555,
    )
    assert (brown.over_line, brown.under_line) != (other.over_line, other.under_line)


def _player_pages():
    return sorted((VIEWER / "nfl" / "players").glob("*/*/index.html"))


def test_generated_pages_do_not_use_static_boundaries():
    pages = _player_pages()
    assert len(pages) >= 780
    pairs = set()
    matched = 0
    missing = []
    bad_sum = []
    static_hits = []
    for path in pages:
        text = path.read_text()
        rel = str(path.relative_to(VIEWER))
        if "dead band" in text or STATIC_DEAD_BAND in text:
            static_hits.append(rel)
        if "vig-adjusted breakeven" not in text:
            missing.append(rel)
        match = BOUNDARY_RE.search(text)
        if match:
            matched += 1
            pairs.add((match.group(1), match.group(2)))
        wins = [float(x) for x in WIN_RE.findall(text)]
        pushes = [float(x) for x in PUSH_RE.findall(text)]
        if len(wins) != 2 or abs(sum(wins) + sum(pushes) - 100.0) > 1e-6:
            bad_sum.append((rel, wins, pushes))
    assert static_hits == []
    assert missing == []
    assert bad_sum == []
    # One player (a near-zero yardage distribution) never clears the over.
    assert len(pages) - matched <= 2
    # One shared pair would mean the pages still print a static band.
    assert len(pairs) > 50
    assert ("49.0", "73.0") not in pairs

    aj = (VIEWER / "nfl" / "players" / "a-j-brown" / "receiving-yards" / "index.html").read_text()
    assert "below <strong>58.2</strong>" in aj
    assert "above <strong>63.4</strong>" in aj
    assert "49.33% win prob" in aj
    assert "49.75% win prob" in aj
    assert "0.92% push" in aj

    methodology = (VIEWER / "methodology" / "index.html").read_text()
    assert "dead band" not in methodology
    assert STATIC_DEAD_BAND not in methodology
    assert "49.0" not in methodology
    assert "73.0" not in methodology
    assert "58.2" in methodology
    assert "63.4" in methodology


def test_snapshot_qualification_anchors_are_not_what_pages_print():
    """The page sentence is recomputed; it does not echo price_boundaries."""
    snaps = json.loads((VIEWER / "snapshots_2026_w7.json").read_text())
    latest = {}
    for snap in snaps:
        latest[(snap.get("player_id"), snap.get("market"))] = snap
    aj = next(
        s for s in latest.values()
        if s["player_name"] == "A.J. Brown" and s["market"] == "receiving_yards"
    )
    anchors = aj["price_boundaries"]
    assert anchors["max_acceptable_over_line_at_minus_110"] == 49.0
    assert anchors["min_acceptable_under_line_at_minus_110"] == 73.0
    params = aj["projection"]["distribution_params"]
    text = render_value_paragraph(
        aj["market"],
        aj["projection"]["fair_line"],
        params["mu_rec"],
        params["mu_ypr"],
        alpha=params["alpha"],
        k=params["k"],
    )
    assert ">49.0<" not in text
    assert ">73.0<" not in text
    assert ">58.2<" in text
    assert ">63.4<" in text


def test_fair_line_from_params_is_the_median_not_a_stored_anchor():
    """The display fair line is solved from the four parameters.

    A.J. Brown's continuous median rounds to the published 61.0. Mack Hollins's
    published parameters (the injury-conditional pair) have median ~45.66, so
    the half-yard fair line is 45.5, not the pre-redistribution 30.0 stored on
    the snapshot.
    """
    assert yards_median(**AJ) == pytest.approx(60.77, abs=0.02)
    assert fair_line_from_params("receiving_yards", **AJ) == 61.0
    hollins_median = yards_median(4.0923, 12.772, alpha=0.1097, k=1.555)
    assert hollins_median == pytest.approx(45.66, abs=0.02)
    assert fair_line_from_params(
        "receiving_yards", 4.0923, 12.772, alpha=0.1097, k=1.555,
    ) == 45.5
    # Discrete receptions: the .5 hook closest to P(over) = 1/2.
    assert fair_line_from_params("receptions", mu_rec=9.8767, alpha=0.1097) == 9.5
    assert fair_line_from_params("receptions", mu_rec=4.0923, alpha=0.1097) == 3.5
