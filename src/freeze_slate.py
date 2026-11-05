"""
Freeze System: Immutable, append-only pre-kickoff and decision-time slate snapshots.
Specification:
- Append-only. Never updates or deletes existing snapshots.
- Every snapshot includes a sha256 content hash of the canonical JSON payload.
- Evaluation code only reads snapshots whose created_at <= decision time being evaluated.
- Role labels are flagged as is_provisional: True until chronological holdout evidence exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy import stats

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
VIEWER_DIR = BASE_DIR / "viewer"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"

sys.path.insert(0, str(SRC_DIR))

from model import ReceivingModel, american_to_prob, american_to_decimal


MODEL_VERSION = "negbin-gamma-v3.2"
MODEL_ALPHA = 0.1097
MODEL_K = 1.555
QUALIFICATION_POLICY_VERSION = "edge_10pct_v1"
EDGE_HURDLE = 0.10


def compute_rec_probs(mu_rec: float, line: float, alpha: float = MODEL_ALPHA) -> Tuple[float, float, float]:
    """Computes P(Over), P(Under), P(Push) for receptions with discrete integer handling."""
    r = 1.0 / alpha
    p = r / (r + mu_rec)
    is_whole = abs(line - round(line)) < 1e-4

    if is_whole:
        k = int(round(line))
        p_push = float(stats.nbinom.pmf(k, r, p))
        p_over = float(stats.nbinom.sf(k, r, p))
        p_under = max(0.001, 1.0 - p_over - p_push)
        s = p_over + p_under + p_push
        return p_over / s, p_under / s, p_push / s
    else:
        p_push = 0.0
        p_over = float(stats.nbinom.sf(int(line), r, p))
        p_under = max(0.001, 1.0 - p_over)
        s = p_over + p_under
        return p_over / s, p_under / s, 0.0


def compute_yards_probs(m: ReceivingModel, mu_rec: float, mu_ypr: float, line: float) -> Tuple[float, float, float]:
    """Computes P(Over), P(Under), P(Push) for receiving yards with discrete integer boundary handling."""
    is_whole = abs(line - round(line)) < 1e-4

    if is_whole:
        L = round(line)
        cdf_lo = 1.0 - m.p_yards_over(mu_rec, mu_ypr, L - 0.5)
        cdf_hi = 1.0 - m.p_yards_over(mu_rec, mu_ypr, L + 0.5)
        p_push = max(0.0, cdf_hi - cdf_lo)
        p_over = max(0.001, 1.0 - cdf_hi)
        p_under = max(0.001, cdf_lo)
        s = p_over + p_under + p_push
        return p_over / s, p_under / s, p_push / s
    else:
        p_push = 0.0
        p_over = float(m.p_yards_over(mu_rec, mu_ypr, line))
        p_under = max(0.001, 1.0 - p_over)
        s = p_over + p_under
        return p_over / s, p_under / s, 0.0


def prob_to_american(prob: float) -> str:
    if prob >= 0.999:
        return "-10000"
    if prob <= 0.001:
        return "+10000"
    if prob >= 0.5:
        odds = int(round(-100.0 * prob / (1.0 - prob)))
        return str(odds)
    else:
        odds = int(round(100.0 * (1.0 - prob) / prob))
        return f"+{odds}"


def evaluate_price_boundaries(
    m: ReceivingModel,
    mu_rec: float,
    mu_ypr: float,
    market: str,
    fair_line: float
) -> Dict[str, Any]:
    """Computes exact price boundaries required to clear 10% hurdle with positive EV."""
    step = 0.5 if market == "receptions" else 1.0
    dec_110 = american_to_decimal(-110)

    max_over_line = None
    min_under_line = None

    # Test lower lines for Over qualification
    l_test = fair_line - step
    while l_test >= max(0.5, fair_line - 30.0):
        if market == "receptions":
            p_over, p_under, p_push = compute_rec_probs(mu_rec, l_test)
        else:
            p_over, p_under, p_push = compute_yards_probs(m, mu_rec, mu_ypr, l_test)

        prob_edge = p_over - 0.50
        ev = p_over * (dec_110 - 1.0) - (1.0 - p_over - p_push)
        if prob_edge >= EDGE_HURDLE and ev > 0:
            max_over_line = l_test
            break
        l_test -= step

    # Test higher lines for Under qualification
    l_test = fair_line + step
    while l_test <= fair_line + 30.0:
        if market == "receptions":
            p_over, p_under, p_push = compute_rec_probs(mu_rec, l_test)
        else:
            p_over, p_under, p_push = compute_yards_probs(m, mu_rec, mu_ypr, l_test)

        prob_edge = p_under - 0.50
        ev = p_under * (dec_110 - 1.0) - (1.0 - p_under - p_push)
        if prob_edge >= EDGE_HURDLE and ev > 0:
            min_under_line = l_test
            break
        l_test += step

    # Break-even odds at the fair line
    if market == "receptions":
        fo, fu, _ = compute_rec_probs(mu_rec, fair_line)
    else:
        fo, fu, _ = compute_yards_probs(m, mu_rec, mu_ypr, fair_line)

    best_p = max(fo, fu)
    breakeven_odds = prob_to_american(best_p)

    return {
        "max_acceptable_over_line_at_minus_110": round(max_over_line, 1) if max_over_line is not None else round(fair_line - (1.0 if market == "receptions" else 6.0), 1),
        "min_acceptable_under_line_at_minus_110": round(min_under_line, 1) if min_under_line is not None else round(fair_line + (1.0 if market == "receptions" else 6.0), 1),
        "breakeven_odds_at_fair": breakeven_odds
    }


def classify_role_shift(row: Dict[str, Any]) -> Dict[str, Any]:
    """Classifies offensive role shift. Explicitly marked as provisional."""
    recent_share = float(row.get("target_share") or 0.0)
    baseline_share = float(row.get("f_tgt_share") or 0.0)
    career_tgts = float(row.get("c_targets") or 0.0)
    games_prior = int(row.get("games_prior") or 0)
    target_sd = float(row.get("f_tgt_sd") or 3.0)
    delta = recent_share - baseline_share

    if recent_share == 0.0 and baseline_share == 0.0:
        label = "none"
    elif delta >= 0.08 and games_prior >= 12 and baseline_share >= 0.15:
        label = "sustained_surge"
    elif delta >= 0.12 and (target_sd >= 3.8 or games_prior < 20 or baseline_share < 0.14):
        label = "one_game_spike"
    elif delta <= -0.08:
        label = "contraction"
    elif baseline_share >= 0.22 or career_tgts >= 6.5:
        label = "established_volume"
    else:
        label = "none"

    return {
        "label": label,
        "is_provisional": True,
        "provisional_note": "Role labels and thresholds remain provisional pending chronological holdout validation.",
        "recent_window": "last_1_game",
        "baseline_window": "prior_8_games_ewma",
        "recent_target_share": round(recent_share, 4),
        "baseline_target_share": round(baseline_share, 4),
        "delta": round(delta, 4),
        "career_games": games_prior,
        "target_sd": round(target_sd, 2),
        "missing_route_data": True,  # Box score/pbp only; official GPS tracking feed unintegrated
        "raw_observations": {
            "targets": int(row.get("targets") or 0),
            "receptions": int(row.get("receptions") or 0),
            "receiving_yards": int(row.get("receiving_yards") or 0),
            "f_targets": round(float(row.get("f_targets") or 0.0), 2),
            "f_rec": round(float(row.get("f_rec") or 0.0), 2),
            "f_yards": round(float(row.get("f_yards") or 0.0), 2),
            "air_yards_share": round(float(row.get("air_yards_share") or 0.0), 4),
            "f_ay_share": round(float(row.get("f_ay_share") or 0.0), 4),
            "adot": round(float(row.get("adot") or 0.0), 2),
            "f_adot": round(float(row.get("f_adot") or 0.0), 2)
        }
    }


def compute_canonical_hash(payload_without_hash: Dict[str, Any]) -> str:
    """Computes SHA-256 hash of canonical JSON string with sorted keys."""
    canonical_json = json.dumps(payload_without_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def freeze_slate(
    season: int = 2026,
    week: int = 7,
    game_id: Optional[str] = None,
    snapshot_type: str = "pre_kickoff",
    created_at: Optional[str] = None,
    game_ids: Optional[set[str]] = None,
    quotes_feed: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
    require_active_quotes: bool = False,
    alert_dir: Optional[Path] = None,
    kickoff_time: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Path, Path]:
    """
    Creates immutable, versioned snapshot records for the specified slate or game.
    Saves to:
    1. snapshots/snapshots_{season}_w{week}.jsonl (append-only log)
    2. viewer/snapshots_{season}_w{week}.json (viewer accessible snapshot bundle)
    When require_active_quotes is True, couples candidate generation to active quotes
    (roster INNER JOIN active_quotes), preventing unquoted candidates from polluting journals.
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    slate_key = f"{season}_w{week}"
    slate_file = VIEWER_DIR / f"slate_{slate_key}.json"

    if not slate_file.exists():
        raise FileNotFoundError(f"Slate file not found: {slate_file}")

    with open(slate_file, "r", encoding="utf-8") as f:
        slate_rows = json.load(f)

    # Filter to specific game if requested (e.g. TNF: 2026_07_NE_CHI)
    if game_id:
        slate_rows = [p for p in slate_rows if p.get("game_id") == game_id]
        if not slate_rows:
            raise ValueError(f"No players found for game_id: {game_id}")
    if game_ids is not None:
        slate_rows = [p for p in slate_rows if p.get("game_id") in game_ids]
        found = {p.get("game_id") for p in slate_rows}
        if found != game_ids:
            raise ValueError(f"Missing slate rows for games: {sorted(game_ids - found)}")

    m = ReceivingModel(
        rec_params=None,
        ypr_params=None,
        alpha=MODEL_ALPHA,
        k=MODEL_K,
        means=None,
        sds=None,
        cols=None
    )

    snapshots: List[Dict[str, Any]] = []

    quotes_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if quotes_feed:
        feed_items = quotes_feed.values() if isinstance(quotes_feed, dict) else quotes_feed
        for q in feed_items:
            qid = str(q.get("player_id", ""))
            qname = str(q.get("player_name", "")).lower()
            qmkt = str(q.get("market", ""))
            if qid and qmkt:
                quotes_index[(qid, qmkt)] = q
            if qname and qmkt:
                quotes_index[(qname, qmkt)] = q

    for row in slate_rows:
        p_id = row.get("player_id", "")
        p_name = row.get("player_display_name", "")
        p_team = row.get("team", "")
        p_opp = row.get("opponent_team", "")
        p_game = row.get("game_id", f"{season}_{week:02d}_{p_team}_{p_opp}")
        mu_rec = float(row.get("mu_rec", 0.0))
        mu_ypr = float(row.get("mu_ypr", 0.0))
        fair_yards = float(row.get("fair_line_yards", 0.0))
        fair_rec = float(row.get("fair_line_rec", 0.0))
        proj_yards = float(row.get("proj_yards", 0.0))
        proj_rec = float(row.get("proj_rec", 0.0))

        role_info = classify_role_shift(row)

        # -------------------------------------------------------------
        # Market 1: receiving_yards
        # -------------------------------------------------------------
        q_yards = quotes_index.get((p_id, "receiving_yards")) or quotes_index.get((p_name.lower(), "receiving_yards"))
        if not (require_active_quotes and not q_yards):
            py_over, py_under, py_push = compute_yards_probs(m, mu_rec, mu_ypr, fair_yards)
            boundaries_yards = evaluate_price_boundaries(m, mu_rec, mu_ypr, "yards", fair_yards)

            snap_yards = {
                "snapshot_id": str(uuid.uuid4()),
                "snapshot_type": snapshot_type,
                "created_at": timestamp,
                "slate": f"{season}-W{week:02d}",
                "game_id": p_game,
                "player_id": p_id,
                "player_name": p_name,
                "team": p_team,
                "opponent": p_opp,
                "position": row.get("position", "WR"),
                "market": "receiving_yards",
                "model": {
                    "version": MODEL_VERSION,
                    "alpha": MODEL_ALPHA,
                    "k": MODEL_K,
                    "calibration_bias": 0.0 if week > 1 else 0.088,
                    "input_cutoff": timestamp
                },
                "role": role_info,
                "projection": {
                    "fair_line": fair_yards,
                    "proj_volume": round(proj_yards, 2),
                    "distribution_params": {
                        "mu_rec": round(mu_rec, 4),
                        "mu_ypr": round(mu_ypr, 4),
                        "alpha": MODEL_ALPHA,
                        "k": MODEL_K
                    },
                    "p_over": round(py_over, 4),
                    "p_under": round(py_under, 4),
                    "p_push": round(py_push, 4)
                },
                "price_boundaries": boundaries_yards,
                "qualification_policy": {
                    "version": QUALIFICATION_POLICY_VERSION,
                    "edge_hurdle": EDGE_HURDLE,
                    "require_positive_ev": True
                },
                "quote": {
                    "status": "unquoted" if not q_yards else q_yards.get("status", "observed"),
                    "source": None if not q_yards else (q_yards.get("book") or q_yards.get("source")),
                    "book": None if not q_yards else q_yards.get("book"),
                    "line": None if not q_yards else q_yards.get("line"),
                    "odds": None if not q_yards else q_yards.get("odds", -110),
                    "over_odds": None if not q_yards else q_yards.get("over_odds"),
                    "under_odds": None if not q_yards else q_yards.get("under_odds"),
                    "observed_at": None if not q_yards else q_yards.get("observed_at", timestamp),
                    "quote_id": None if not q_yards else q_yards.get("quote_id"),
                    "evaluation": None if not q_yards else q_yards.get("evaluation"),
                },
                "scenario_assumptions": None
            }
            snap_yards["content_hash"] = compute_canonical_hash(snap_yards)
            snapshots.append(snap_yards)

        # -------------------------------------------------------------
        # Market 2: receptions
        # -------------------------------------------------------------
        q_rec = quotes_index.get((p_id, "receptions")) or quotes_index.get((p_name.lower(), "receptions"))
        if not (require_active_quotes and not q_rec):
            pr_over, pr_under, pr_push = compute_rec_probs(mu_rec, fair_rec)
            boundaries_rec = evaluate_price_boundaries(m, mu_rec, mu_ypr, "receptions", fair_rec)

            snap_rec = {
                "snapshot_id": str(uuid.uuid4()),
                "snapshot_type": snapshot_type,
                "created_at": timestamp,
                "slate": f"{season}-W{week:02d}",
                "game_id": p_game,
                "player_id": p_id,
                "player_name": p_name,
                "team": p_team,
                "opponent": p_opp,
                "position": row.get("position", "WR"),
                "market": "receptions",
                "model": {
                    "version": MODEL_VERSION,
                    "alpha": MODEL_ALPHA,
                    "k": MODEL_K,
                    "calibration_bias": 0.0 if week > 1 else 0.057,
                    "input_cutoff": timestamp
                },
                "role": role_info,
                "projection": {
                    "fair_line": fair_rec,
                    "proj_volume": round(proj_rec, 2),
                    "distribution_params": {
                        "mu_rec": round(mu_rec, 4),
                        "mu_ypr": round(mu_ypr, 4),
                        "alpha": MODEL_ALPHA,
                        "k": MODEL_K
                    },
                    "p_over": round(pr_over, 4),
                    "p_under": round(pr_under, 4),
                    "p_push": round(pr_push, 4)
                },
                "price_boundaries": boundaries_rec,
                "qualification_policy": {
                    "version": QUALIFICATION_POLICY_VERSION,
                    "edge_hurdle": EDGE_HURDLE,
                    "require_positive_ev": True
                },
                "quote": {
                    "status": "unquoted" if not q_rec else q_rec.get("status", "observed"),
                    "source": None if not q_rec else (q_rec.get("book") or q_rec.get("source")),
                    "book": None if not q_rec else q_rec.get("book"),
                    "line": None if not q_rec else q_rec.get("line"),
                    "odds": None if not q_rec else q_rec.get("odds", -110),
                    "over_odds": None if not q_rec else q_rec.get("over_odds"),
                    "under_odds": None if not q_rec else q_rec.get("under_odds"),
                    "observed_at": None if not q_rec else q_rec.get("observed_at", timestamp),
                    "quote_id": None if not q_rec else q_rec.get("quote_id"),
                    "evaluation": None if not q_rec else q_rec.get("evaluation"),
                },
                "scenario_assumptions": None
            }
            snap_rec["content_hash"] = compute_canonical_hash(snap_rec)
            snapshots.append(snap_rec)

    # Fail-closed check: when require_active_quotes=True and zero active quotes were matched,
    # abort immediately, write structured alert marker, and never append empty snapshots.
    if require_active_quotes and not snapshots:
        now_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        min_mins_to_kickoff = 999.0
        if kickoff_time:
            k_dt = datetime.fromisoformat(kickoff_time.replace("Z", "+00:00"))
            min_mins_to_kickoff = (k_dt - now_dt).total_seconds() / 60.0

        if min_mins_to_kickoff > 180:
            reason_code = "PRE_POST"
            reason_detail = f"Markets legitimately not posted yet ({min_mins_to_kickoff:.0f} mins to kickoff). Retry scheduled closer to kickoff."
        else:
            reason_code = "ADAPTER_FAILURE"
            reason_detail = f"Zero quotes captured within {min_mins_to_kickoff:.0f} mins of kickoff. Odds ingestion adapter failed or feed down."

        target_dir = alert_dir or (BASE_DIR / "data" / "pipeline_alerts")
        target_dir.mkdir(parents=True, exist_ok=True)
        date_str = now_dt.strftime("%Y%m%d_%H%M%S")
        alert_file = target_dir / f"{date_str}_empty_quotes_alert.json"
        alert_payload = {
            "timestamp": timestamp,
            "status": "REJECTED_EMPTY_QUOTES",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "slate": slate_key,
            "candidates_generated": 0,
            "required_active_quotes": True,
        }
        alert_file.write_text(json.dumps(alert_payload, indent=2), encoding="utf-8")
        raise ValueError(
            f"Freeze aborted [{reason_code}]: {reason_detail} "
            f"Zero active quotes found across candidate roster universe. Alert written to {alert_file}"
        )

    # Validate and publish the viewer bundle before appending to the journal.
    # A rejected payload must never leave an untracked frozen decision behind.
    jsonl_path = SNAPSHOTS_DIR / f"snapshots_{season}_w{week}.jsonl"
    viewer_json_path = VIEWER_DIR / f"snapshots_{season}_w{week}.json"
    existing_viewer: List[Dict[str, Any]] = []
    if viewer_json_path.exists():
        with open(viewer_json_path, "r", encoding="utf-8") as f:
            existing_viewer = json.load(f)
        if not isinstance(existing_viewer, list):
            raise ValueError("existing viewer snapshot bundle must be a list")

    # Merge by unique snapshot_id
    existing_ids = {s["snapshot_id"] for s in existing_viewer}
    combined_viewer = existing_viewer + [s for s in snapshots if s["snapshot_id"] not in existing_ids]

    from src.contracts.snapshot import SnapshotRow
    from src.contracts.gate import validate_and_publish
    ok, _manifest = validate_and_publish(
        schema_cls=SnapshotRow,
        raw_data=combined_viewer,
        target_path=viewer_json_path,
        source_feed=f"freeze_slate_{slate_key}",
    )
    if not ok:
        raise ValueError("snapshot contract rejected the freeze; journal was not appended")
    with open(jsonl_path, "a", encoding="utf-8") as f:
        for s in snapshots:
            f.write(json.dumps(s) + "\n")
        f.flush()
        os.fsync(f.fileno())

    return snapshots, jsonl_path, viewer_json_path


