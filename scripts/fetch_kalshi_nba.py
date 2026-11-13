#!/usr/bin/env python3
"""fetch_kalshi_nba.py - free, keyless NBA player-points lines from Kalshi.

Fallback for scripts/fetch_nba_odds.py when The Odds API key is out of
credits. Writes the SAME two files the NBA market board already reads:

  nba_games_<date>.json  schedule from ESPN's public scoreboard (tip-off times)
  nba_odds_<date>.json   one "main line" per player from Kalshi's public
                         KXNBAPTS markets, through the LiveOddsFeed contract

Kalshi lists binary "N+ points" contracts per player. "25+ points" is the same
bet as Over 24.5, so line = floor_strike, Over price = the YES ask and Under
price = the NO ask (fees excluded). Of a player's thresholds, the main line is
the genuinely two-sided one (bid > 0, spread <= --max-spread) whose midpoint is
closest to 50%. Placeholder quotes (bid 0, ask 0.95) are skipped.

HONESTY RULES (same as fetch_nba_odds.py): every quote is _fixture:false and
verified:false; nothing is synthesised. No usable quote -> nothing written.

    python3 scripts/fetch_kalshi_nba.py --date 2026-11-13
    python3 scripts/fetch_kalshi_nba.py --selftest

EXIT: 0 ok (or no games that day), 3 games but no usable quotes yet, 5 network/contract error.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VIEWER = ROOT / "viewer"
ET = ZoneInfo("America/New_York")
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SERIES = "KXNBAPTS"
BOOK = "Kalshi"
SOURCE = "Kalshi exchange (unverified market quote)"
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

#: ESPN / Kalshi team codes -> the repo's codes (scripts/fetch_nba_odds.py TEAM_ABBR).
TEAM_ALIASES = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA",
                "WSH": "WAS", "BRK": "BKN", "PHO": "PHX", "CHO": "CHA", "NOR": "NOP"}
TEAMS = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND",
         "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
         "POR", "SAC", "SAS", "TOR", "UTA", "WAS"}


def team(code: str) -> str:
    code = str(code or "").upper().strip()
    return TEAM_ALIASES.get(code, code)


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def get_json(url: str, params: dict | None = None):
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    req = urllib.request.Request(full, headers={"Accept": "application/json", "User-Agent": "propstein-data/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cents_to_american(p: float) -> int:
    """Price (0-1) -> American odds. Same mapping as the Polymarket fetcher."""
    p = min(0.98, max(0.02, p))
    if p >= 0.5:
        return -round(100.0 * p / (1.0 - p))
    return round(100.0 * (1.0 - p) / p)


# ---- schedule (ESPN) ------------------------------------------------------

def normalize_espn_games(payload: dict, day: str) -> list[dict]:
    games = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): team((c.get("team") or {}).get("abbreviation")) for c in comp.get("competitors", [])}
        away, home = sides.get("away"), sides.get("home")
        if away not in TEAMS or home not in TEAMS:
            raise ValueError(f"unmapped team in ESPN event {ev.get('id')}: {away} @ {home}")
        tip = datetime.fromisoformat(str(ev["date"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        if tip.astimezone(ET).date().isoformat() != day:
            continue
        et = tip.astimezone(ET)
        games.append({
            "game_id": f"nba-{day.replace('-', '')}-{away}-{home}",
            "gameday": day,
            "gametime": et.strftime("%H:%M"),
            "gametime_et": et.strftime("%H:%M"),
            "tipoff_utc": tip.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "away_team": away,
            "home_team": home,
            "odds_event_id": None,
            "espn_event_id": str(ev.get("id") or ""),
            "_fixture": False,
        })
    return sorted(games, key=lambda g: (g["tipoff_utc"], g["game_id"]))


# ---- Kalshi markets ---------------------------------------------------------

def event_date(event_ticker: str) -> str | None:
    """KXNBAPTS-26NOV13ATLCHI -> 2026-11-13."""
    try:
        code = event_ticker.split("-")[1]
        return date(2000 + int(code[:2]), MONTHS[code[2:5]], int(code[5:7])).isoformat()
    except (IndexError, KeyError, ValueError):
        return None


def event_teams(event: dict) -> tuple[str, str] | None:
    """'ATL vs CHI (Nov 13)' -> ('ATL', 'CHI'); away team is listed first."""
    sub = str(event.get("sub_title") or "").split("(")[0]
    parts = [team(p) for p in sub.split(" vs ")]
    return (parts[0], parts[1]) if len(parts) == 2 and all(p in TEAMS for p in parts) else None


def fetch_series(path: str, key: str) -> list[dict]:
    out, cursor = [], None
    for _ in range(20):  # hard page cap
        params = {"series_ticker": SERIES, "status": "open", "limit": 1000 if key == "markets" else 200}
        if cursor:
            params["cursor"] = cursor
        page = get_json(f"{KALSHI}/{path}", params)
        out += page.get(key) or []
        cursor = page.get("cursor")
        if not cursor:
            break
    return out


def price(market: dict, field: str) -> float:
    try:
        return float(market.get(f"{field}_dollars"))
    except (TypeError, ValueError):
        return 0.0


def main_lines(markets: list[dict], max_spread: float = 0.10) -> dict[str, dict]:
    """player name -> the two-sided threshold market nearest 50%."""
    best: dict[str, tuple[float, dict]] = {}
    for m in markets:
        if m.get("strike_type") != "greater" or m.get("floor_strike") is None:
            continue
        bid, ask, no_ask = price(m, "yes_bid"), price(m, "yes_ask"), price(m, "no_ask")
        if not (0 < bid < ask < 1) or ask - bid > max_spread or not (0 < no_ask < 1):
            continue
        player = str(m.get("title") or "").split(":")[0].strip()
        if not player:
            continue
        dist = abs((bid + ask) / 2 - 0.5)
        if player not in best or dist < best[player][0]:
            best[player] = (dist, m)
    return {p: m for p, (_, m) in best.items()}


def build_quotes(day: str, games: list[dict], events: list[dict], markets: list[dict],
                 observed_at: str, max_spread: float = 0.10) -> list[dict]:
    by_pair = {frozenset((g["away_team"], g["home_team"])): g for g in games}
    quotes = []
    for ev in events:
        if event_date(ev.get("event_ticker", "")) != day:
            continue
        pair = event_teams(ev)
        game = by_pair.get(frozenset(pair)) if pair else None
        if game is None:
            continue
        ev_markets = [m for m in markets if m.get("event_ticker") == ev["event_ticker"]]
        for player, m in sorted(main_lines(ev_markets, max_spread).items()):
            seg = str(m["ticker"]).split("-")[2] if m["ticker"].count("-") >= 3 else ""
            own = next((t for t in pair if seg.startswith(t) or seg.startswith(_kalshi_code(ev, t))), None)
            line = float(m["floor_strike"])
            quotes.append({
                "quote_id": f"{game['game_id']}_kalshi_{slug(player)}_points_{f'{line:g}'.replace('.', 'p')}",
                "provider_quote_id": m["ticker"],
                "source_url": f"{KALSHI}/markets/{m['ticker']}",
                "book": BOOK,
                "player_id": f"odds-nba-{slug(player)}",
                "player_name": player,
                "team": own,
                "opponent": next((t for t in pair if t != own), None) if own else None,
                "game_id": game["game_id"],
                "market": "points",
                "line": line,
                "over_odds": cents_to_american(price(m, "yes_ask")),
                "under_odds": cents_to_american(price(m, "no_ask")),
                "over_ask_price": price(m, "yes_ask"),
                "under_ask_price": price(m, "no_ask"),
                "observed_at": observed_at,
                "source": SOURCE,
                "verified": False,
                "_fixture": False,
                "unit": "pts",
            })
    return quotes


def _kalshi_code(event: dict, repo_code: str) -> str:
    """Raw code Kalshi used for a team in this event's sub_title (e.g. GS vs GSW)."""
    sub = str(event.get("sub_title") or "").split("(")[0]
    for raw in (p.strip().upper() for p in sub.split(" vs ")):
        if team(raw) == repo_code:
            return raw
    return repo_code


