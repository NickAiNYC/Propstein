#!/usr/bin/env python3
"""
De-identification transform for bundled demo fixtures (provenance hotfix).

Idempotent: running twice yields byte-identical output (mappings use identity
fallbacks for already-synthetic values; timestamps are deterministic per
quote index).

What it does (fail-closed by design):
  1. Root + viewer live_odds_feed.json:
     - real players  -> Player A..G (ids SYN-A..SYN-G)
     - real books    -> Synthetic Book A..D
     - quote ids     -> syn_<bookletter>_<game>_player_<letter>_<mkt>_open
     - sources       -> "<book> Manual Entry (UNVERIFIED - demonstration fixture)"
     - one shared observation stamp -> 10 distinct deterministic stamps
     - the +32% phantom-EV quote (book line 29.5 vs fair 45.5) becomes the
       efficient-market case: line == fair == 45.5, edge 0.0, PASS, stake 0.
       Numeric market data is otherwise preserved.
     - viewer export: source_url/receipt_id neutralized, verified stays False.
  2. picks_log.jsonl:
     - real players  -> Player H..M (ledger namespace continues after G)
     - real books    -> Synthetic Book A..E
     - is_demo/status demo markers kept; numeric clv/line payload preserved.
     - NOTE: this file is UNTRACKED in git (runtime data); `git rm --cached`
       is done by the caller, not here.

The demo quotes intentionally can never match the real slate ("Player A" is
not a slate player_id), so no downstream evaluation path can treat them as
actionable. monitored_books stays real by decision: it is the watchlist
config sitting next to verified_books_count: 0, not a claim about this data.
The embedded `slate` array stays real for the same reason: it mirrors the
actual slate input files, it is not a quote-attribution claim.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BOOK_MAP = {
    "DraftKings": "Synthetic Book A",
    "FanDuel": "Synthetic Book B",
    "BetMGM": "Synthetic Book C",
    "Pinnacle": "Synthetic Book D",
    "Circa": "Synthetic Book E",
}
PLAYER_MAP = {  # feed quotes: real name -> (Player X, SYN-X)
    "DeMario Douglas": ("Player A", "SYN-A"),
    "Hunter Henry": ("Player B", "SYN-B"),
    "Mack Hollins": ("Player C", "SYN-C"),
    "George Kittle": ("Player D", "SYN-D"),
    "Christian McCaffrey": ("Player E", "SYN-E"),
    "A.J. Brown": ("Player F", "SYN-F"),
    "Amon-Ra St. Brown": ("Player G", "SYN-G"),
}
LEDGER_PLAYER_MAP = {  # picks_log.jsonl: real name -> Player H..M
    "Ja'Marr Chase": "Player H",
    "Amon-Ra St. Brown": "Player I",
    "Chris Olave": "Player J",
    "Justin Jefferson": "Player K",
    "Trey McBride": "Player L",
    "Puka Nacua": "Player M",
}
ID_BOOK_PREFIX = {"dk": "syn_a", "fd": "syn_b", "mgm": "syn_c", "pin": "syn_d"}
ID_PLAYER_TOKEN = {
    "douglas": "player_a", "henry": "player_b", "hollins": "player_c",
    "kittle": "player_d", "cmc": "player_e", "ajb": "player_f",
    "amonra": "player_g",
}

EFFICIENT_EVALUATION = {  # the former Hollins slot: honest no-edge case
    "is_qualified": False,
    "status": "PASS",
    "best_side": "OVER",
    "prob_edge": 0.0,
    "break_even_adv": -0.0238,   # be(-110, no push) = 0.5238 -> 0.5 - 0.5238
    "expected_return": -0.0455,  # 1.9091*0.5 - 1 at -110/-110
    "actionable_stake": 0.0,
    "catalyst": "pricing",
    "injury_context": "Teammate WR (Shoulder OUT) - synthetic context",
}

_TS_BASE = datetime(2026, 10, 20, 6, 23, 18, tzinfo=timezone.utc)


def _ts(i: int) -> str:
    """Deterministic, distinct observation stamp per quote index."""
    return (_TS_BASE + timedelta(seconds=61 * i + 17, microseconds=137 * i)
            ).isoformat()


def map_quote_id(old_id: str) -> str:
    new = old_id
    for old_prefix, new_prefix in ID_BOOK_PREFIX.items():
        if new.startswith(old_prefix + "_"):
            new = new_prefix + new[len(old_prefix):]
            break
    for tok, repl in ID_PLAYER_TOKEN.items():
        if f"_{tok}_" in new:
            new = new.replace(f"_{tok}_", f"_{repl}_")
    return new


def is_hollins_slot(q: dict) -> bool:
    qid = q.get("quote_id", "")
    return "hollins" in qid or "player_c" in qid


def transform_feed(path: Path, viewer: bool) -> None:
    data = json.loads(path.read_text())
    for i, q in enumerate(data["quotes"]):
        q["quote_id"] = map_quote_id(q.get("quote_id", q.get("provider_quote_id", "")))
        if viewer and "provider_quote_id" in q:
            q["provider_quote_id"] = q["quote_id"]
        name = q.get("player_name", "")
        if name in PLAYER_MAP:
            q["player_name"], q["player_id"] = PLAYER_MAP[name]
        if q.get("book") in BOOK_MAP:
            q["book"] = BOOK_MAP[q["book"]]
        q["source"] = f"{q['book']} Manual Entry (UNVERIFIED - demonstration fixture)"
        q["observed_at"] = _ts(i)
        if viewer:
            q["verified"] = False
            q["source_url"] = ""
            q["receipt_id"] = ""
        if is_hollins_slot(q):
            q["line"] = q["fair_line"] = 45.5
            q["over_odds"] = q["under_odds"] = -110
            q["evaluation"] = dict(EFFICIENT_EVALUATION)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    stamps = {q["observed_at"] for q in data["quotes"]}
    print(f"{path.name}: {len(data['quotes'])} quotes, {len(stamps)} distinct stamps")


def transform_ledger(path: Path) -> None:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    for r in rows:
        if r.get("player") in LEDGER_PLAYER_MAP:
            r["player"] = LEDGER_PLAYER_MAP[r["player"]]
        if r.get("book") in BOOK_MAP:
            r["book"] = BOOK_MAP[r["book"]]
        r["is_demo"] = True
        r["status"] = "demo"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"picks_log.jsonl: {len(rows)} rows de-identified (Player H..M)")


if __name__ == "__main__":
    transform_feed(ROOT / "live_odds_feed.json", viewer=False)
    transform_feed(ROOT / "viewer" / "live_odds_feed.json", viewer=True)
    transform_ledger(ROOT / "picks_log.jsonl")
    sys.exit(0)
