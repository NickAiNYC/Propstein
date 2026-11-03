"""
settlement_engine.py — Two-Stage Deterministic Settlement Engine for PropWire

Implements fail-closed settlement:
  Stage A: Kickoff Closing Line Lock (ClosingSnapshot)
  Stage B: Official Gamebook Boxscore Resolution (OfficialBoxscoreStat)

Chains Entry -> Closing -> Settlement into an immutable 3-hash audit receipt.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

from src.crypto_utils import canonical_json_dumps, canonical_json_sha256


class SettlementOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"
    VOID_INACTIVE_OR_ZERO_SNAP = "VOID_INACTIVE_OR_ZERO_SNAP"
    QUARANTINED_STAT_DISCREPANCY = "QUARANTINED_STAT_DISCREPANCY"


@dataclass(frozen=True)
class EntryReceipt:
    receipt_hash: str
    player_id: str
    player_name: str
    book: str
    market: str          # e.g., "receiving_yards" or "receptions"
    direction: str       # "OVER" | "UNDER"
    entry_line: float    # e.g., 43.5
    entry_price: int     # e.g., -115
    fair_line_at_entry: float
    entry_ts: int        # epoch ms


@dataclass(frozen=True)
class ClosingSnapshot:
    closing_line: float
    closing_over_odds: int
    closing_under_odds: int
    closing_fair_line: float
    provider_update_ts: int
    raw_payload_sha256: str
    closing_snapshot_sha256: str
    clv_delta_yards: float
    clv_no_vig_pct: float


@dataclass(frozen=True)
class OfficialBoxscoreStat:
    provider_game_id: str
    game_status: str     # Must be "FINAL_OFFICIAL"
    active_gameday_roster: bool
    offensive_snaps: Optional[int]
    receiving_yards: Optional[float]
    source_primary: str   # e.g., "sleeper_official"
    source_secondary: str # e.g., "espn_gamebook"
    stat_matches_across_sources: bool
    boxscore_payload_sha256: str


def american_to_implied_prob(odds: int) -> float:
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def devig_two_way_market(over_odds: int, under_odds: int) -> Dict[str, float]:
    p_over_raw = american_to_implied_prob(over_odds)
    p_under_raw = american_to_implied_prob(under_odds)
    book_hold = p_over_raw + p_under_raw
    return {
        "over_prob": round(p_over_raw / book_hold, 6),
        "under_prob": round(p_under_raw / book_hold, 6),
    }


def compute_entry_clv(
    direction: str,
    entry_line: float,
    entry_odds: int,
    closing_line: float,
    closing_over_odds: int,
    closing_under_odds: int,
    gamma_dispersion_yards: float = 18.5,
) -> Dict[str, float]:
    """
    Calculates both directional yardage CLV and no-vig probability CLV.
    Accounts for both line movement (yards) and juice movement (odds).
    """
    devig_close = devig_two_way_market(closing_over_odds, closing_under_odds)
    entry_implied_prob = american_to_implied_prob(entry_odds)
    dir_upper = direction.upper()

    if dir_upper == "OVER":
        clv_delta_yards = round(closing_line - entry_line, 2)
        base_close_prob = devig_close["over_prob"]
    elif dir_upper == "UNDER":
        clv_delta_yards = round(entry_line - closing_line, 2)
        base_close_prob = devig_close["under_prob"]
    else:
        raise ValueError(f"Unsupported direction: {direction}")

    yard_prob_shift = math.erf(clv_delta_yards / (math.sqrt(2.0) * gamma_dispersion_yards)) * 0.5
    true_closing_win_prob = min(0.99, max(0.01, base_close_prob + yard_prob_shift))
    clv_no_vig_pct = round(((true_closing_win_prob / entry_implied_prob) - 1.0) * 100.0, 2)

    return {
        "clv_delta_yards": clv_delta_yards,
        "clv_no_vig_pct": clv_no_vig_pct,
    }


def grade_receiving_prop(
    entry: EntryReceipt,
    closing: ClosingSnapshot,
    boxscore: OfficialBoxscoreStat,
    house_rule_mode: str = "ONE_SNAP_REQUIRED",
) -> Dict[str, Any]:
    """
    Fail-closed deterministic prop grader.
    Never grades WIN/LOSS if primary and secondary boxscore feeds disagree
    or if snap counts are not yet finalized.
    """
    # 1. Fail closed if game is not officially final or sources conflict
    if boxscore.game_status != "FINAL_OFFICIAL" or not boxscore.stat_matches_across_sources:
        outcome = SettlementOutcome.QUARANTINED_STAT_DISCREPANCY
        settled_stat = None

    # 2. Enforce Inactive / Zero-Snap Void Rules
    elif not boxscore.active_gameday_roster:
        outcome = SettlementOutcome.VOID_INACTIVE_OR_ZERO_SNAP
        settled_stat = 0.0
    elif house_rule_mode == "ONE_SNAP_REQUIRED" and (
        boxscore.offensive_snaps is None or boxscore.offensive_snaps == 0
    ):
        if boxscore.offensive_snaps is None:
            outcome = SettlementOutcome.QUARANTINED_STAT_DISCREPANCY
            settled_stat = None
        else:
            outcome = SettlementOutcome.VOID_INACTIVE_OR_ZERO_SNAP
            settled_stat = 0.0

    # 3. Grade Standard Over/Under Outcome
    else:
        if boxscore.receiving_yards is None:
            outcome = SettlementOutcome.QUARANTINED_STAT_DISCREPANCY
            settled_stat = None
        else:
            settled_stat = float(boxscore.receiving_yards)
            dir_upper = entry.direction.upper()
            if settled_stat == entry.entry_line:
                outcome = SettlementOutcome.PUSH
            elif dir_upper == "OVER":
                outcome = SettlementOutcome.WIN if settled_stat > entry.entry_line else SettlementOutcome.LOSS
            elif dir_upper == "UNDER":
                outcome = SettlementOutcome.WIN if settled_stat < entry.entry_line else SettlementOutcome.LOSS
            else:
                raise ValueError(f"Invalid direction: {entry.direction}")

    settlement_payload = {
        "schema_version": "propwire.settlement.v1",
        "entry_receipt_hash": entry.receipt_hash,
        "player_id": entry.player_id,
        "market": entry.market,
        "direction": entry.direction,
        "entry_line": entry.entry_line,
        "entry_price": entry.entry_price,
        "closing_line": closing.closing_line,
        "closing_over_odds": closing.closing_over_odds,
        "closing_under_odds": closing.closing_under_odds,
        "clv_delta_yards": closing.clv_delta_yards,
        "clv_no_vig_pct": closing.clv_no_vig_pct,
        "closing_payload_sha256": closing.closing_snapshot_sha256,
        "settled_receiving_yards": settled_stat,
        "offensive_snaps": boxscore.offensive_snaps,
        "outcome": outcome.value,
        "boxscore_payload_sha256": boxscore.boxscore_payload_sha256,
    }

    settlement_hash = canonical_json_sha256(settlement_payload)
    return {
        **settlement_payload,
        "settlement_receipt_hash": settlement_hash,
        "finalized": outcome != SettlementOutcome.QUARANTINED_STAT_DISCREPANCY,
    }