# ---- publish --------------------------------------------------------------

def write_files(day: str, games: list[dict], quotes: list[dict], observed_at: str) -> bool:
    from src.contracts.gate import validate_and_publish
    from src.contracts.odds import LiveOddsFeed
    payload = {
        "schema_version": "nba.v1",
        "feed_status": "live-unverified",
        "_fixture": False,
        "updated_at": observed_at,
        "slate": day,
        "source": "kalshi",
        "verified_books_count": 0,
        "verified_quotes_count": 0,
        "monitored_books": [BOOK],
        "unverified_books": [BOOK],
        "total_quotes": len(quotes),
        "qualified_count": 0,
        "quotes": quotes,
    }
    ok, _ = validate_and_publish(schema_cls=LiveOddsFeed, raw_data=payload,
                                 target_path=str(VIEWER / f"nba_odds_{day}.json"), source_feed="kalshi_nba")
    if not ok:
        return False
    tmp = VIEWER / f"nba_games_{day}.json.tmp"
    tmp.write_text(json.dumps(games, indent=1) + "\n", encoding="utf-8")
    tmp.replace(VIEWER / f"nba_games_{day}.json")
    return True


def run(day: str, max_spread: float) -> int:
    try:
        games = normalize_espn_games(get_json(ESPN, {"dates": day.replace("-", "")}), day)
        if not games:
            print(f"[kalshi_nba] {day}: no NBA games on ESPN's schedule; nothing written")
            return 0
        events = fetch_series("events", "events")
        markets = fetch_series("markets", "markets")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[kalshi_nba] fetch failed closed: {exc}", file=sys.stderr)
        return 5
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    quotes = build_quotes(day, games, events, markets, observed_at, max_spread)
    covered = len({q["game_id"] for q in quotes})
    print(f"[kalshi_nba] {day}: {len(games)} games (ESPN), {len(markets)} open Kalshi markets, "
          f"{len(quotes)} two-sided main lines across {covered} games")
    if not quotes:
        print("[kalshi_nba] no usable two-sided quotes yet; nothing written", file=sys.stderr)
        return 3
    if not write_files(day, games, quotes, observed_at):
        print("[kalshi_nba] contract validation failed; existing files preserved", file=sys.stderr)
        return 5
    return 0


