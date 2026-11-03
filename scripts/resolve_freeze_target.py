#!/usr/bin/env python3
"""Resolve the active NFL slate and kickoff without hard-coded week defaults."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
EASTERN = ZoneInfo("America/New_York")
FILE_RE = re.compile(r"games_(\d{4})_w(\d+)\.json$")


def fail(message: str) -> None:
    raise SystemExit(f"freeze target resolution failed: {message}")


def load_candidates() -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for path in sorted(VIEWER.glob("games_*_w*.json")):
        match = FILE_RE.fullmatch(path.name)
        if not match:
            continue
        season, week = int(match.group(1)), int(match.group(2))
        slate_path = VIEWER / f"slate_{season}_w{week}.json"
        if not slate_path.is_file():
            fail(f"{path.name} exists but {slate_path.name} is missing")
        games = json.loads(path.read_text(encoding="utf-8"))
        for game in games:
            kickoff = datetime.fromisoformat(
                f"{game['gameday']}T{game['gametime']}"
            ).replace(tzinfo=EASTERN)
            candidates.append(
                {"season": season, "week": week, "game_id": game["game_id"], "kickoff": kickoff}
            )
    return candidates


def main() -> None:
    now_input = os.getenv("FREEZE_NOW", "").strip()
    now = datetime.fromisoformat(now_input).astimezone(EASTERN) if now_input else datetime.now(EASTERN)
    season_input = os.getenv("INPUT_SEASON", "").strip()
    week_input = os.getenv("INPUT_WEEK", "").strip()
    game_input = os.getenv("INPUT_GAME_ID", "").strip()
    manual = os.getenv("EVENT_NAME") == "workflow_dispatch"
    candidates = load_candidates()

    if season_input or week_input:
        if not (season_input and week_input):
            fail("season and week overrides must be supplied together")
        season, week = int(season_input), int(week_input)
        slate = [c for c in candidates if c["season"] == season and c["week"] == week]
    else:
        slate = [c for c in candidates if c["kickoff"].date() == now.date()]
        if not slate and manual:
            future = [c for c in candidates if c["kickoff"] >= now]
            if future:
                nearest = min(future, key=lambda c: c["kickoff"])
                slate = [
                    c for c in candidates
                    if c["season"] == nearest["season"] and c["week"] == nearest["week"]
                ]
        if not slate and not manual:
            # The UTC cron fires a second time after midnight to cover EST.
            # During EDT that invocation is after Thursday kickoff and has no
            # game on its Eastern calendar date; it is a planned no-op.
            print("should_run=false")
            return
        if not slate:
            fail(f"no complete slate contains a game on {now.date().isoformat()}")
        season, week = int(slate[0]["season"]), int(slate[0]["week"])

    if not slate:
        fail(f"no complete slate found for {season} week {week}")
    selected = next((c for c in slate if c["game_id"] == game_input), None) if game_input else None
    if game_input and selected is None:
        fail(f"game {game_input} is not present in {season} week {week}")
    if selected is None:
        future = [c for c in slate if c["kickoff"] >= now]
        selected = min(future or slate, key=lambda c: abs((c["kickoff"] - now).total_seconds()))

    minutes_to_kickoff = (selected["kickoff"] - now).total_seconds() / 60
    should_run = manual or 15 <= minutes_to_kickoff <= 75
    print(f"season={season}")
    print(f"week={week}")
    print(f"game_id={selected['game_id']}")
    print(f"should_run={'true' if should_run else 'false'}")
    print(f"kickoff={selected['kickoff'].isoformat()}")
    print(f"minutes_to_kickoff={minutes_to_kickoff:.1f}")


if __name__ == "__main__":
    main()
