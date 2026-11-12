#!/usr/bin/env python3
"""Count a proved close tape. Does not grade decisions or write a ledger.

A row is proved only when captured_at < kickoff_at and receipt_sha256 is
64 hex. Shared kickoff times do not cover every game at that time.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TAPE = ROOT / "snapshots" / "close_tape.jsonl"
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
REQUIRED = ("player_id", "market", "book", "line", "captured_at", "kickoff_at", "receipt_sha256")


def _utc(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).replace(microsecond=0)


def _rows(text: str) -> list[dict]:
    proved = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if any(key not in row for key in REQUIRED):
            continue
        captured = _utc(str(row["captured_at"]))
        kickoff = _utc(str(row["kickoff_at"]))
        receipt = str(row["receipt_sha256"])
        if captured is None or kickoff is None or not captured < kickoff:
            continue
        if len(receipt) != 64 or any(ch not in "0123456789abcdef" for ch in receipt):
            continue
        row["_kick"] = kickoff
        proved.append(row)
    return proved


def _load() -> list[dict]:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return _rows(text)
    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        if piped.strip():
            return _rows(piped)
    if not TAPE.exists() or not TAPE.read_text(encoding="utf-8").strip():
        return []
    return _rows(TAPE.read_text(encoding="utf-8"))


def _slates() -> dict[str, dict[datetime, list[str]]]:
    found: dict[str, dict[datetime, list[str]]] = {}
    for path in sorted((ROOT / "viewer").glob("games_2026_w*.json")):
        week = int(path.stem.rsplit("_w", 1)[1])
        slate = f"2026-W{week:02d}"
        slots: dict[datetime, list[str]] = {}
        for game in json.loads(path.read_text(encoding="utf-8")):
            hour, minute = str(game["gametime"]).split(":")
            local = datetime(
                *map(int, str(game["gameday"]).split("-")),
                int(hour),
                int(minute),
                tzinfo=ET,
            ).astimezone(UTC).replace(microsecond=0)
            slots.setdefault(local, []).append(game["game_id"])
        found[slate] = slots
    return found


def main() -> int:
    rows = _load()
    if not rows:
        return 0
    slates = _slates()
    game_slate = {}
    slot_owners: dict[datetime, list[str]] = {}
    for slate, slots in slates.items():
        for kick, ids in slots.items():
            slot_owners[kick] = ids
            for game_id in ids:
                game_slate[game_id] = slate
    covered: set[str] = set()
    used_slates: set[str] = set()
    for row in rows:
        game_id = row.get("game_id")
        if isinstance(game_id, str) and game_id in game_slate:
            covered.add(game_id)
            used_slates.add(game_slate[game_id])
            continue
        owners = slot_owners.get(row["_kick"], [])
        if len(owners) == 1:
            covered.add(owners[0])
            used_slates.add(game_slate[owners[0]])
    if len(used_slates) == 1:
        slate = next(iter(used_slates))
        needed = {game_id for ids in slates[slate].values() for game_id in ids}
        full = needed <= covered and len(needed) > 0
    else:
        slate = "unmatched" if not used_slates else "mixed"
        full = False
    print(f"slate {slate}")
    print(f"unique game_ids {len(covered)}")
    print(f"full board {'yes' if full else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
