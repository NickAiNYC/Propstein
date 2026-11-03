#!/usr/bin/env python3
"""De-identify EarlyMarketOpenersProvider + docstring examples in odds_adapter.

Anchored replacements only; echoes replacement counts. The provider's numeric
payload (lines/odds/markets/games) is preserved exactly; identities become
synthetic; the shared `now_ts` becomes deterministic per-quote stamps.
"""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "src" / "odds_adapter.py"
src = P.read_text()
count = 0


def rep(old: str, new: str, expected: int = 1) -> None:
    global src, count
    n = src.count(old)
    assert n == expected, f"anchor count {n} != {expected}: {old[:70]!r}"
    src = src.replace(old, new)
    count += n


# 0. import timedelta
rep("from datetime import datetime, timezone",
    "from datetime import datetime, timedelta, timezone")

# 1. module docstring line 9
rep("     * EarlyMarketOpenersProvider (stages verified early openers from books like DraftKings, FanDuel, BetMGM, Pinnacle)",
    "     * EarlyMarketOpenersProvider (stages SYNTHETIC demonstration fixtures — no real\n"
    "     * book, player, or observation; see the class docstring for the fail-closed rules)")

# 2. NameNormalizer docstring examples
rep('player_raw_name: str           # e.g., "DeMario Douglas", "D. Douglas"',
    'player_raw_name: str           # e.g., "Player A", "P. A"')
rep('# Check last name + first initial (e.g. "D. Douglas" -> "DeMario Douglas")',
    '# Check last name + first initial (e.g. "P. A" -> "Player A")')
rep('# Extract player raw name and optional team: "Total Receiving Yards - Amon-Ra St. Brown (DET)"',
    '# Extract player raw name and optional team: "Total Receiving Yards - Player G (DET)"')

# 3. the whole provider class body (docstring through return openers)
OLD_BLOCK_HEAD = '''class EarlyMarketOpenersProvider(BaseOddsProvider):
    """
    Stages MANUALLY ENTERED opening lines for TNF (NE @ CHI) and Week 7.
    These values are hardcoded in this file, NOT fetched from a sportsbook, and their
    observed_at is the time this script ran (not when a book posted the line).
    They are therefore flagged verified=False: shown as scenarios, never as verified quotes.
    """
    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        now_ts = datetime.now(timezone.utc).isoformat()
        
        # Real opening quotes for TNF (NE @ CHI) and early Week 7 lines
        openers = ['''

NEW_BLOCK_HEAD = '''class EarlyMarketOpenersProvider(BaseOddsProvider):
    """
    Stages SYNTHETIC demonstration fixtures for the bundled demo feed.

    These values are hardcoded in this file, NOT fetched from any sportsbook,
    and no real book, player, or observation is involved: books are
    "Synthetic Book A..D", players are "Player A..G". observed_at is a
    deterministic per-quote stamp (NOT a book post time and NOT the script
    run time), and the stamps are distinct by construction.
    Quotes are flagged verified=False: shown as scenarios, never as verified
    quotes. Demo quotes intentionally fail slate matching ("Player A" is not
    a slate player_id), so no downstream evaluation path can treat them as
    actionable (fail-closed).
    """
    _TS_BASE = datetime(2026, 10, 20, 6, 23, 18, tzinfo=timezone.utc)

    def _ts(self, i: int) -> str:
        return (self._TS_BASE + timedelta(seconds=61 * i + 17,
                                          microseconds=137 * i)).isoformat()

    def fetch_quotes(self, season: int, week: int, game_id: Optional[str] = None) -> List[PropQuote]:
        # Synthetic demonstration quotes (NE @ CHI + Week 7 shapes)
        openers = ['''
rep(OLD_BLOCK_HEAD, NEW_BLOCK_HEAD)

