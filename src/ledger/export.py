"""JSONL mirror stub.

Merkle roots and OpenTimestamps anchoring are a follow-up. This writer only
copies ledger events. It does not anchor them.
"""

from __future__ import annotations

import json
from pathlib import Path


def export_ledger_jsonl(conn, dest: Path) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT passport_id::text AS passport_id, seq, event_type, prev_hash,
                   integrity_hash, created_at_canonical
            FROM ledger_events
            ORDER BY created_at, passport_id, seq
            """
        )
        rows = cur.fetchall()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({
                "passport_id": row["passport_id"],
                "seq": row["seq"],
                "event_type": row["event_type"],
                "prev_hash": row["prev_hash"],
                "integrity_hash": row["integrity_hash"],
                "created_at": row["created_at_canonical"],
            }, sort_keys=True) + "\n")
    return {
        "path": str(dest),
        "event_count": len(rows),
        "anchoring": "not_implemented",
    }
