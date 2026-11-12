#!/usr/bin/env python3
"""Repo-only 2026-W10 readiness check. Does not query Postgres."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "viewer" / "games_2026_w10.json"
ET = ZoneInfo("America/New_York")
REFUSAL = "No close tape source that can prove captured_at < kickoff_at"


def kickoff(game: dict) -> datetime:
    hour, minute = game["gametime"].split(":")
    local = datetime(
        *map(int, game["gameday"].split("-")),
        int(hour),
        int(minute),
        tzinfo=ET,
    )
    return local.astimezone(ZoneInfo("UTC"))


def main() -> int:
    games = json.loads(GAMES.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo("UTC"))
    future = 0
    for game in games:
        when = kickoff(game)
        if when <= now:
            print(f"FAIL past kickoff {game['game_id']} {when.strftime('%Y-%m-%dT%H:%M:%SZ')}", file=sys.stderr)
            return 1
        future += 1
    cron = subprocess.check_output(
        ["git", "show", "HEAD:src/closing_snapshot_cron.py"],
        cwd=ROOT,
        text=True,
    )
    needed = (
        "ADD COLUMN IF NOT EXISTS kickoff_at TIMESTAMPTZ",
        "ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ",
        "def prove_close_times",
    )
    if any(token not in cron for token in needed):
        print("FAIL cron HEAD missing kickoff_at, captured_at, or prove_close_times", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    emit = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "emit_close_tape.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if emit.returncode != 0 or emit.stdout.strip() != REFUSAL:
        print("FAIL emit_close_tape did not refuse", file=sys.stderr)
        return 1
    print(f"W10 future kickoffs: {future}/{len(games)}")
    print("cron HEAD: kickoff_at captured_at prove_close_times")
    print(f"emit_close_tape: {REFUSAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
