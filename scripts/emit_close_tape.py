#!/usr/bin/env python3
"""Future close-tape emitter. Does not connect and does not invent rows.

Required snapshots/close_tape.jsonl object:
  player_id       str
  market          str
  book            str
  line            number
  captured_at     timezone-aware ISO-8601 UTC, strictly before kickoff_at
  kickoff_at      timezone-aware ISO-8601 UTC
  receipt_sha256  64 lowercase hex over the canonical payload that includes
                  captured_at and kickoff_at

The stored closing_snapshots row has player_id, market, book, and closing_line.
It has no kickoff_at and no captured_at. Its snapshot hash does not cover those
two fields. Do not backfill.
"""

from __future__ import annotations

MESSAGE = "No close tape source that can prove captured_at < kickoff_at"


def main() -> int:
    print(MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
