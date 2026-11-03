"""
Legacy CLV Research Estimator
Historical trigger-only estimate, not a prospective full-board track record.

Logic:
1. Isolate the Trigger: Finds the first timestamp where a prop was flagged as VERIFIED_ACTIVE with edge >= 10%.
2. Select the last recorded snapshot; this script cannot prove it is a pre-kickoff close.
3. Calculate the Delta: Computes the line movement delta and mathematical EV of holding the trigger ticket
   against the closing market consensus distribution.
4. Publish a legacy research report. This script is not the prospective,
   receipt-verified full-board audit; use prospective_board.py for that.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
VIEWER_DIR = BASE_DIR / "viewer"


def american_to_prob(odds: int) -> float:
    """Returns break-even win probability from American odds."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def american_payout(odds: int) -> float:
    """Returns decimal profit multiplier for $1 wager (b)."""
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)


def devig_two_way(over_odds: int, under_odds: int) -> Tuple[float, float]:
    """De-vigs two-way American odds to multiplicative fair probabilities."""
    p_over = american_to_prob(over_odds)
    p_under = american_to_prob(under_odds)
    total = p_over + p_under
    if total <= 0:
        return 0.5, 0.5
    return p_over / total, p_under / total


def estimate_clv_ev(
    side: str,
    market: str,
    trigger_line: float,
    trigger_odds: int,
    close_line: float,
    close_odds: int,
    proj_sd: Optional[float] = None
) -> float:
    """
    Calculates the expected value of holding a trigger ticket evaluated against
    the closing market consensus.
    """
    b = american_payout(trigger_odds)
    # Estimate standard deviation for line shift: ~22.0 yards for receiving yards, ~2.2 for receptions
    sd = proj_sd if (proj_sd and proj_sd > 0) else (2.2 if market == "receptions" else 22.0)
    
    # Line movement impact in z-score
    if side == "OVER":
        line_diff = close_line - trigger_line
    else:
        line_diff = trigger_line - close_line

    # Base closing probability from closing odds
    base_close_prob = american_to_prob(close_odds)
    
    # Probability shift due to line delta: norm.cdf approximation
    z_shift = line_diff / max(sd, 1.0)
    prob_shift = 0.5 * math.erf(z_shift / math.sqrt(2))
    
    # Win probability of trigger line evaluated under close distribution
    p_win_against_close = max(0.01, min(0.99, base_close_prob + (prob_shift * 0.45)))
    
    # EV = (P * (1 + b)) - 1
    ev = (p_win_against_close * (1.0 + b)) - 1.0
    return round(ev, 4)


