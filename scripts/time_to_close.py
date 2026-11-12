"""Time-to-close on the published Week 7 board.

A row is near-close when close_time - trigger_time is 2 hours or less.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "viewer" / "clv_report_2026_w7.json"


def summarize() -> dict:
    rows = json.loads(BOARD.read_text(encoding="utf-8"))["ledger"]
    hours = []
    beat = 0
    for row in rows:
        gap = (
            datetime.fromisoformat(row["close_time"]) - datetime.fromisoformat(row["trigger_time"])
        ).total_seconds() / 3600
        hours.append(gap)
        row["hours_to_close"] = round(gap, 3)
        if row.get("status") == "BEAT_CLOSE":
            beat += 1
    n = len(rows)
    within_2h = sum(gap <= 2 for gap in hours)
    ordered = sorted(hours)
    median = ordered[n // 2] if n else None
    return {
        "n": n,
        "beat": beat,
        "within_2h": within_2h,
        "median_h": median,
        "trigger_times": sorted({row["trigger_time"] for row in rows}),
        "close_times": sorted({row["close_time"] for row in rows}),
        "rows": rows,
    }


def main() -> None:
    summary = summarize()
    n = summary["n"]
    within = summary["within_2h"]
    print(f"n={n} within_2h={within} ({within / n:.1%}) median_h={summary['median_h']:.3f}")
    print("trigger_times", summary["trigger_times"])
    print("close_times", summary["close_times"])


if __name__ == "__main__":
    main()
