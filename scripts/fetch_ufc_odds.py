#!/usr/bin/env python3
"""fetch_ufc_odds.py - PropStein UFC pipeline (card + odds + model + status + grading).

  python3 scripts/fetch_ufc_odds.py                 # card + model + status, odds only if within 48h and key set
  python3 scripts/fetch_ufc_odds.py --no-odds       # never spend credits
  python3 scripts/fetch_ufc_odds.py --snapshot pre|post|lock   # fight-week snapshots (freeze_ufc.yml)
  python3 scripts/fetch_ufc_odds.py --grade         # grade finished cards -> viewer/ufc_ledger.json

Writes (viewer/): ufc_card_<date>.json, ufc_status_<date>.json, ufc_snapshots_<date>.json,
ufc_fighters.json, ufc_ledger.json. <date> = US-Eastern date of the card's first fight.

Sources: ESPN public UFC scoreboard (card, results, bios; UFC-only by construction) and
The Odds API mma_mixed_martial_arts h2h+totals, 1 region (2 credits per pull). Odds events
that do not match a fighter pair on the ESPN UFC card (PFL, ONE, ...) are dropped.
Exit codes: 0 ok - 4 credit budget exceeded - 5 network/API error.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ufc import espn, odds as uodds  # noqa: E402
from src.ufc.common import HONESTY_LABEL, prob_to_american  # noqa: E402
from src.ufc.grade import grade_card, summarize  # noqa: E402
from src.ufc.ratings import Ratings, backtest  # noqa: E402
from src.ufc.status import apply_overrides, diff_status, is_void  # noqa: E402

VIEWER = ROOT / "viewer"
DATA = ROOT / "data"
ET = ZoneInfo("America/New_York")
HISTORY = DATA / "ufc_history.json"
ATHLETES = DATA / "ufc_athletes.json"
FIRST_YEAR = 2020
LOCK_WINDOW_MIN = 60


def now_utc() -> datetime:
    env = os.environ.get("PROPSTEIN_NOW", "").strip()
    return datetime.fromisoformat(env).astimezone(timezone.utc) if env else datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_history(now: datetime) -> list[dict]:
    cached = read_json(HISTORY, {})
    if cached and time.time() - cached.get("fetched_epoch", 0) < 20 * 3600:
        return cached["fights"]
    fights: list[dict] = []
    for yr in range(FIRST_YEAR, now.year + 1):
        try:
            fights.extend(espn.fetch_range(str(yr)))
        except Exception as exc:  # fail-open: keep what we have
            print(f"  [warn] ESPN history {yr} failed: {exc}", file=sys.stderr)
    if fights:
        write_json(HISTORY, {"fetched_epoch": time.time(), "fights": fights})
    return fights or cached.get("fights", [])


def load_bios(ids: list[str]) -> dict:
    cache = read_json(ATHLETES, {})
    for aid in ids:
        if aid not in cache:
            cache[aid] = espn.fetch_athlete(aid)
    write_json(ATHLETES, cache)
    return cache


def card_date(fights: list[dict]) -> str:
    t = espn._parse_ts(fights[0]["start"])
    return t.astimezone(ET).strftime("%Y-%m-%d")


def build_card(card_fights, history, ratings, bios, market, status, now) -> dict:
    fights_out = []
    for f in card_fights:
        model = ratings.win_prob(f, bios)
        mk = market.get(f["fight_id"])
        totals = []
        for t in (mk or {}).get("totals", []):
            totals.append({"line": t["line"], "p_over_novig": t["p_over_novig"],
                           "model_p_over": ratings.p_over(f, t["line"]), "books": t["books"]})
        st = status.get(f["fight_id"], {"status": "scheduled"})
        fights_out.append({
            **{k: f[k] for k in ("fight_id", "start", "weight_class", "sched_rounds", "result",
                                 "end_round", "went_distance")},
            "fighters": [{**x, **{k: bios.get(x["id"], {}).get(k) for k in ("age", "reach_in", "stance", "headshot")}}
                         for x in f["fighters"]],
            "model": {**model, "fair_american": [prob_to_american(p) for p in model["p"]],
                      "p_finish": round(ratings.p_finish(f), 4),
                      "p_over_by_line": {str(l): ratings.p_over(f, l) for l in (1.5, 2.5, 3.5, 4.5)
                                         if l < f["sched_rounds"]}},
            "market": ({"h2h_novig": mk["h2h_novig"], "best": mk["best"], "books": mk["books"],
                        "odds_event_id": mk["odds_event_id"]} if mk else None),
            "totals": totals,
            "status": st.get("status"), "status_events": st.get("events", []),
            "short_notice": bool(st.get("short_notice")),
            "void": is_void(status, f["fight_id"]),
            "edge": "NO EDGE",
        })
    return {
        "schema_version": "ufc-card.v1", "sport": "ufc",
        "generated_at": iso(now), "event_id": card_fights[0]["event_id"],
        "event_name": card_fights[0]["event_name"], "date": card_date(card_fights),
        "honesty": HONESTY_LABEL,
        "sources": {"card": "ESPN UFC scoreboard", "odds": "The Odds API (mma_mixed_martial_arts: h2h, totals; region us)"},
        "fights": fights_out,
    }


def pull_market(card_fights, now, max_credits) -> tuple[dict, dict]:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        return {}, {"skipped": "no ODDS_API_KEY"}
    starts = [espn._parse_ts(f["start"]) for f in card_fights]
    t0, t1 = min(starts) - timedelta(hours=12), max(starts) + timedelta(hours=12)
    events, meter = uodds.fetch_odds(key, iso(t0), iso(t1), max_credits=max_credits)
    market, matched = {}, set()
    for f in card_fights:
        ev = uodds.match_event(f, events)
        if ev:
            market[f["fight_id"]] = uodds.summarize_event(f, ev)
            matched.add(ev.get("id"))
    meter.update({"events_returned": len(events), "ufc_matched": len(matched),
                  "non_ufc_dropped": len(events) - len(matched)})
    print(f"[ufc] odds: {len(events)} MMA events, {len(matched)} matched to UFC card, "
          f"{meter['cost_measured']} credits used, {meter['remaining']} remaining")
    return market, meter


def run(args) -> int:
    now = now_utc()
    history = load_history(now)
    try:
        upcoming = espn.fetch_range(f"{(now - timedelta(days=1)):%Y%m%d}-{(now + timedelta(days=21)):%Y%m%d}")
    except Exception as exc:
        print(f"[ufc] ESPN card fetch failed: {exc}", file=sys.stderr)
        return 5
    card_fights = espn.next_card(upcoming, now)
    if not card_fights:
        print("[ufc] no upcoming UFC card in the next 21 days")
        return 0
    date = card_date(card_fights)
    print(f"[ufc] next card: {card_fights[0]['event_name']} ({date}, {len(card_fights)} fights)")
    card_path = VIEWER / f"ufc_card_{date}.json"
    status_path = VIEWER / f"ufc_status_{date}.json"
    snaps_path = VIEWER / f"ufc_snapshots_{date}.json"
    prev = read_json(card_path, {})
    status = diff_status(prev.get("fights", []), card_fights, read_json(status_path, {}).get("fights", {}), now)
    status = apply_overrides(status, read_json(VIEWER / "ufc_status_overrides.json", {}).get(date, {}))

    ids = [x["id"] for f in card_fights for x in f["fighters"]]
    bios = load_bios(ids)
    ratings = Ratings().fit([h for h in history if h["event_id"] != card_fights[0]["event_id"]])

    first = min(espn._parse_ts(f["start"]) for f in card_fights)
    want_odds = not args.no_odds and (args.snapshot or first - now <= timedelta(hours=48))
    lock_targets = set()
    if args.snapshot == "lock":
        snaps = read_json(snaps_path, {})
        for f in card_fights:
            t = espn._parse_ts(f["start"])
            if (timedelta(0) <= t - now <= timedelta(minutes=LOCK_WINDOW_MIN)
                    and "lock" not in snaps.get(f["fight_id"], {}) and not is_void(status, f["fight_id"])):
                lock_targets.add(f["fight_id"])
        if not lock_targets:
            print("[ufc] lock: no fight starts within the lock window - no API call")
            want_odds = False
    market, meter = {}, {"skipped": "outside 48h window or --no-odds"}
    if want_odds:
        try:
            market, meter = pull_market(card_fights, now, args.max_credits)
        except uodds.BudgetExceeded as exc:
            print(f"[ufc] budget guard: {exc}", file=sys.stderr)
            return 4
        except Exception as exc:
            print(f"[ufc] odds pull failed ({exc}) - card written without market", file=sys.stderr)
            meter = {"error": str(exc)}
    if not market and prev:  # keep last good market quotes, flagged stale by generated time
        market = {f["fight_id"]: {**f["market"], "totals": [
            {"line": t["line"], "p_over_novig": t["p_over_novig"], "books": t["books"]} for t in f.get("totals", [])]}
            for f in prev.get("fights", []) if f.get("market")}
        if market:
            meter["market_from"] = prev.get("market_as_of") or prev.get("generated_at")

    card = build_card(card_fights, history, ratings, bios, market, status, now)
    card["odds_meter"] = meter
    card["market_as_of"] = iso(now) if "cost_measured" in meter else meter.get("market_from")
    card["backtest"] = backtest(history)
    write_json(card_path, card)
    write_json(status_path, {"date": date, "event_id": card["event_id"], "updated_at": iso(now), "fights": status})

    if args.snapshot and "cost_measured" in meter:
        snaps = read_json(snaps_path, {})
        for f in card_fights:
            fid = f["fight_id"]
            if fid not in market or is_void(status, fid):
                continue
            if args.snapshot == "lock" and fid not in lock_targets:
                continue
            slot = snaps.setdefault(fid, {})
            if args.snapshot in slot:
                continue  # never overwrite a captured point
            slot[args.snapshot] = {"at": iso(now), "h2h_novig": market[fid]["h2h_novig"],
                                   "best": market[fid]["best"], "totals": market[fid]["totals"]}
        write_json(snaps_path, snaps)
        print(f"[ufc] snapshot {args.snapshot}: {sum(1 for v in snaps.values() if args.snapshot in v)} fights")

    write_fighters(card_fights, ratings, bios)
    print(f"[ufc] wrote {card_path.name}, {status_path.name}, ufc_fighters.json")
    return 0


def write_fighters(card_fights, ratings: Ratings, bios: dict) -> None:
    out = read_json(VIEWER / "ufc_fighters.json", {})
    for f in card_fights:
        for x in f["fighters"]:
            fid = x["id"]
            fin = ratings.fin.get(fid, [0, 0])
            out[fid] = {"id": fid, "name": x["name"], "record": x.get("record"), "flag": x.get("flag"),
                        **bios.get(fid, {}), "elo": round(ratings.rating(fid), 1),
                        "ufc_fights": ratings.n.get(fid, 0),
                        "finish_rate": round(fin[0] / fin[1], 3) if fin[1] else None,
                        "recent": list(reversed(ratings.hist.get(fid, [])[-8:]))}
    write_json(VIEWER / "ufc_fighters.json", out)


def grade(args) -> int:
    now = now_utc()
    graded = []
    for p in sorted(glob.glob(str(VIEWER / "ufc_card_*.json"))):
        card = read_json(Path(p), {})
        date = card.get("date")
        if not date or date > now.astimezone(ET).strftime("%Y-%m-%d"):
            continue
        snaps = read_json(VIEWER / f"ufc_snapshots_{date}.json", {})
        status = read_json(VIEWER / f"ufc_status_{date}.json", {}).get("fights", {})
        try:
            res = {f["fight_id"]: f for f in espn.fetch_range(date.replace("-", ""))}
        except Exception as exc:
            print(f"  [warn] results for {date} unavailable: {exc}", file=sys.stderr)
            res = {}
        graded.append(grade_card(card, snaps, res, status))
    ledger = {"generated_at": iso(now), "rules": "draw/NC/cancel/scratch = void (push); CLV vs lock snapshot only",
              "summary": summarize(graded), "cards": graded}
    write_json(VIEWER / "ufc_ledger.json", ledger)
    print(f"[ufc] ledger: {ledger['summary']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-odds", action="store_true")
    ap.add_argument("--snapshot", choices=["pre", "post", "lock"])
    ap.add_argument("--grade", action="store_true")
    ap.add_argument("--max-credits", type=int, default=4)
    args = ap.parse_args()
    return grade(args) if args.grade else run(args)


if __name__ == "__main__":
    sys.exit(main())
