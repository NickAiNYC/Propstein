"""Historical rows that lack event_id or provenance stay flagged.

game_id, kickoff_at, trigger_time, and close_time are not copied into
event_id or event_start_at. Missing evidence is not reconstructed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.crypto_utils import canonical_json_sha256

INVENTORY = (
    ("snapshots/full_board_2026_w8_early_1300.jsonl", "jsonl"),
    ("snapshots/snapshots_2026_w1.jsonl", "jsonl"),
    ("snapshots/snapshots_2026_w7.jsonl", "jsonl"),
    ("snapshots/snapshots_2026_w8.jsonl", "jsonl"),
    ("viewer/clv_report_2026_w7.json", "clv_ledger"),
    ("viewer/clv_audit_report.json", "audit_records"),
    ("public/clv_audit_report.json", "audit_records"),
    ("viewer/ufc_ledger.json", "ufc_cards"),
)


@dataclass(frozen=True)
class Gap:
    source_name: str
    source_locator: str
    missing_fields: tuple[str, ...]
    payload: dict
    source_integrity_hash: str | None


def _aware(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def missing_evidence(row: dict) -> tuple[str, ...]:
    """Return required evidence that is absent. Never substitute other fields."""
    missing: list[str] = []
    event_id = row.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        missing.append("event_id")
    if not _aware(row.get("event_start_at")):
        missing.append("event_start_at")
    captured = row.get("captured_at")
    if captured is None:
        if "captured_at" in row or row.get("schema") == "propstein.prospective_board.v1":
            missing.append("captured_at")
    elif not _aware(captured):
        missing.append("captured_at")
    digest = row.get("record_sha256")
    if isinstance(digest, str):
        body = {key: value for key, value in row.items() if key != "record_sha256"}
        if digest != canonical_json_sha256(body):
            missing.append("record_sha256")
    return tuple(missing)


def classify_import_row(row: dict, *, source_name: str, locator: str) -> Gap | None:
    missing = missing_evidence(row)
    if "event_id" in missing or "event_start_at" in missing or "record_sha256" in missing or "captured_at" in missing:
        digest = row.get("record_sha256") if isinstance(row.get("record_sha256"), str) else None
        return Gap(source_name, locator, missing, row, digest)
    return None


def _iter_records(path: Path, kind: str):
    if not path.is_file():
        return
    if kind == "jsonl":
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            yield f"line:{index}", json.loads(line)
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if kind == "clv_ledger":
        for index, row in enumerate(payload.get("ledger") or []):
            yield f"ledger:{index}", row
    elif kind == "audit_records":
        for index, row in enumerate(payload.get("records") or []):
            yield f"records:{index}", row
    elif kind == "ufc_cards":
        for index, row in enumerate(payload.get("cards") or []):
            yield f"cards:{index}", row


def inventory_historical_gaps(root: Path) -> list[dict]:
    found: list[dict] = []
    for relative, kind in INVENTORY:
        path = root / relative
        for locator, row in _iter_records(path, kind) or ():
            if not isinstance(row, dict):
                continue
            missing = list(missing_evidence(row))
            if kind == "ufc_cards" and not row.get("decisions"):
                if "event_start_at" not in missing and "event_id" not in missing:
                    continue
            if not missing and kind != "jsonl":
                # Audit rows have no record_sha256. Still require event identity.
                continue
            if missing:
                found.append({
                    "source": relative,
                    "locator": locator,
                    "player_id": row.get("player_id") or row.get("player"),
                    "market": row.get("market"),
                    "game_id": row.get("game_id"),
                    "event_id_present": isinstance(row.get("event_id"), str) and bool(row.get("event_id")),
                    "missing_fields": missing,
                })
    return found


def summarize_gaps(rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        bucket = grouped.setdefault(row["source"], {
            "source": row["source"],
            "records": 0,
            "missing_fields": {},
        })
        bucket["records"] += 1
        for field in row["missing_fields"]:
            bucket["missing_fields"][field] = bucket["missing_fields"].get(field, 0) + 1
    return [grouped[key] for key in sorted(grouped)]