def grade_clv_snapshots(
    snapshot_path: Path,
    output_path: Path,
    slate: str = "2026-W07",
    edge_hurdle: float = 0.10
) -> Dict[str, Any]:
    """
    Scans a snapshot JSONL file and computes an unverified legacy estimate.
    """
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot file not found: {snapshot_path}")

    # Key: (player_name, market, side) -> list of snapshot dicts
    history: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    with open(snapshot_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            quote = record.get("quote")
            if not quote or quote.get("line") is None:
                continue

            eval_info = quote.get("evaluation") or {}
            side = eval_info.get("best_side", "OVER")
            key = (record.get("player_name"), record.get("market"), side)
            history[key].append(record)

    ledger_entries = []
    total_line_deltas = []
    total_ev_gains = []
    beat_close_count = 0

    for (player_name, market, side), records in history.items():
        # Sort chronologically
        records.sort(key=lambda r: r.get("created_at", ""))

        # 1. Isolate the Trigger
        trigger_record = None
        for r in records:
            q = r.get("quote", {})
            e = q.get("evaluation") or {}
            edge = e.get("prob_edge") or 0.0
            is_qualified = e.get("is_qualified") or (edge >= edge_hurdle)
            is_verified = (q.get("status") == "verified")

            if is_verified and is_qualified:
                trigger_record = r
                break

        if not trigger_record:
            continue

        # 2. Isolate the Close
        close_record = records[-1]
        # A single trigger snapshot is not a closing observation. Never grade
        # it against itself or invent a close when the later quote is absent.
        if close_record.get("created_at", "") <= trigger_record.get("created_at", ""):
            continue

        t_quote = trigger_record.get("quote", {})
        c_quote = close_record.get("quote", {})

        entry_odds = t_quote.get("over_odds" if side == "OVER" else "under_odds")
        closing_odds = c_quote.get("over_odds" if side == "OVER" else "under_odds")
        if entry_odds is None or closing_odds is None or c_quote.get("line") is None:
            continue
        t_line = float(t_quote["line"])
        t_odds = int(entry_odds)
        t_eval = t_quote.get("evaluation") or {}
        t_edge = float(t_eval.get("prob_edge", 0.0))

        c_line = float(c_quote["line"])
        c_odds = int(closing_odds)

        # 3. Calculate Deltas
        if side == "OVER":
            line_movement = c_line - t_line
        else:
            line_movement = t_line - c_line

        clv_ev = estimate_clv_ev(
            side=side,
            market=market,
            trigger_line=t_line,
            trigger_odds=t_odds,
            close_line=c_line,
            close_odds=c_odds
        )

        # Status classification
        if line_movement > 0 or (line_movement == 0 and c_odds < t_odds):
            status = "BEAT_CLOSE"
            beat_close_count += 1
        elif line_movement == 0 and c_odds == t_odds:
            status = "PUSH"
        else:
            status = "FADED"

        total_line_deltas.append(line_movement)
        total_ev_gains.append(clv_ev)

        entry = {
            "player_id": trigger_record.get("player_id"),
            "player_name": player_name,
            "team": trigger_record.get("team"),
            "opponent": trigger_record.get("opponent"),
            "market": market,
            "side": side,
            "trigger_time": trigger_record.get("created_at"),
            "trigger_line": t_line,
            "trigger_odds": t_odds,
            "trigger_edge": round(t_edge, 4),
            "close_time": close_record.get("created_at"),
            "close_line": c_line,
            "close_odds": c_odds,
            "line_movement": round(line_movement, 2),
            "clv_ev": clv_ev,
            "status": status,
            "book": t_quote.get("book") or "DraftKings / Bovada Consensus",
            "receipt_id": t_quote.get("quote_id") or trigger_record.get("snapshot_id")
        }
        ledger_entries.append(entry)

    # Sort ledger entries by line movement descending
    ledger_entries.sort(key=lambda x: (x["status"] == "BEAT_CLOSE", x["line_movement"], x["clv_ev"]), reverse=True)

    total_graded = len(ledger_entries)
    positive_clv_pct = (beat_close_count / total_graded) if total_graded > 0 else 0.0
    avg_line_delta = (sum(total_line_deltas) / total_graded) if total_graded > 0 else 0.0
    avg_clv_ev = (sum(total_ev_gains) / total_graded) if total_graded > 0 else 0.0

    report = {
        "slate": slate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "edge_hurdle": edge_hurdle,
        "summary": {
            "total_graded": total_graded,
            "beat_close_count": beat_close_count,
            "positive_clv_pct": round(positive_clv_pct, 4),
            "avg_line_delta": round(avg_line_delta, 2),
            "avg_clv_ev": round(avg_clv_ev, 4),
            "verification_rate": None,
            "immutable_ledger": False,
            "audit_status": "LEGACY_RESEARCH_ONLY_NO_INDEPENDENT_RECEIPT_VERIFICATION"
        },
        "ledger": ledger_entries
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="CLV Validation Engine")
    parser.add_argument("--snapshots", type=str, default="snapshots/snapshots_2026_w7.jsonl", help="Path to snapshots JSONL")
    parser.add_argument("--output", type=str, default="viewer/clv_report_2026_w7.json", help="Path to output JSON report")
    parser.add_argument("--slate", type=str, default="2026-W07", help="Slate key")
    parser.add_argument("--hurdle", type=float, default=0.10, help="Minimum edge hurdle to qualify (default 0.10)")
    args = parser.parse_args()

    snaps = Path(args.snapshots)
    out = Path(args.output)
    
    report = grade_clv_snapshots(snaps, out, slate=args.slate, edge_hurdle=args.hurdle)
    summary = report["summary"]
    print(f"=== CLV Validation Engine Report [{args.slate}] ===")
    print(f"Total Qualified Props: {summary['total_graded']}")
    print(f"Beat Close %:          {summary['positive_clv_pct']:.1%}")
    print(f"Average Line Movement: {summary['avg_line_delta']:+.2f} units")
    print(f"Average CLV EV:        {summary['avg_clv_ev']:+.2%}")
    print(f"Ledger Output:         {out.resolve()}")


if __name__ == "__main__":
    main()