def main():
    parser = argparse.ArgumentParser(description="Freeze immutable pre-kickoff slate snapshot")
    parser.add_argument("--season", type=int, default=2026, help="NFL Season")
    parser.add_argument("--week", type=int, default=7, help="NFL Week")
    parser.add_argument("--game-id", type=str, default=None, help="Filter to specific game_id (e.g. 2026_07_NE_CHI)")
    parser.add_argument("--all-games", action="store_true", help="Freeze entire slate")
    parser.add_argument("--snapshot-type", type=str, default="pre_kickoff", choices=["pre_kickoff", "first_published", "material_revision", "closing"])
    parser.add_argument("--cutoff-time", type=str, default=None, help="Custom ISO cutoff timestamp")
    args = parser.parse_args()

    game_target = None if args.all_games else args.game_id

    print(f"============================================================")
    print(f"NFL PROPS FREEZE SYSTEM: PRE-KICKOFF SNAPSHOT CREATION")
    print(f"Season: {args.season} | Week: {args.week}")
    print(f"Target: {'Full Slate (All Games)' if args.all_games else (game_target or 'TNF (2026_07_NE_CHI)')}")
    print(f"Snapshot Type: {args.snapshot_type}")
    print(f"============================================================")

    # Default to TNF if no game specified and not all_games
    if not args.all_games and not game_target:
        game_target = f"{args.season}_{args.week:02d}_NE_CHI"

    snapshots, jsonl_file, viewer_file = freeze_slate(
        season=args.season,
        week=args.week,
        game_id=game_target,
        snapshot_type=args.snapshot_type,
        created_at=args.cutoff_time
    )

    print(f"✓ Frozen {len(snapshots)} individual player-market records.")
    print(f"✓ Append-only storage: {jsonl_file}")
    print(f"✓ Viewer bundle: {viewer_file}")
    if snapshots:
        sample = snapshots[0]
        print(f"\n--- Canonical Sample Record ---")
        print(f"Snapshot ID:  {sample['snapshot_id']}")
        print(f"Player:       {sample['player_name']} ({sample['team']}) vs {sample['opponent']}")
        print(f"Market:       {sample['market']} | Fair: {sample['projection']['fair_line']}")
        print(f"Role Label:   {sample['role']['label']} (is_provisional: {sample['role']['is_provisional']})")
        print(f"P(Over/Un/Ps): {sample['projection']['p_over']} / {sample['projection']['p_under']} / {sample['projection']['p_push']}")
        print(f"Price Bound:  Over <= {sample['price_boundaries']['max_acceptable_over_line_at_minus_110']} | Odds: {sample['price_boundaries']['breakeven_odds_at_fair']}")
        print(f"SHA-256 Hash: {sample['content_hash']}")
    print(f"============================================================")


if __name__ == "__main__":
    main()
