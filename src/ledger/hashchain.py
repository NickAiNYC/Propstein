"""Per-passport SHA-256 chain over canonical JSON."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.crypto_utils import canonical_json_dumps, canonical_json_sha256


def utc_canonical(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return moment.astimezone(timezone.utc).isoformat()


def payload_canonical(payload: dict[str, Any]) -> str:
    return canonical_json_dumps(payload)


def event_integrity_hash(
    *,
    passport_id: str,
    seq: int,
    event_type: str,
    payload_canonical_text: str,
    prev_hash: str | None,
    created_at_canonical: str,
) -> str:
    return canonical_json_sha256({
        "created_at": created_at_canonical,
        "event_type": event_type,
        "passport_id": str(passport_id),
        "payload_canonical": payload_canonical_text,
        "prev_hash": prev_hash,
        "seq": seq,
    })
