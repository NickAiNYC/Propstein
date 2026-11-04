#!/usr/bin/env python3
"""Fail when the active week's unstarted games lack pre-cutoff context.

The nflverse ``data/games.csv`` download is gitignored, so CI judges the
committed journal plus a fresh schedule download. Exit 1 is the pricing-time
alert: spread, total, or weather is missing, naive, or later than kickoff.
A week that has already kicked off is not a failure. Stale-but-valid captures
are reported and do not by themselves fail the check.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from scripts.ingest_espn_game_context import (
    ET,
    NFLVERSE_GAMES_URL,
    evaluate_pricing_context,
    format_provenance_report,
    load_journal,
    load_schedule_rows,
    write_provenance_report,
)


def fetch_schedule(dest: Path) -> None:
    req = urllib.request.Request(NFLVERSE_GAMES_URL, headers={"User-Agent": "PropSteinGameContext/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alert when pregame context is missing at pricing time")
    parser.add_argument("--games-csv", type=Path, default=None, help="Schedule CSV (default: download nflverse)")
    parser.add_argument("--now", default=None, help="ISO timestamp override, used by tests")
    parser.add_argument("--write-report", action="store_true", help="Rewrite data/game_context_provenance_report.json")
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now).astimezone(ET) if args.now else datetime.now(ET)
    failed: list[str] = []
    schedule_path = args.games_csv
    temporary = None
    if schedule_path is None:
        temporary = Path("/tmp/propstein_nflverse_games.csv")
        try:
            fetch_schedule(temporary)
            schedule_path = temporary
        except Exception as exc:
            failed.append(f"schedule fetch failed: {exc}")
            print(f"game-context provenance\n  pricing: BLOCKED\n  - fetch failed: {failed[0]}")
            return 1

    try:
        schedule = load_schedule_rows(schedule_path)
    except Exception as exc:
        print(f"game-context provenance\n  pricing: BLOCKED\n  - fetch failed: unreadable schedule: {exc}")
        return 1

    journal = load_journal()
    report = evaluate_pricing_context(schedule, journal, now, failed_fetches=failed)
    print(format_provenance_report(report))
    if args.write_report:
        write_provenance_report(report)
    if not report["ready_for_pricing"]:
        print("PROVENANCE_ALERT: required game context is missing at pricing time", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
