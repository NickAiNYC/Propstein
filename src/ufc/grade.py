"""UFC grading + CLV.

Rules (documented in research/ufc-gate1/IMPLEMENTATION.md):
  * A research decision is the model's lean side on h2h when model prob -
    no-vig market prob >= LEAN_GATE at the decision snapshot (pre, else post).
  * CLV = lock no-vig prob(side) - decision no-vig prob(side). No lock
    snapshot -> ungradable for CLV (never backfilled).
  * Result: win/loss. Draw, no contest, cancellation, scratch -> VOID (push),
    excluded from N. Totals are not graded yet (limited vendor coverage).
"""
from __future__ import annotations

from typing import Any

from .common import wilson
from .status import is_void

LEAN_GATE = 0.03


def decisions_for_card(card: dict, snapshots: dict) -> list[dict]:
    out = []
    for f in card.get("fights", []):
        fid = f["fight_id"]
        snaps = snapshots.get(fid, {})
        dec = snaps.get("pre") or snaps.get("post")
        model = (f.get("model") or {}).get("p")
        if not dec or not dec.get("h2h_novig") or not model:
            continue
        for side in (0, 1):
            edge = model[side] - dec["h2h_novig"][side]
            if edge >= LEAN_GATE:
                out.append({"fight_id": fid, "side": side,
                            "fighter": f["fighters"][side]["name"],
                            "decision_snapshot": "pre" if snaps.get("pre") else "post",
                            "model_p": model[side], "market_p": dec["h2h_novig"][side],
                            "edge": round(edge, 4)})
    return out


def grade_card(card: dict, snapshots: dict, results: dict[str, dict], status: dict) -> dict:
    """results: fight_id -> parsed ESPN fight (with winner flags/result)."""
    rows = []
    for d in decisions_for_card(card, snapshots):
        fid = d["fight_id"]
        res = results.get(fid)
        lock = (snapshots.get(fid) or {}).get("lock")
        r = dict(d)
        if lock and lock.get("h2h_novig"):
            r["lock_p"] = lock["h2h_novig"][d["side"]]
            r["clv"] = round(r["lock_p"] - d["market_p"], 4)
        else:
            r["clv"] = None
        if is_void(status, fid) or (res and res.get("result") in ("draw_or_nc", "cancelled")):
            r["result"] = "void"
        elif res and res.get("result") == "win":
            r["result"] = "win" if res["fighters"][d["side"]]["winner"] else "loss"
        else:
            r["result"] = "pending"
        rows.append(r)
    return {"event_id": card.get("event_id"), "event_name": card.get("event_name"), "decisions": rows}


def summarize(graded_cards: list[dict]) -> dict[str, Any]:
    rows = [r for c in graded_cards for r in c["decisions"]]
    clv_rows = [r for r in rows if r.get("clv") is not None and r["result"] != "void"]
    beat = sum(1 for r in clv_rows if r["clv"] > 0)
    settled = [r for r in rows if r["result"] in ("win", "loss")]
    ci = wilson(beat, len(clv_rows))
    return {
        "n_decisions": len(rows), "n_settled": len(settled),
        "n_void": sum(1 for r in rows if r["result"] == "void"),
        "wins": sum(1 for r in settled if r["result"] == "win"),
        "n_clv": len(clv_rows), "beat_close": beat,
        "beat_close_ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
        "mean_clv": round(sum(r["clv"] for r in clv_rows) / len(clv_rows), 4) if clv_rows else None,
        "edge_claim": "NO EDGE",
    }
