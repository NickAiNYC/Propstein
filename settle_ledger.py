#!/usr/bin/env python3
"""
settle_ledger.py — Institutional CLV & Box-Score Settlement Engine for PropWire
Computes:
1. Closing Line Value (Yardage Delta & De-Vigged Implied Probability Delta)
2. Realized Binary Outcome (WIN / LOSS / PUSH) & Net Unit / Dollar ROI
3. Cryptographic Audit Hash for the footer & [CLV Report] modal
"""
import json
import math
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.crypto_utils import canonical_json_sha256
from src.settlement_engine import (
    EntryReceipt,
    ClosingSnapshot,
    OfficialBoxscoreStat,
    grade_receiving_prop,
    SettlementOutcome,
)


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds (-115, +170) to raw implied probability (0.0 - 1.0)."""
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def american_to_decimal_payout(odds: int) -> float:
    """Return net profit multiplier per 1 unit risked."""
    if odds < 0:
        return 100.0 / (-odds)
    return odds / 100.0


def devig_two_way(over_odds: int, under_odds: int) -> Dict[str, float]:
    """Multiplicative (proportional) de-vigging of a two-way prop market."""
    p_over_raw = american_to_implied_prob(over_odds)
    p_under_raw = american_to_implied_prob(under_odds)
    book_sum = p_over_raw + p_under_raw
    return {
        "p_over": p_over_raw / book_sum,
        "p_under": p_under_raw / book_sum,
        "hold_pct": (book_sum - 1.0) * 100.0,
    }


def normal_cdf(x: float, mean: float, std: float) -> float:
    """Approximate P(X <= x) using error function for yardage-movement CLV conversion."""
    if std <= 0:
        return 0.5
    z = (x - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def compute_clv_metrics(
    bet: Dict[str, Any],
    closing_quote: Dict[str, Any],
    model_std: float = 24.0,
) -> Dict[str, Any]:
    """
    Calculates both:
    - clv_yards: Positive means the line moved in your bet's favor by kickoff
    - clv_prob_pct: De-vigged win probability gained between bet placement and close
    """
    side = bet["side"].upper()  # 'OVER' or 'UNDER'
    bet_line = float(bet["line"])
    bet_odds = int(bet["odds"])
    close_line = float(closing_quote["line"])
    close_over_odds = int(closing_quote.get("over_odds", -115))
    close_under_odds = int(closing_quote.get("under_odds", -115))

    # 1. Directional Yardage CLV
    # If OVER 75.5 and it closes 79.5 -> +4.0 yds CLV
    # If UNDER 69.5 and it closes 66.5 -> +3.0 yds CLV
    clv_yards = (close_line - bet_line) if side == "OVER" else (bet_line - close_line)

    # 2. De-Vigged Closing Probability at the Closing Line
    devig_close = devig_two_way(close_over_odds, close_under_odds)
    p_close_at_close_line = devig_close["p_over"] if side == "OVER" else devig_close["p_under"]

    # Adjust closing probability for half-yard / multi-yard line movement using local density
    # so moving from 75.5 to 78.5 properly credits probability gain
    p_shift = normal_cdf(close_line, close_line, model_std) - normal_cdf(bet_line, close_line, model_std)
    if side == "OVER":
        true_close_prob_of_bet_line = min(0.95, max(0.05, p_close_at_close_line + p_shift))
    else:
        true_close_prob_of_bet_line = min(0.95, max(0.05, p_close_at_close_line - p_shift))

    # Compare against De-Vigged Implied Probability at Bet Placement
    counterpart_odds = int(bet.get("counterpart_odds", -115))
    devig_bet = (
        devig_two_way(bet_odds, counterpart_odds)["p_over"]
        if side == "OVER"
        else devig_two_way(counterpart_odds, bet_odds)["p_under"]
    )
    clv_prob_pct = (true_close_prob_of_bet_line - devig_bet) * 100.0

    return {
        "close_line": round(close_line, 1),
        "close_odds": close_over_odds if side == "OVER" else close_under_odds,
        "clv_yards": round(clv_yards, 1),
        "bet_devig_prob_pct": round(devig_bet * 100.0, 2),
        "close_devig_prob_pct": round(true_close_prob_of_bet_line * 100.0, 2),
        "clv_prob_pct": round(clv_prob_pct, 2),
        "beat_close": (clv_yards > 0) or (clv_prob_pct > 0),
    }


def grade_bet(bet: Dict[str, Any], actual_yards: float) -> Dict[str, Any]:
    """Grades binary WIN / LOSS / PUSH and computes realized P&L."""
    side = bet["side"].upper()
    line = float(bet["line"])
    odds = int(bet["odds"])
    stake = float(bet.get("stake_amount", 100.0))

    if actual_yards == line:
        outcome = "PUSH"
        pnl = 0.0
    elif (side == "OVER" and actual_yards > line) or (side == "UNDER" and actual_yards < line):
        outcome = "WIN"
        pnl = stake * american_to_decimal_payout(odds)
    else:
        outcome = "LOSS"
        pnl = -stake

    return {
        "actual_yards": actual_yards,
        "outcome": outcome,
        "stake_amount": round(stake, 2),
        "net_pnl": round(pnl, 2),
    }


def settle_slate(
    bets_path: Path,
    closing_snapshots_path: Path,
    boxscores_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    bets: List[Dict[str, Any]] = json.loads(bets_path.read_text()) if bets_path.exists() else []
    boxscores: Dict[str, float] = json.loads(boxscores_path.read_text()) if boxscores_path.exists() else {}

    # Load latest closing quote per (player, market) from JSONL
    closing_map: Dict[str, Dict[str, Any]] = {}
    if closing_snapshots_path.exists():
        for raw_line in closing_snapshots_path.read_text().splitlines():
            if not raw_line.strip():
                continue
            snap = json.loads(raw_line)
            key = f"{snap['player']}::{snap.get('market', 'rec_yds')}"
            closing_map[key] = snap

    graded_records = []
    total_staked = 0.0
    total_pnl = 0.0
    wins = losses = pushes = 0
    clv_beats = 0
    clv_prob_sum = 0.0
    clv_yards_sum = 0.0

    for bet in bets:
        key = f"{bet['player']}::{bet.get('market', 'rec_yds')}"
        close_quote = closing_map.get(key, {"line": bet["line"], "over_odds": bet["odds"], "under_odds": -115})
        clv = compute_clv_metrics(bet, close_quote)
        actual = boxscores.get(bet["player"])
        settlement = (
            grade_bet(bet, actual)
            if actual is not None
            else {
                "actual_yards": None,
                "outcome": "PENDING",
                "stake_amount": float(bet.get("stake_amount", 100.0)),
                "net_pnl": 0.0,
            }
        )

        if settlement["outcome"] in ("WIN", "LOSS", "PUSH"):
            total_staked += settlement["stake_amount"]
            total_pnl += settlement["net_pnl"]
            if settlement["outcome"] == "WIN":
                wins += 1
            elif settlement["outcome"] == "LOSS":
                losses += 1
            else:
                pushes += 1

        if clv["beat_close"]:
            clv_beats += 1
        clv_prob_sum += clv["clv_prob_pct"]
        clv_yards_sum += clv["clv_yards"]

        record_payload = {**bet, **clv, **settlement}
        # Build canonical settlement receipt binding entry, close, and outcome
        canon_obj = {
            "player": bet.get("player"),
            "market": bet.get("market", "rec_yds"),
            "side": bet.get("side", "OVER"),
            "line": float(bet.get("line", 0.0)),
            "odds": int(bet.get("odds", -110)),
            "close_line": float(clv.get("close_line", 0.0)),
            "clv_prob_pct": float(clv.get("clv_prob_pct", 0.0)),
            "actual_yards": settlement.get("actual_yards"),
            "outcome": settlement.get("outcome"),
        }
        receipt = canonical_json_sha256(canon_obj)[:16]
        record_payload["settlement_receipt"] = receipt
        graded_records.append(record_payload)

    n = len(graded_records)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": n,
        "graded_count": wins + losses + pushes,
        "record_str": f"{wins}-{losses}-{pushes}",
        "win_rate_pct": round((wins / max(1, wins + losses)) * 100.0, 1),
        "beat_close_rate_pct": round((clv_beats / max(1, n)) * 100.0, 1),
        "avg_clv_yards": round(clv_yards_sum / max(1, n), 2),
        "avg_clv_prob_pct": round(clv_prob_sum / max(1, n), 2),
        "total_staked": round(total_staked, 2),
        "net_pnl": round(total_pnl, 2),
        "realized_roi_pct": round((total_pnl / max(1.0, total_staked)) * 100.0, 2),
        "records": graded_records,
    }
    summary["ledger_root_hash"] = canonical_json_sha256({"records": summary["records"]})[:16]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))

    # Also mirror to viewer/ for Vercel static serving
    viewer_path = Path("viewer/clv_audit_report.json")
    viewer_path.write_text(json.dumps(summary, indent=2))

    return summary


def settle_slate_batch(
    pending_entries: List[EntryReceipt],
    closing_map: Dict[str, ClosingSnapshot],
    boxscore_map: Dict[str, OfficialBoxscoreStat],
    house_rule_mode: str = "ONE_SNAP_REQUIRED",
) -> Dict[str, Any]:
    """
    Two-Stage Deterministic Batch Settler.
    Grades pending entries against verified closing snapshots and cross-validated boxscores.
    """
    settled_records = []
    quarantined_records = []

    for entry in pending_entries:
        closing = closing_map.get(entry.receipt_hash) or closing_map.get(f"{entry.player_name}::{entry.market}")
        boxscore = boxscore_map.get(entry.player_id) or boxscore_map.get(entry.player_name)

        if not closing or not boxscore:
            quarantined_records.append({
                "entry_receipt_hash": entry.receipt_hash,
                "player": entry.player_name,
                "reason": "MISSING_CLOSING_SNAPSHOT_OR_BOXSCORE",
            })
            continue

        result = grade_receiving_prop(entry, closing, boxscore, house_rule_mode=house_rule_mode)
        if not result["finalized"]:
            quarantined_records.append(result)
        else:
            settled_records.append(result)

    return {
        "settled_count": len(settled_records),
        "quarantined_count": len(quarantined_records),
        "settled_receipts": settled_records,
        "quarantined_reviews": quarantined_records,
    }


if __name__ == "__main__":
    report = settle_slate(
        bets_path=Path("data/logged_bets_w7.json"),
        closing_snapshots_path=Path("data/snapshots_2026_w7.jsonl"),
        boxscores_path=Path("data/boxscores_2026_w7.json"),
        output_path=Path("public/clv_audit_report.json"),
    )
    print(
        f"✔ Settled {report['total_records']} records | CLV Beat: {report['beat_close_rate_pct']}% | "
        f"ROI: {report['realized_roi_pct']}% | Root: #{report['ledger_root_hash']}"
    )
