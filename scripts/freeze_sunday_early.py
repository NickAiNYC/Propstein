#!/usr/bin/env python3
"""Freeze the complete Sunday early kickoff cohort and capture its research board."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.freeze_slate import freeze_slate
from src.prospective_board import capture_board, verify_journal


ROOT = Path(__file__).resolve().parent.parent
EASTERN = ZoneInfo("America/New_York")


def target(now: datetime) -> tuple[int, int, dict[str, str]] | None:
    local = now.astimezone(EASTERN)
    if local.weekday() != 6:
        return None
    for path in sorted((ROOT / "viewer").glob("games_*_w*.json")):
        parts = path.stem.split("_")
        if len(parts) != 3 or not parts[2].startswith("w"):
            continue
        season, week = int(parts[1]), int(parts[2][1:])
        games = json.loads(path.read_text(encoding="utf-8"))
        cohort: dict[str, str] = {}
        for game in games:
            kickoff = datetime.fromisoformat(
                f"{game['gameday']}T{game['gametime']}"
            ).replace(tzinfo=EASTERN)
            minutes = (kickoff - local).total_seconds() / 60
            if kickoff.date() == local.date() and kickoff.hour == 13 and 15 <= minutes <= 75:
                cohort[game["game_id"]] = kickoff.isoformat()
        if cohort:
            return season, week, cohort
    return None


def main() -> None:
    now = datetime.now(timezone.utc)
    selected = target(now)
    if selected is None:
        print("No Sunday 1 PM Eastern kickoff 15–75 minutes away; no freeze.")
        return
    season, week, kickoffs = selected
    suffix = f"{season}_w{week}_early_1300"
    journal = ROOT / "snapshots" / f"full_board_{suffix}.jsonl"
    if journal.exists():
        rows = verify_journal(journal)
        if {row["game_id"] for row in rows} != set(kickoffs):
            raise ValueError("existing early-window journal has incomplete game coverage")
        print(f"Verified existing full board: {len(rows)} candidates across {len(kickoffs)} games")
        return

    snapshot_log = ROOT / "snapshots" / f"snapshots_{season}_w{week}.jsonl"
    existing = []
    if snapshot_log.exists():
        existing = [json.loads(line) for line in snapshot_log.read_text().splitlines() if line.strip()]
    covered = {row["game_id"] for row in existing if row.get("snapshot_type") == "pre_kickoff"}
    missing = set(kickoffs) - covered
    if missing:
        freeze_slate(season=season, week=week, snapshot_type="pre_kickoff", game_ids=missing)

    snapshots = []
    for line in snapshot_log.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("game_id") in kickoffs and row.get("snapshot_type") == "pre_kickoff":
            snapshots.append(row)
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        source = temp / "snapshots.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in snapshots), encoding="utf-8")
        kickoff_map = temp / "kickoffs.json"
        kickoff_map.write_text(json.dumps(kickoffs), encoding="utf-8")
        policy_path = ROOT / "config" / "pipeline_coverage.json"
        min_cov = 0.30
        if policy_path.exists():
            try:
                min_cov = float(json.loads(policy_path.read_text(encoding="utf-8")).get("min_quote_coverage_rate", 0.30))
            except Exception:
                pass
        report = capture_board(source, kickoff_map, journal, min_coverage_rate=min_cov)
    verified = verify_journal(journal)
    if {row["game_id"] for row in verified} != set(kickoffs):
        raise ValueError("prospective board omitted a Sunday early game")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
