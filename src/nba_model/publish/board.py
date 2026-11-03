"""Board builder — top-8 plays behind fail-closed gates, with SHA-256 receipts.

Reuses PropWire's existing trust primitive (src/crypto_utils.py, RFC-8785
canonical JSON) so the board receipt is byte-identical across the Python
pipeline, the Node viewer, and any independent notary client. Board history
is append-only and hash-chained (each receipt carries prev_sha256), the
same discipline as the freeze system.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .. import config
from .._compat import crypto_utils
from ..eval.devig import group_quotes, market_consensus
from ..model.distribution import PointsDistribution
from .gates import (
    GateCheck,
    evaluate_calibration_gate,
    evaluate_freshness_gate,
    evaluate_play_quote_gate,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_board(
    preds: pd.DataFrame,
    quotes: list[dict],
    wf_summary: dict,
    dataset_meta: dict,
    now: pd.Timestamp | None = None,
    board_size: int | None = None,
) -> dict:
    """Returns {"status": "PUBLISHED"|"REFUSED", ...} — never raises for gate failures."""
    now = now or pd.Timestamp.utcnow().tz_localize(None)
    board_size = board_size or config.BOARD_SIZE

    calib_report = evaluate_calibration_gate(wf_summary)
    fresh_report = evaluate_freshness_gate(dataset_meta, quotes, now=now)
    gate_payload = {
        "calibration": calib_report.to_dict(),
        "freshness": fresh_report.to_dict(),
    }

    if not calib_report.all_passed or not fresh_report.all_passed:
        return {
            "status": "REFUSED",
            "slate_date": dataset_meta.get("max_game_date"),
            "reasons": calib_report.fail_reasons + fresh_report.fail_reasons,
            "gates": gate_payload,
            "n_predictions": wf_summary.get("n", 0),
            "generated_at": _utcnow_iso(),
        }

    grouped = group_quotes(quotes, market=config.MARKET)
    candidates: list[dict] = []
    quote_gate_failures = 0

    for _, p in preds.iterrows():
        if p.get("below_minutes_floor"):
            continue
        dist = PointsDistribution(mean=float(p["mean_pts"]), sd=float(p["sd_pts"]))
        for (player_id, line), qgroup in grouped.items():
            if player_id != p["player_id"]:
                continue
            consensus = market_consensus(qgroup)
            if consensus is None:
                continue
            qgate = evaluate_play_quote_gate(consensus, now=now)
            if not qgate.all_passed:
                quote_gate_failures += 1
                continue

            m_over, m_push = dist.p_over(line), dist.p_push(line)
            m_under = dist.p_under(line)
            k_over = consensus["p_over"]
            k_under = max(0.0, 1.0 - k_over)
            edge_over = m_over - k_over
            edge_under = m_under - k_under
            side, model_p, market_p, edge = (
                ("OVER", m_over, k_over, edge_over)
                if edge_over >= edge_under else
                ("UNDER", m_under, k_under, edge_under)
            )
            if edge < config.EDGE_HURDLE:
                continue
            candidates.append({
                "player_id": player_id,
                "player_name": p["player_display_name"],
                "team": p["team"],
                "opponent": p["opponent"],
                "game_id": p["game_id"],
                "market": config.MARKET,
                "line": float(line),
                "side": side,
                "model_p": round(model_p, 4),
                "market_p_devig": round(market_p, 4),
                "edge": round(edge, 4),
                "model_price_american": dist.prob_to_american(model_p, vig=0.045),
                "books": consensus["books"],
                "n_books": consensus["n_books"],
                "latest_observed_at": consensus["latest_observed_at"],
                "model_mean_pts": float(p["mean_pts"]),
                "model_sd_pts": float(p["sd_pts"]),
                "model_push_p": round(m_push, 4),
                "explain": p["explain"],
                "quote_gate": qgate.to_dict(),
            })

    candidates.sort(key=lambda x: x["edge"], reverse=True)
    plays = candidates[:board_size]

    payload = {
        "schema": "propwire.nba_board.v1",
        "model_id": config.MODEL_ID,
        "model_version": config.MODEL_VERSION,
        "slate_date": dataset_meta.get("max_game_date"),
        "generated_at": _utcnow_iso(),
        "gates": gate_payload,
        "walk_forward": {
            "n": wf_summary.get("n"),
            "brier_model": wf_summary.get("brier_model"),
            "brier_market": wf_summary.get("brier_market"),
            "brier_vs_market": wf_summary.get("brier_vs_market"),
            "calibration_slope": wf_summary.get("calibration_slope"),
            "uncalibrated": wf_summary.get("uncalibrated"),
        },
        "dataset_meta": {
            "source": dataset_meta.get("source"),
            "all_fixture": dataset_meta.get("all_fixture"),
            "n_games": dataset_meta.get("n_games"),
            "n_players": dataset_meta.get("n_players"),
            "min_game_date": dataset_meta.get("min_game_date"),
            "max_game_date": dataset_meta.get("max_game_date"),
        },
        "n_candidates": len(candidates),
        "n_quote_gate_failures": quote_gate_failures,
        "plays": plays,
    }
    return {"status": "PUBLISHED", "payload": payload}


def _canonical_sha256(payload: dict) -> str:
    cu = crypto_utils()
    return cu.canonical_json_sha256(payload)


def publish_board(
    result: dict,
    out_dir: str | Path,
) -> tuple[Path, str]:
    """Write the board (or refusal) + append-only history entry.

    History file: nba_board_history.jsonl — one JSON line per publish
    attempt, hash-chained via prev_sha256. Never rewritten, never sorted.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    history_path = out / "nba_board_history.jsonl"

    prev_hash = ""
    if history_path.exists():
        lines = [ln for ln in history_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            prev_hash = str(json.loads(lines[-1]).get("sha256", ""))
        else:
            lines = []
    else:
        lines = []

    body = result.get("payload") if result["status"] == "PUBLISHED" else result
    receipt = {
        "status": result["status"],
        "locked_at": _utcnow_iso(),
        "sha256": _canonical_sha256(body),
        "prev_sha256": prev_hash,
        "model_version": config.MODEL_VERSION,
    }

    slate_date = result.get("slate_date") or "undated"
    suffix = "" if result["status"] == "PUBLISHED" else "_REFUSED"
    board_path = out / f"nba_board_{slate_date}{suffix}.json"
    with open(board_path, "w", encoding="utf-8") as fh:
        json.dump({"receipt": receipt, **body}, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    lines.append(json.dumps(receipt, sort_keys=True))
    history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return board_path, receipt["sha256"]
