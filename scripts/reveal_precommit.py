"""Precommit reveal. verified is true only when every check passes.

Append stores only {payload_sha256, received_at}. Reveal never labels a row
verified without a matching hash, received_at < kickoff_at, and a close
receipt from snapshots/close_tape.jsonl. That tape is not in the repo, so
the only states this file can emit today are UNKNOWN, MISMATCH, LATE,
COMMITTED, and AWAITING_CLOSE.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.crypto_utils import canonical_json_sha256

LOG = ROOT / "viewer" / "precommit_log.jsonl"
STATUS = ROOT / "viewer" / "precommit_status.json"
CLOSE_TAPE = ROOT / "snapshots" / "close_tape.jsonl"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KEYS = ("book", "kickoff_at", "line", "market", "odds", "player_id", "side", "slate")


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_hash(digest: str) -> dict:
    if not HEX64.match(digest):
        raise SystemExit("reject: payload_sha256 must be 64 hex characters")
    row = {
        "payload_sha256": digest.lower(),
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def _write_status(row: dict) -> dict:
    current = {"close_tape_present": CLOSE_TAPE.exists(), "rows": []}
    if STATUS.exists():
        current = json.loads(STATUS.read_text(encoding="utf-8"))
    rows = [item for item in current.get("rows", []) if item.get("payload_sha256") != row.get("payload_sha256")]
    rows.append(row)
    payload = {"close_tape_present": CLOSE_TAPE.exists(), "rows": rows}
    STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return row


def _grade(payload: dict, quote: dict) -> str:
    side = payload["side"]
    if side == "OVER":
        line_delta = float(quote["line"]) - float(payload["line"])
    elif side == "UNDER":
        line_delta = float(payload["line"]) - float(quote["line"])
    else:
        return "MISMATCH"
    if line_delta > 0:
        return "BEAT"
    if line_delta < 0:
        return "LOSE"
    return "TIE"


def reveal(payload: dict) -> dict:
    if set(payload) != set(KEYS):
        return {"state": "MISMATCH", "verified": False, "reason": "payload keys"}
    digest = canonical_json_sha256({key: payload[key] for key in KEYS})
    matches = [row for row in load_log() if row.get("payload_sha256") == digest]
    if not matches:
        return {"state": "UNKNOWN", "verified": False, "payload_sha256": digest}
    received_at = matches[0]["received_at"]
    kickoff_at = payload["kickoff_at"]
    base = {"payload_sha256": digest, "received_at": received_at, "kickoff_at": kickoff_at, "verified": False}
    if received_at >= kickoff_at:
        return _write_status({**base, "state": "LATE"})
    if not CLOSE_TAPE.exists():
        return _write_status({**base, "state": "AWAITING_CLOSE"})
    legal = []
    for line in CLOSE_TAPE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        quote = json.loads(line)
        if quote.get("player_id") != payload["player_id"]:
            continue
        if quote.get("market") != payload["market"] or quote.get("book") != payload["book"]:
            continue
        captured_at = quote.get("captured_at")
        receipt = quote.get("receipt_sha256")
        if not captured_at or not receipt or not HEX64.match(str(receipt)):
            continue
        if not (received_at < captured_at < kickoff_at):
            continue
        legal.append(quote)
    if not legal:
        return _write_status({**base, "state": "AWAITING_CLOSE"})
    quote = max(legal, key=lambda item: item["captured_at"])
    return _write_status({
        **base,
        "state": "VERIFIED",
        "verified": True,
        "close_receipt_sha256": quote["receipt_sha256"],
        "grade": _grade(payload, quote),
    })


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "append":
        if len(argv) != 3:
            raise SystemExit("usage: reveal_precommit.py append <64-hex-sha256>")
        print(json.dumps(append_hash(argv[2])))
        return 0
    if len(argv) == 3 and argv[1] == "reveal":
        payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(reveal(payload)))
        return 0
    raise SystemExit("usage: reveal_precommit.py append <hash> | reveal <payload.json>")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
