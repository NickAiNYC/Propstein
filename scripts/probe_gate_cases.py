#!/usr/bin/env python3
"""Probe the qualification gate with candidate sub-hurdle lines (no source pasting).

Builds the same __new__-pattern adapter as tests/test_gate_boundary.py and prints
prob_edge / expected_return / status / is_qualified / actionable_stake for each
candidate line, so the LEAN-band case is chosen empirically, not by hand math.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from odds_adapter import PropQuote, OddsIngestionAdapter, EDGE_HURDLE

SYN_SLATE = [{
    "player_id": "SYN-Z",
    "player_display_name": "Player Z",
    "team": "NE",
    "opponent_team": "CHI",
    "game_id": "2026_07_NE_CHI",
    "position": "WR",
    "mu_rec": 4.0,
    "mu_ypr": 11.0,
    "fair_line_rec": 6.5,
    "fair_line_yards": 55.0,
}]


def probe(line: float, over_odds: int = -110, under_odds: int = -110) -> None:
    quote = PropQuote(
        quote_id=f"probe_sub_hurdle_{line}_{over_odds}",
        book="Synthetic Book A",
        market="receptions",
        player_raw_name="Player Z",
        team="NE",
        opponent="CHI",
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        observed_at="2026-10-20T06:00:00+00:00",
        source="Synthetic Book A Manual Entry (UNVERIFIED - probe)",
        verified=True,
    )
    a = OddsIngestionAdapter.__new__(OddsIngestionAdapter)
    a.season = 2026
    a.week = 7
    a.slate_players = SYN_SLATE
    a.injury_beneficiaries = {}
    a.model = None
    a.provider = type("StubProvider", (), {
        "fetch_quotes": lambda self, season, week, game_id=None: [quote],
    })()
    a.emit_snapshots = lambda evaluations: []
    a.export_live_feed = lambda evaluations: "unused"
    a._trigger_db_ingestion = lambda: None

    ev = a.evaluate_quote(quote)
    print(f"line={line:>5}  prob_edge={ev.prob_edge:+.4f}  "
          f"expected_return={ev.expected_return:+.4f}  status={ev.status:<10} "
          f"is_qualified={ev.is_qualified}  stake={ev.actionable_stake}  "
          f"(EDGE_HURDLE={EDGE_HURDLE}, half={EDGE_HURDLE * 0.5})")


if __name__ == "__main__":
    print("--- line sweep at -110/-110 ---")
    for line in (2.5, 3.0, 3.5, 4.0, 4.5):
        probe(line)
    print("--- odds sweep at line 2.5 (worse over price -> smaller devig edge) ---")
    for over, under in ((-170, 140), (-175, 145), (-180, 150), (-185, 155)):
        probe(2.5, over, under)