def selftest() -> None:
    espn = {"events": [
        {"id": "1", "date": "2026-11-14T00:00Z", "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "NY"}}, {"homeAway": "home", "team": {"abbreviation": "IND"}}]}]},
        {"id": "2", "date": "2026-11-14T02:30Z", "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "GS"}}, {"homeAway": "home", "team": {"abbreviation": "SA"}}]}]}]}
    games = normalize_espn_games(espn, "2026-11-13")
    assert [g["game_id"] for g in games] == ["nba-20261113-NYK-IND", "nba-20261113-GSW-SAS"], games
    assert games[0]["gametime_et"] == "19:00"
    assert event_date("KXNBAPTS-26NOV13NYKIND") == "2026-11-13"
    events = [{"event_ticker": "KXNBAPTS-26NOV13GSSA", "sub_title": "GS vs SA (Nov 13)"}]
    mk = lambda t, k, b, a, n: {"ticker": f"KXNBAPTS-26NOV13GSSA-{t}-{k}", "event_ticker": "KXNBAPTS-26NOV13GSSA",
                                "title": f"{'Stephen Curry' if t.startswith('GS') else 'Victor Wembanyama'}: {k}+ points",
                                "strike_type": "greater", "floor_strike": k - 0.5,
                                "yes_bid_dollars": b, "yes_ask_dollars": a, "no_ask_dollars": n}
    markets = [mk("GSSCURRY30", 20, "0.80", "0.84", "0.20"), mk("GSSCURRY30", 25, "0.47", "0.51", "0.53"),
               mk("GSSCURRY30", 30, "0.20", "0.24", "0.80"), mk("SAVWEMBANYAMA1", 25, "0.0000", "0.95", "1.00")]
    q = build_quotes("2026-11-13", games, events, markets, "2026-11-13T16:00:00Z")
    assert len(q) == 1, q  # placeholder-only player skipped
    assert q[0]["line"] == 24.5 and q[0]["team"] == "GSW" and q[0]["opponent"] == "SAS", q[0]
    assert q[0]["over_odds"] == -104 and q[0]["under_odds"] == -113, q[0]
    assert q[0]["verified"] is False and q[0]["_fixture"] is False and q[0]["book"] == "Kalshi"
    print("selftest ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="US-Eastern slate date, YYYY-MM-DD (default: today ET)")
    ap.add_argument("--max-spread", type=float, default=0.10)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        selftest()
        return 0
    day = args.date or datetime.now(ET).date().isoformat()
    date.fromisoformat(day)
    return run(day, args.max_spread)


if __name__ == "__main__":
    sys.exit(main())