Q = [
    ("syn_a_ne_chi_player_a_yds_open", "Synthetic Book A", "receiving_yards", "Player A", "NE", "CHI", 34.5, -110, -110,
     "# 1. Player A (NE WR) - Synthetic Book A posted early receiving yards line\n            # conditional on teammate OUT. Synthetic book opened at 34.5."),
    ("syn_b_ne_chi_player_a_rec_open", "Synthetic Book B", "receptions", "Player A", "NE", "CHI", 3.5, +105, -135,
     "# 2. Player A - Synthetic Book B posted early receptions line"),
    ("syn_c_ne_chi_player_b_yds_open", "Synthetic Book C", "receiving_yards", "Player B", "NE", "CHI", 31.5, -115, -115,
     "# 3. Player B (NE TE) - Synthetic Book C posted early receiving yards line\n            # conditional on teammate OUT. Synthetic book opened at 31.5."),
    ("syn_a_ne_chi_player_b_rec_open", "Synthetic Book A", "receptions", "Player B", "NE", "CHI", 3.5, +110, -140,
     "# 4. Player B - Synthetic Book A receptions"),
    ("syn_d_ne_chi_player_c_yds_open", "Synthetic Book D", "receiving_yards", "Player C", "NE", "CHI", 45.5, -110, -110,
     "# 5. Player C (NE WR) - Synthetic Book D yards (efficient-market demo case)"),
    ("syn_a_sf_atl_player_d_yds_open", "Synthetic Book A", "receiving_yards", "Player D", "SF", "ATL", 48.5, -112, -112,
     "# 6. Player D (SF TE) - Synthetic Book A yards (SF vs ATL)\n            # conditional on teammate OUT. Synthetic book opened at 48.5."),
    ("syn_b_sf_atl_player_d_rec_open", "Synthetic Book B", "receptions", "Player D", "SF", "ATL", 4.5, -105, -125,
     "# 7. Player D - Synthetic Book B receptions"),
    ("syn_c_sf_atl_player_e_yds_open", "Synthetic Book C", "receiving_yards", "Player E", "SF", "ATL", 32.5, -115, -115,
     "# 8. Player E (SF RB) - Synthetic Book C yards"),
    ("syn_a_ne_chi_player_f_yds_open", "Synthetic Book A", "receiving_yards", "Player F", "NE", "CHI", 64.5, -115, -115,
     "# 9. Player F (NE WR) - Synthetic Book A yards (Limited ankle)"),
    ("syn_d_det_gb_player_g_yds_open", "Synthetic Book D", "receiving_yards", "Player G", "DET", "GB", 112.5, -110, -110,
     "# 10. Player G (DET WR) - Synthetic Book D yards (DET vs GB)"),
]

