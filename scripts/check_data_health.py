#!/usr/bin/env python3
"""Daily data-health report: catch the silent failures per-job alarms miss.

Each data job only checks its own output, and several fail soft on purpose
(the NFL sportsbook sweep always exits 0 so Polymarket still publishes). In
November 2026 that let the shared Odds API key run dry and NBA lines stop for
days with no alarm. This report looks at the published files and the key's
balance together and fails when anything a user would see is stale.

    python scripts/check_data_health.py [--summary path.md] [--now ISO]

Checks (each OK / WARN / FAIL / SKIP):
  odds_api_credits   remaining credits on ODDS_API_KEY, read from the free
                     /v4/sports endpoint (costs 0 credits). The key is never
                     printed. FAIL at 0 or when the provider refuses the key.
  nba_lines          newest real nba_odds_<date>.json during the NBA season
                     must be younger than --nba-max-age-hours.
  nfl_odds_feed      live_odds_feed.json age during an active NFL window.
  nfl_sportsbook     sportsbook (non-Polymarket) quotes present during an
                     active NFL window. WARN only: the board works without them.
  nfl_injuries       current week's injury report age during an active window.

Exit 1 when any check FAILs. Never edits data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
ET = ZoneInfo("America/New_York")
ODDS_API_SPORTS_URL = "https://api.the-odds-api.com/v4/sports"
#: Rows the NFL sweep writes carry this source (scripts/fetch_nfl_props_sweep.py).
SWEEP_SOURCE = "The Odds API (unverified sportsbook quote)"
NBA_ODDS_RE = re.compile(r"nba_odds_(\d{4}-\d{2}-\d{2})\.json$")


@dataclass
class Result:
    name: str
    status: str  # OK | WARN | FAIL | SKIP
    detail: str


def parse_time(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no timezone")
    return parsed.astimezone(timezone.utc)


def hours_since(value, now: datetime) -> float:
    return (now - parse_time(value)).total_seconds() / 3600


def age_label(hours: float) -> str:
    return f"{hours:.1f}h" if hours < 48 else f"{hours / 24:.1f} days"


# ---- Odds API balance ------------------------------------------------------

def fetch_sports_endpoint(key: str):
    """GET /v4/sports (free). Returns (status_code, headers, body_text)."""
    url = f"{ODDS_API_SPORTS_URL}?apiKey={key}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status, dict(resp.headers), ""
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()[:300].decode("utf-8", "replace")


def check_odds_api_credits(key: str | None, fetch=fetch_sports_endpoint,
                           warn_below: int = 50) -> Result:
    name = "odds_api_credits"
    if not key:
        return Result(name, "SKIP", "ODDS_API_KEY not available to this job")
    try:
        status, headers, body = fetch(key)
    except Exception as exc:  # network trouble is not a quota verdict
        msg = str(exc).replace(key, "***")
        return Result(name, "WARN", f"could not reach The Odds API: {msg[:160]}")
    headers = {k.lower(): v for k, v in headers.items()}
    if status in (401, 403, 429):
        reason = "out of credits" if "OUT_OF_USAGE_CREDITS" in body or "quota" in body.lower() else f"HTTP {status}"
        return Result(name, "FAIL", f"provider refused the key ({reason}); every Odds API job is down "
                                    "until the plan resets or is upgraded")
    if status != 200:
        return Result(name, "WARN", f"unexpected HTTP {status} from /v4/sports")
    remaining = headers.get("x-requests-remaining")
    used = headers.get("x-requests-used")
    try:
        left = int(float(remaining))
    except (TypeError, ValueError):
        return Result(name, "WARN", "response had no x-requests-remaining header")
    detail = f"{left} credits remaining" + (f", {used} used this period" if used else "")
    if left <= 0:
        return Result(name, "FAIL", detail + "; every Odds API job is down")
    if left < warn_below:
        return Result(name, "WARN", detail + f" (below {warn_below})")
    return Result(name, "OK", detail)


# ---- NBA -----------------------------------------------------------------

def nba_in_season(day: date) -> bool:
    """Regular season + playoffs: late October through mid June."""
    return (day.month == 10 and day.day >= 20) or day.month in (11, 12, 1, 2, 3, 4, 5) \
        or (day.month == 6 and day.day <= 20)


def check_nba_lines(viewer: Path, now: datetime, max_age_hours: float = 48) -> Result:
    name = "nba_lines"
    today = now.astimezone(ET).date()
    if not nba_in_season(today):
        return Result(name, "SKIP", "outside the NBA season")
    newest = None
    for path in viewer.glob("nba_odds_*.json"):
        match = NBA_ODDS_RE.fullmatch(path.name)
        if not match:
            continue
        try:
            feed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if feed.get("_fixture") is not False or not feed.get("updated_at"):
            continue
        try:
            observed = parse_time(feed["updated_at"])
        except ValueError:
            continue
        if newest is None or observed > newest[0]:
            newest = (observed, match.group(1), int(feed.get("total_quotes") or 0))
    if newest is None:
        return Result(name, "FAIL", "no real (non-fixture) NBA odds file published this season")
    observed, slate, quotes = newest
    age = (now - observed).total_seconds() / 3600
    detail = f"newest slate {slate}, {quotes} quotes, updated {age_label(age)} ago"
    if age > max_age_hours:
        return Result(name, "FAIL", detail + f" (limit {max_age_hours:.0f}h); the NBA board shows no current slate")
    return Result(name, "OK", detail)


# ---- NFL -----------------------------------------------------------------

def nfl_current_slate(viewer: Path):
    index = json.loads((viewer / "feeds/slate-index.json").read_text(encoding="utf-8"))
    nfl = index["sports"]["nfl"]
    key = nfl.get("default_slate")
    return (key, nfl["slates"][key]) if key and key in nfl["slates"] else (None, None)


def nfl_active(viewer: Path, slate: dict, now: datetime) -> bool:
    """Same rule as check_odds_freshness: a game within -1..+7 ET days."""
    games = json.loads((viewer / slate["games"]).read_text(encoding="utf-8"))
    today = now.astimezone(ET).date()
    return any(-1 <= (date.fromisoformat(str(g["gameday"])[:10]) - today).days <= 7 for g in games)


def check_nfl(viewer: Path, now: datetime, feed_max_age_hours: float = 6,
              injuries_max_age_hours: float = 36) -> list[Result]:
    try:
        key, slate = nfl_current_slate(viewer)
    except (OSError, ValueError, KeyError) as exc:
        return [Result("nfl_odds_feed", "FAIL", f"slate index unreadable: {exc}")]
    if not slate:
        return [Result("nfl_odds_feed", "SKIP", "no current NFL slate")]
    try:
        active = nfl_active(viewer, slate, now)
    except (OSError, ValueError, KeyError) as exc:
        return [Result("nfl_odds_feed", "FAIL", f"{key} games file unreadable: {exc}")]
    if not active:
        return [Result("nfl_odds_feed", "SKIP", f"{key}: no game within the active window")]

    results = []
    try:
        feed = json.loads((viewer / "live_odds_feed.json").read_text(encoding="utf-8"))
        age = hours_since(feed["updated_at"], now)
        status = "FAIL" if age > feed_max_age_hours else "OK"
        results.append(Result("nfl_odds_feed", status,
                              f"{feed.get('polymarket_quotes_count', 0)} Polymarket quotes, "
                              f"updated {age_label(age)} ago (limit {feed_max_age_hours:.0f}h)"))
        books = sum(1 for q in feed.get("quotes", []) if q.get("source") == SWEEP_SOURCE)
        results.append(Result("nfl_sportsbook", "OK" if books else "WARN",
                              f"{books} sportsbook quotes in the feed" if books else
                              "0 sportsbook quotes; the board is Polymarket-only (sweep failing or out of credits)"))
    except (OSError, ValueError, KeyError) as exc:
        results.append(Result("nfl_odds_feed", "FAIL", f"live_odds_feed.json unreadable: {exc}"))

    if slate.get("injuries"):
        try:
            report = json.loads((viewer / slate["injuries"]).read_text(encoding="utf-8"))
            age = hours_since(report["as_of"], now)
            results.append(Result("nfl_injuries", "FAIL" if age > injuries_max_age_hours else "OK",
                                  f"{slate['injuries']} as of {age_label(age)} ago "
                                  f"(limit {injuries_max_age_hours:.0f}h)"))
        except (OSError, ValueError, KeyError) as exc:
            results.append(Result("nfl_injuries", "FAIL", f"{slate['injuries']} unreadable: {exc}"))
    else:
        results.append(Result("nfl_injuries", "WARN", f"{key} has no injury report registered"))
    return results


# ---- report --------------------------------------------------------------

def run_checks(viewer: Path, now: datetime, key: str | None, fetch=fetch_sports_endpoint,
               nba_max_age_hours: float = 48) -> list[Result]:
    return [check_odds_api_credits(key, fetch),
            check_nba_lines(viewer, now, nba_max_age_hours),
            *check_nfl(viewer, now)]


def render(results: list[Result], now: datetime) -> str:
    icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "➖"}
    lines = [f"## PropStein data health · {now.strftime('%Y-%m-%d %H:%M')} UTC", "",
             "| Check | Status | Detail |", "|---|---|---|"]
    lines += [f"| `{r.name}` | {icon[r.status]} {r.status} | {r.detail} |" for r in results]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--summary", help="append the markdown report to this file")
    ap.add_argument("--now", help="evaluate as of this ISO timestamp (testing)")
    ap.add_argument("--nba-max-age-hours", type=float, default=48)
    ap.add_argument("--viewer", default=str(VIEWER))
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    results = run_checks(Path(args.viewer), now, os.environ.get("ODDS_API_KEY", "").strip() or None,
                         nba_max_age_hours=args.nba_max_age_hours)
    report = render(results, now)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    failed = [r.name for r in results if r.status == "FAIL"]
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
