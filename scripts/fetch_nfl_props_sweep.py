#!/usr/bin/env python3
"""fetch_nfl_props_sweep.py — bulk The Odds API NFL player-prop sweep (book #2).

PHASE 1A (audit §b.3, §d): the NFL board feed has exactly one real publisher
(Polymarket). This sweep adds the second publisher — sportsbook player props
via The Odds API's BULK /odds endpoint, ONE request for the whole league
(2 markets x 1 region = 2 credits per sweep, never the 250-450-credit
per-event path) — merged into the same viewer/live_odds_feed.json the board
serves, republished atomically through the frozen PolymarketMergedFeed
contract.

HONESTY RULES (fail-closed — this sweep must NEVER block book #1):
  * No ODDS_API_KEY -> loud message, exit 0; the Polymarket feed publishes
    regardless.
  * API / network / contract failure -> feed untouched, exit 0, loud stderr.
  * Nothing is ever synthesised. Rows carry verified:false, the real sweep
    time, real book names, real paired odds.
  * NO verification stamps are written here. Adding a second book makes the
    frozen V3_conflict clause CHECKABLE on markets where >= 2 sharp books
    quote the same player/line — it does NOT unlock VERIFIED by itself.
    VERIFIED stays engine-assigned only (and the feed contract still forbids
    verified counts on this path until that amendment is deliberate).
  * Credits: the free /events probe runs first and reads
    x-requests-remaining; below --min-remaining the sweep is skipped BEFORE
    spending. The 2-credit request fires only inside an active slate window
    (a game within -1..+7 days, the same rule as check_odds_freshness)
    unless --mode force. Exit code is always 0 (except --selftest failures):
    this step must never gate the Polymarket steps around it.

USAGE:
  ODDS_API_KEY=... python3 scripts/fetch_nfl_props_sweep.py            # auto
  ODDS_API_KEY=... python3 scripts/fetch_nfl_props_sweep.py --mode force
  python3 scripts/fetch_nfl_props_sweep.py --selftest                  # offline
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
FEED_PATH = VIEWER / "live_odds_feed.json"
SLATE_INDEX = VIEWER / "feeds" / "slate-index.json"

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# The Odds API market key -> the slate's market id (same vocabulary the
# Polymarket parser emits; src/odds.py MARKETS is the API-key source).
MARKETS = {"player_receptions": "receptions",
           "player_reception_yds": "receiving_yards"}

#: Row marker: every row this sweep writes carries this exact `source`, and
#: each run REPLACES all rows carrying it (dead provider rows never persist).
SWEEP_SOURCE = "The Odds API (unverified sportsbook quote)"

#: Credits one sweep spends: 2 markets x 1 region (audit §d).
SWEEP_CREDIT_COST = 2


def _sharp_books() -> set[str]:
    """Sharpness comes from the FROZEN engine's own config — single source of
    truth (src/odds.py's SHARP_BOOKS mirrors it; importing that module would
    drag in `requests`, which the odds_freshness workflow does not install)."""
    sys.path.insert(0, str(ROOT))
    from src.contracts.verification import VerificationConfig
    return set(VerificationConfig().sharp_books)


def _load_pm_module():
    """Reuse the Polymarket fetcher's slate loading / name normalisation —
    one implementation of player matching across both books."""
    spec = importlib.util.spec_from_file_location(
        "fetch_polymarket_props", ROOT / "scripts" / "fetch_polymarket_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def active_slate_window(now: datetime | None = None) -> bool:
    """True when a game sits within -1..+7 days of today (ET) — identical to
    check_odds_freshness's active-window rule. Unknown slate -> False
    (fail-closed: no credits spent on an unreadable slate)."""
    now = now or datetime.now(timezone.utc)
    try:
        index = json.loads(SLATE_INDEX.read_text(encoding="utf-8"))
        nfl = index["sports"]["nfl"]
        slate = nfl["slates"][nfl["default_slate"]]
        games = json.loads((VIEWER / slate["games"]).read_text(encoding="utf-8"))
    except Exception:
        return False
    today_et = now.astimezone(ZoneInfo("America/New_York")).date()
    return any(-1 <= (datetime.fromisoformat(g["gameday"]).date() - today_et).days <= 7
               for g in games)


def api_get(path: str, params: dict, key: str) -> tuple[object, str | None]:
    """One GET. Returns (json, x-requests-remaining). Raises RuntimeError with
    the status code so callers can fail closed without tracebacks."""
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode({**params, 'apiKey': key})}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            remaining = resp.headers.get("x-requests-remaining")
            return json.loads(resp.read().decode("utf-8")), remaining
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} from {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error on {path}: {exc}") from exc


def parse_bulk_quotes(payload: list, slate_idx: dict, observed_at: str,
                      sharp_books: set[str]) -> tuple[list[dict], int, list[str]]:
    """Pair Over/Under per (book, player, line) across the bulk response.

    Returns (rows, off_slate_skipped, book_keys_seen). Unpaired sides are
    dropped; off-slate players are skipped; nothing is fabricated."""
    rows: list[dict] = []
    off_slate = 0
    books_seen: set[str] = set()
    for event in payload if isinstance(payload, list) else []:
        for bm in event.get("bookmakers", []):
            book_key = str(bm.get("key") or "")
            if not book_key:
                continue
            books_seen.add(book_key)
            for mk in bm.get("markets", []):
                market = MARKETS.get(str(mk.get("key") or ""))
                if market is None:
                    continue
                sides: dict[tuple[str, float], dict] = {}
                for oc in mk.get("outcomes", []):
                    name = oc.get("description")
                    pt = oc.get("point")
                    if name is None or pt is None:
                        continue
                    sides.setdefault((str(name), float(pt)), {})[str(oc["name"]).lower()] = oc.get("price")
                for (player, line), px in sorted(sides.items()):
                    if "over" not in px or "under" not in px:
                        continue  # a one-sided book is not a quote
                    row = slate_idx.get(_norm_name(player))
                    if row is None:
                        off_slate += 1
                        continue
                    line_key = f"{line:g}".replace(".", "p")
                    rows.append({
                        "quote_id": f"oa_{event.get('id')}_{book_key}_{slug(player)}_{market}_{line_key}",
                        "provider_quote_id": f"{event.get('id')}:{book_key}:{slug(player)}:{mk.get('key')}:{line:g}",
                        "source_url": f"{BASE_URL}/sports/{SPORT}/odds",
                        "book": str(bm.get("title") or book_key),
                        "book_key": book_key,
                        "player_id": row["player_id"],
                        "player_name": row.get("player_display_name") or player,
                        "team": row.get("team") or "",
                        "opponent": row.get("opponent_team") or "",
                        "game_id": row.get("game_id") or "",
                        "market": market,
                        "line": line,
                        "over_odds": int(px["over"]),
                        "under_odds": int(px["under"]),
                        "observed_at": observed_at,
                        "source": SWEEP_SOURCE,
                        "verified": False,
                        "_fixture": False,
                        "sharp": book_key in sharp_books,
                        "event_id": str(event.get("id") or ""),
                        "commence_time": str(event.get("commence_time") or ""),
                    })
    return rows, off_slate, sorted(books_seen)


def merge_sweep(rows: list[dict], book_titles: list[str], sharp_present: list[str],
                feed_path: Path | None = None) -> bool:
    """Replace this sweep's previous rows, keep every other row untouched,
    republish atomically through the frozen contract. Fail-closed: any error
    leaves the feed byte-identical."""
    if feed_path is None:
        feed_path = FEED_PATH  # module global, resolved at call time (tests swap it)
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    prior_sweep = [q for q in feed.get("quotes", []) if q.get("source") == SWEEP_SOURCE]
    if not rows and not prior_sweep:
        print("[oddsapi] nothing to merge (no matched quotes, no stale sweep rows) — feed untouched")
        return False
    now = datetime.now(timezone.utc).isoformat()
    keep = [q for q in feed.get("quotes", []) if q.get("source") != SWEEP_SOURCE]
    keep.extend(rows)
    feed["quotes"] = keep
    feed["updated_at"] = now
    feed["total_quotes"] = len(keep)
    monitored = list(feed.get("monitored_books") or [])
    for title in book_titles:
        if title not in monitored:
            monitored.append(title)
    feed["monitored_books"] = monitored
    feed["oddsapi_quotes_count"] = len(rows)
    feed["oddsapi_observed_at"] = now
    feed["sharp_books_present"] = sharp_present
    # Polymarket rows, receipt stamps and feed_status pass through untouched.
    sys.path.insert(0, str(ROOT))
    from src.contracts.gate import validate_and_publish
    from src.contracts.polymarket import PolymarketMergedFeed
    published, _ = validate_and_publish(PolymarketMergedFeed, feed, feed_path,
                                        source_feed="the_odds_api_nfl_props")
    return published


def run(mode: str, min_remaining: int, slate_idx: dict | None = None,
        feed_path: Path | None = None) -> int:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("[oddsapi] no ODDS_API_KEY — sharp-book sweep skipped "
              "(Polymarket feed publishes regardless)", file=sys.stderr)
        return 0
    if mode == "off":
        print("[oddsapi] sweep mode 'off' — skipped by request")
        return 0
    if mode == "auto" and not active_slate_window():
        print("[oddsapi] no NFL game within the active seven-day window — "
              "sweep skipped (no credits spent)")
        return 0

    # Free probe first: validates the key AND reads the credit balance before
    # anything is spent.
    _, remaining = api_get(f"/sports/{SPORT}/events", {"dateFormat": "iso"}, key)
    try:
        remaining_n = int(remaining)
    except (TypeError, ValueError):
        remaining_n = None
    if remaining_n is not None and remaining_n < min_remaining:
        print(f"[oddsapi] only {remaining_n} credits remaining (floor {min_remaining}) — "
              f"sweep skipped before spending; check the plan tier", file=sys.stderr)
        return 0

    data, remaining = api_get(
        f"/sports/{SPORT}/odds",
        {"regions": "us", "markets": ",".join(MARKETS),
         "oddsFormat": "american", "dateFormat": "iso"},
        key)
    print(f"[oddsapi] bulk sweep spent {SWEEP_CREDIT_COST} credits; "
          f"remaining this month: {remaining}")

    pm = _load_pm_module()
    if slate_idx is None:
        slate_idx = pm.index_slate(pm.load_slate())
    observed_at = datetime.now(timezone.utc).isoformat()
    sharp_books = _sharp_books()
    rows, off_slate, books_seen = parse_bulk_quotes(data, slate_idx, observed_at, sharp_books)
    sharp_present = sorted(b for b in books_seen if b in sharp_books)
    print(f"[oddsapi] books seen: {books_seen} | sharp present: {sharp_present} | "
          f"matched quotes: {len(rows)} | off-slate skipped: {off_slate}")
    if not books_seen:
        print("[oddsapi] no bookmaker quoted these markets — feed untouched (fail-closed)",
              file=sys.stderr)
        return 0
    book_titles = sorted({r["book"] for r in rows})
    if merge_sweep(rows, book_titles, sharp_present, feed_path=feed_path):
        print(f"[oddsapi] merged {len(rows)} sportsbook quotes into {FEED_PATH.name} "
              f"({len(sharp_present)} sharp books present; VERIFIED stays engine-assigned only)")
    else:
        print("[oddsapi] merge published nothing — feed preserved (fail-closed)", file=sys.stderr)
    return 0


def selftest() -> int:
    """Offline checks with a synthetic payload SHAPED like the documented bulk
    response — never written to viewer/."""
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f" -> {detail}" if detail else ""))
        ok = ok and cond

    sharp_books = {"pinnacle", "betonlineag", "lowvig", "circasports"}
    slate_idx = {
        _norm_name("Puka Nacua"): {"player_id": "00-0039075",
                                   "player_display_name": "Puka Nacua",
                                   "team": "LA", "opponent_team": "LAC",
                                   "game_id": "2026_09_LA_LAC"},
    }
    payload = [{
        "id": "evt1", "commence_time": "2026-11-08T18:15:00Z",
        "bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -122, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 122, "point": 74.5},
                    {"name": "Over", "description": "Mystery Player", "price": -110, "point": 10.5},
                    {"name": "Under", "description": "Mystery Player", "price": -110, "point": 10.5}]},
                {"key": "player_receptions", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -105, "point": 4.5},
                    {"name": "Under", "description": "Puka Nacua", "price": -115, "point": 4.5}]}]},
            {"key": "draftkings", "title": "DraftKings", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -118, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 118, "point": 74.5},
                    {"name": "Over", "description": "Lonely Player", "price": -120, "point": 30.5}]}]},
            {"key": "lowvig", "title": "LowVig", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -120, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 120, "point": 74.5}]}]}],
    }]
    rows, off_slate, books_seen = parse_bulk_quotes(payload, slate_idx,
                                                    "2026-11-02T21:00:00+00:00", sharp_books)
    check("parse: 4 two-sided slate-matched quotes", len(rows) == 4, str(len(rows)))
    check("parse: off-slate player skipped", off_slate == 1, str(off_slate))
    check("parse: unpaired side dropped", not any("Lonely" in r["player_name"] for r in rows))
    check("parse: out-of-scope market skipped",
          not any(r["market"] not in ("receiving_yards", "receptions") for r in rows))
    check("parse: market keys mapped to slate ids",
          {r["market"] for r in rows} == {"receiving_yards", "receptions"})
    check("parse: books seen", books_seen == ["draftkings", "lowvig", "pinnacle"], str(books_seen))
    check("parse: sharp flags from frozen engine config",
          {r["book_key"] for r in rows if r["sharp"]} == {"pinnacle", "lowvig"})
    check("parse: no verification claim on any row",
          all(r["verified"] is False and r["source"] == SWEEP_SOURCE for r in rows))
    check("parse: quote ids unique", len({r["quote_id"] for r in rows}) == len(rows))

    # merge: replace-only-own-rows, keep polymarket + synthetic, contract-safe
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    feed_path = tmp / "live_odds_feed.json"
    pm_row = {"quote_id": "pm_x", "book": "Polymarket", "player_id": "00-0039075",
              "market": "receiving_yards", "line": 74.5, "observed_at": "2026-11-02T12:00:00Z",
              "receipt_id": "pm_x", "content_hash": "a" * 64,
              "source_url": "https://polymarket.com/market/x",
              "over_odds": -110, "under_odds": 110, "liquidity_usd": 50.0,
              "over_token_id": "o", "under_token_id": "u",
              "over_ask_price": 0.55, "under_ask_price": 0.45,
              "over_ask_depth_usd": 50.0, "under_ask_depth_usd": 60.0,
              "verification_status": "OBSERVED", "verification_engine": "verification.v1",
              "verification_receipt_id": "pmr_" + "a" * 16, "verification_clauses": []}
    syn_row = {"quote_id": "syn_a", "book": "Synthetic Book A",
               "source": "Synthetic Book A Manual Entry (UNVERIFIED - harness fixture)"}
    feed_path.write_text(json.dumps({
        "feed_status": "LIVE_POLYMARKET_CLOB_RECEIPTED",
        "updated_at": "2026-11-02T21:00:00Z",
        "quotes": [pm_row, syn_row], "monitored_books": ["Polymarket"],
        "total_quotes": 2, "polymarket_quotes_count": 1,
        "receipt_matched_quotes_count": 1,
    }), encoding="utf-8")
    globals()["FEED_PATH"] = feed_path
    published = merge_sweep(rows, ["Pinnacle", "DraftKings", "LowVig"], ["lowvig", "pinnacle"],
                            feed_path=feed_path)
    check("merge: published through the frozen contract", published is True)
    merged = json.loads(feed_path.read_text(encoding="utf-8"))
    pm_rows = [q for q in merged["quotes"] if q["book"] == "Polymarket"]
    check("merge: polymarket row + stamps preserved byte-for-byte",
          len(pm_rows) == 1 and pm_rows[0] == pm_row)
    check("merge: synthetic row preserved", any(q["book"] == "Synthetic Book A" for q in merged["quotes"]))
    check("merge: counts consistent", merged["total_quotes"] == len(merged["quotes"]) == 6)
    check("merge: sharp_books_present recorded",
          merged["sharp_books_present"] == ["lowvig", "pinnacle"])
    check("merge: monitored books extended", "Pinnacle" in merged["monitored_books"])
    # idempotency: re-sweep replaces own rows only
    rows2 = [dict(r, over_odds=r["over_odds"] - 1) for r in rows]
    merge_sweep(rows2, ["Pinnacle", "DraftKings", "LowVig"], ["lowvig", "pinnacle"],
                feed_path=feed_path)
    merged2 = json.loads(feed_path.read_text(encoding="utf-8"))
    sweep_rows = [q for q in merged2["quotes"] if q.get("source") == SWEEP_SOURCE]
    check("merge: re-sweep replaces own rows (no duplication)",
          len(sweep_rows) == 4 and merged2["total_quotes"] == 6)
    # empty result WITH prior rows -> dead rows honestly dropped
    merge_sweep([], [], [], feed_path=feed_path)
    merged3 = json.loads(feed_path.read_text(encoding="utf-8"))
    check("merge: dead sweep rows dropped when provider goes quiet",
          not any(q.get("source") == SWEEP_SOURCE for q in merged3["quotes"])
          and merged3["total_quotes"] == 2)

    print("fetch_nfl_props_sweep selftest: ALL PASS" if ok else "fetch_nfl_props_sweep selftest: FAILURES")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["auto", "force", "off"], default="auto",
                    help="auto: sweep only in the active slate window; force: sweep now; off: skip")
    ap.add_argument("--min-remaining", type=int, default=100,
                    help="skip the sweep when monthly credits remaining fall below this floor")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    try:
        return run(args.mode, args.min_remaining)
    except RuntimeError as exc:
        print(f"[oddsapi] sweep failed closed ({exc}) — feed untouched; "
              f"Polymarket publication proceeds", file=sys.stderr)
        return 0


# Name normalisation shared with the Polymarket fetcher (bound lazily so the
# module stays importable without the repo layout in tests that stub it).
_NORM = None


def _norm_name(name: str) -> str:
    global _NORM
    if _NORM is None:
        _NORM = _load_pm_module()._norm_name
    return _NORM(name)


if __name__ == "__main__":
    sys.exit(main())