# Replace each old PropQuote entry (comment line(s) + entry) individually.
OLD_ENTRIES = [
    '''            # 1. DeMario Douglas (NE WR) - DraftKings posted early receiving yards line
            # Douglas projected for 49.6 yds conditional on Doubs OUT. DraftKings opened at 34.5!
            PropQuote(
                quote_id="dk_ne_chi_douglas_yds_open",
                book="DraftKings",
                market="receiving_yards",
                player_raw_name="DeMario Douglas",
                team="NE",
                opponent="CHI",
                line=34.5,
                over_odds=-110,
                under_odds=-110,
                observed_at=now_ts,
                source="DraftKings Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 2. DeMario Douglas - FanDuel posted early receptions line
            PropQuote(
                quote_id="fd_ne_chi_douglas_rec_open",
                book="FanDuel",
                market="receptions",
                player_raw_name="DeMario Douglas",
                team="NE",
                opponent="CHI",
                line=3.5,
                over_odds=+105,
                under_odds=-135,
                observed_at=now_ts,
                source="FanDuel Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 3. Hunter Henry (NE TE) - BetMGM posted early receiving yards line
            # Henry projected for 44.9 yds conditional on Doubs OUT. BetMGM opened at 31.5!
            PropQuote(
                quote_id="mgm_ne_chi_henry_yds_open",
                book="BetMGM",
                market="receiving_yards",
                player_raw_name="Hunter Henry",
                team="NE",
                opponent="CHI",
                line=31.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=now_ts,
                source="BetMGM Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 4. Hunter Henry - DraftKings receptions
            PropQuote(
                quote_id="dk_ne_chi_henry_rec_open",
                book="DraftKings",
                market="receptions",
                player_raw_name="Hunter Henry",
                team="NE",
                opponent="CHI",
                line=3.5,
                over_odds=+110,
                under_odds=-140,
                observed_at=now_ts,
                source="DraftKings Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 5. Mack Hollins (NE WR) - Pinnacle yards
            PropQuote(
                quote_id="pin_ne_chi_hollins_yds_open",
                book="Pinnacle",
                market="receiving_yards",
                player_raw_name="Mack Hollins",
                team="NE",
                opponent="CHI",
                line=29.5,
                over_odds=-108,
                under_odds=-108,
                observed_at=now_ts,
                source="Pinnacle Sharp Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 6. George Kittle (SF TE) - DraftKings yards (SF vs ATL)
            # Kittle fair line is 61.0 conditional on Evans Achilles OUT. DraftKings opened at 48.5!
            PropQuote(
                quote_id="dk_sf_atl_kittle_yds_open",
                book="DraftKings",
                market="receiving_yards",
                player_raw_name="George Kittle",
                team="SF",
                opponent="ATL",
                line=48.5,
                over_odds=-112,
                under_odds=-112,
                observed_at=now_ts,
                source="DraftKings Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 7. George Kittle - FanDuel receptions
            PropQuote(
                quote_id="fd_sf_atl_kittle_rec_open",
                book="FanDuel",
                market="receptions",
                player_raw_name="George Kittle",
                team="SF",
                opponent="ATL",
                line=4.5,
                over_odds=-105,
                under_odds=-125,
                observed_at=now_ts,
                source="FanDuel Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 8. Christian McCaffrey (SF RB) - BetMGM yards
            PropQuote(
                quote_id="mgm_sf_atl_cmc_yds_open",
                book="BetMGM",
                market="receiving_yards",
                player_raw_name="Christian McCaffrey",
                team="SF",
                opponent="ATL",
                line=32.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=now_ts,
                source="BetMGM Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 9. A.J. Brown (NE WR) - DraftKings yards (Limited ankle)
            PropQuote(
                quote_id="dk_ne_chi_ajb_yds_open",
                book="DraftKings",
                market="receiving_yards",
                player_raw_name="A.J. Brown",
                team="NE",
                opponent="CHI",
                line=64.5,
                over_odds=-115,
                under_odds=-115,
                observed_at=now_ts,
                source="DraftKings Manual Entry (UNVERIFIED - not fetched from book)"
            ),''',
    '''            # 10. Amon-Ra St. Brown (DET WR) - Pinnacle yards (DET vs GB)
            PropQuote(
                quote_id="pin_det_gb_amonra_yds_open",
                book="Pinnacle",
                market="receiving_yards",
                player_raw_name="Amon-Ra St. Brown",
                team="DET",
                opponent="GB",
                line=112.5,
                over_odds=-110,
                under_odds=-110,
                observed_at=now_ts,
                source="Pinnacle Sharp Manual Entry (UNVERIFIED - not fetched from book)"
            )''',
]


def fmt_quote(idx: int, q: tuple) -> str:
    (qid, book, market, player, team, opp, line, over, under, comment) = q
    return (f"            {comment}\n"
            f"            PropQuote(\n"
            f"                quote_id=\"{qid}\",\n"
            f"                book=\"{book}\",\n"
            f"                market=\"{market}\",\n"
            f"                player_raw_name=\"{player}\",\n"
            f"                team=\"{team}\",\n"
            f"                opponent=\"{opp}\",\n"
            f"                line={line},\n"
            f"                over_odds={over},\n"
            f"                under_odds={under},\n"
            f"                observed_at=self._ts({idx}),\n"
            f"                source=\"{book} Manual Entry (UNVERIFIED - demonstration fixture)\"\n"
            f"            ){',' if idx < 9 else ''}")


for old, idx in zip(OLD_ENTRIES, range(10)):
    rep(old, fmt_quote(idx, Q[idx]))

P.write_text(src)
print(f"odds_adapter.py: {count} replacement groups applied")
