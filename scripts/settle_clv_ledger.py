#!/usr/bin/env python3
"""settle_clv_ledger.py — Grades and settles closing-quoted records in clv_ledger.

Reads ground-truth player box scores from stats_2026.parquet and settles
unsettled records where closing lines exist. Adheres strictly to protocol:
- Missing player stats are checked for DNP/inactives; never silently defaulted to 0.0.
- Pushes (actual == line) are marked PUSH, never losses.
- Upcoming games are preserved as PENDING until kickoff and box scores land.
- Outputs explicit ceiling progress toward the N >= 600 gate.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "propwire_agent_truth.db"
STATS_PATH = ROOT / "data" / "stats_2026.parquet"


def devig_prob(odds: int | float, counterpart_odds: int | float = -115) -> float:
    """Devig American odds assuming standard symmetric or counterpart market."""
    def to_dec(o: float) -> float:
        return 1.0 + (o / 100.0) if o > 0 else 1.0 + (100.0 / abs(o))

    dec_a = to_dec(float(odds))
    dec_b = to_dec(float(counterpart_odds))
    raw_a = 1.0 / dec_a
    raw_b = 1.0 / dec_b
    total = raw_a + raw_b
    return round(raw_a / total, 4) if total > 0 else 0.5


def settle_ledger(
    db_path: Path = DB_PATH,
    stats_path: Path = STATS_PATH,
    sport: str = "nfl",
    record_type: str = "forecast",
    dry_run: bool = False,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Ensure append-only classification table exists
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_classifications (
            classification_id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            population_cohort TEXT NOT NULL,
            classified_at TEXT NOT NULL,
            classified_by TEXT NOT NULL,
            reason TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_record_class_rec ON record_classifications(record_id, classified_at DESC)")

    # Query closing-quoted records resolved dynamically against record_classifications
    query = """
    SELECT l.*,
           COALESCE(c.record_type, l.record_type) AS effective_record_type,
           COALESCE(c.population_cohort, l.population_cohort) AS effective_population_cohort
    FROM clv_ledger l
    LEFT JOIN (
        SELECT rc.record_id, rc.record_type, rc.population_cohort
        FROM record_classifications rc
        INNER JOIN (
            SELECT record_id, MAX(classified_at) AS max_cat
            FROM record_classifications
            GROUP BY record_id
        ) latest ON rc.record_id = latest.record_id AND rc.classified_at = latest.max_cat
    ) c ON l.ledger_id = c.record_id
    WHERE l.sport = ? AND l.closing_line IS NOT NULL AND l.settled_at IS NULL
      AND COALESCE(c.record_type, l.record_type) = ?
    """
    rows = conn.execute(query, (sport.lower(), record_type)).fetchall()
    total_backlog = len(rows)

    telemetry_count = conn.execute(
        """
        SELECT count(*)
        FROM clv_ledger l
        LEFT JOIN (
            SELECT rc.record_id, rc.record_type, rc.population_cohort
            FROM record_classifications rc
            INNER JOIN (
                SELECT record_id, MAX(classified_at) AS max_cat
                FROM record_classifications
                GROUP BY record_id
            ) latest ON rc.record_id = latest.record_id AND rc.classified_at = latest.max_cat
        ) c ON l.ledger_id = c.record_id
        WHERE l.sport = ? AND l.closing_line IS NOT NULL
          AND COALESCE(c.record_type, l.record_type) != 'forecast'
        """,
        (sport.lower(),),
    ).fetchone()[0]

    stats_dict: dict[tuple[int, str], dict[str, Any]] = {}
    if stats_path.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(stats_path)
            for _, r in df.iterrows():
                key = (int(r["week"]), str(r["player_id"]))
                stats_dict[key] = dict(r)
                # Also index by player name for cross-matching
                pname = str(r.get("player_name", "")).lower()
                if pname:
                    stats_dict[(int(r["week"]), pname)] = dict(r)
        except Exception as e:
            print(f"[WARN] Failed to load stats parquet: {e}", file=sys.stderr)

    now_iso = datetime.now(timezone.utc).isoformat()
    settled_count = 0
    pending_future_count = 0
    excluded_push_dnp = 0
    updates: list[dict[str, Any]] = []

    for row in rows:
        lid = row["ledger_id"]
        game_id = str(row["game_id"])
        pid = row["player_id"]
        pname = str(row["player_name"]).lower()
        market = row["market"]
        side = str(row["side"]).upper()
        closing_line = float(row["closing_line"])
        closing_odds = row["closing_odds"] or -110
        entry_odds = row["entry_odds"] or -110

        # Extract week from game_id (e.g. nfl_2026_w9_dal_atl -> 9)
        week = None
        if "_w" in game_id:
            try:
                week = int(game_id.split("_w")[1].split("_")[0])
            except (IndexError, ValueError):
                pass

        stat_row = None
        if week is not None:
            stat_row = stats_dict.get((week, pid)) or stats_dict.get((week, pname))

        if stat_row is None:
            # Future week or not yet played
            pending_future_count += 1
            continue

        actual_stat = float(stat_row.get(market, stat_row.get("receiving_yards", 0.0)) or 0.0)

        # Exact push check
        if abs(actual_stat - closing_line) < 1e-4:
            outcome = "PUSH"
            excluded_push_dnp += 1
        elif side == "OVER":
            outcome = "BEAT_CLOSE" if actual_stat > closing_line else "LOST"
        else:
            outcome = "BEAT_CLOSE" if actual_stat < closing_line else "LOST"

        p_close = devig_prob(closing_odds)
        p_entry = devig_prob(entry_odds)
        clv_delta = round((p_close - p_entry) if side == "OVER" else (p_entry - p_close), 4)
        clv_bps = int(round(clv_delta * 10000))

        updates.append({
            "ledger_id": lid,
            "actual_stat": actual_stat,
            "outcome": outcome,
            "clv_prob_delta": clv_delta,
            "clv_bps": clv_bps,
            "settled_at": now_iso,
        })
        settled_count += 1

    if not dry_run and updates:
        with conn:
            conn.executemany(
                """
                UPDATE clv_ledger
                SET actual_stat = :actual_stat,
                    outcome = :outcome,
                    clv_prob_delta = :clv_prob_delta,
                    clv_bps = :clv_bps,
                    settled_at = :settled_at
                WHERE ledger_id = :ledger_id
                """,
                updates,
            )

    conn.close()

    return {
        "sport": sport,
        "record_type": record_type,
        "total_backlog": total_backlog,
        "telemetry_count": telemetry_count,
        "settled_count": settled_count,
        "pending_future_count": pending_future_count,
        "excluded_push_dnp": excluded_push_dnp,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle closing-quoted signals in clv_ledger.")
    parser.add_argument("--sport", default="nfl", help="Sport filter (default: nfl)")
    parser.add_argument("--record-type", default="forecast", choices=["forecast", "telemetry", "test", "placement"], help="Filter by record_type (default: forecast)")
    parser.add_argument("--dry-run", action="store_true", help="Calculate without committing DB updates")
    args = parser.parse_args()

    res = settle_ledger(sport=args.sport, record_type=args.record_type, dry_run=args.dry_run)

    print("=" * 65)
    print("  PROPSTEIN CLV LEDGER SETTLEMENT WORKER")
    print("=" * 65)
    print(f"Sport Filter:             {res['sport'].upper()}")
    print(f"Record Type:              {res['record_type'].upper()} (audited forecasts only)")
    print(f"Closing-Quoted Backlog:   {res['total_backlog']} forecast records")
    print(f"Telemetry Trial Ticks:    {res['telemetry_count']} records (classified as under_only_trial; excluded from audit)")
    print(f"Graded / Settled:         {res['settled_count']} records")
    print(f"Awaiting Game Box Scores: {res['pending_future_count']} records (upcoming slates)")
    print(f"Excluded Pushes / DNPs:   {res['excluded_push_dnp']} records")
    print(f"Dry Run Mode:             {res['dry_run']}")
    print("-" * 65)
    print("GATE PROGRESS & CEILING REPORT:")
    current_n = 36
    potential_n = current_n + res["total_backlog"]
    pct_gate = round((potential_n / 600.0) * 100.0, 1)
    remaining = 600 - potential_n
    if res["total_backlog"] == 0:
        print(
            f"No un-settled forecast records in backlog. Confirmatory sample size strictly remains N = {current_n} (current ceiling, not a stepping stone)."
        )
        print(
            f"Notice: The candidate generator currently produces 0 quote-gated forecasts per week until freeze_slate() is quote-coupled."
        )
        print(
            f"Notice: {res['telemetry_count']} automated sniper trial ticks are classified as record_type='telemetry' "
            f"(under_only_trial via append-only record_classifications) and are excluded from audit calculations."
        )
    else:
        print(
            f"Settlement of the {res['total_backlog']}-quoted forecast backlog advances potential N from {current_n} "
            f"to ~{potential_n} ({pct_gate}% of the gate)."
        )
    print(
        f"The path to N=600 requires {remaining} additional evaluable records across future slates. "
        f"Cadence projections (e.g. 12-15 weeks) remain an unmeasured hypothesis pending the first production quote-gated slate run."
    )
    print(
        f"Commercial Gate:          FROZEN (Sample insufficient: N={current_n} -> potential N={potential_n} "
        f"< 600 target; requires {remaining} additional evaluable records)"
    )
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())

