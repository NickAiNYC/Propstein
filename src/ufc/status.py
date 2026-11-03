"""Per-card fighter-status layer (scratches, replacements, missed weight,
cancellations). Auto-detected by diffing the new ESPN card against the last
written card, merged with a hand-maintained overrides file. Statuses that make
a fight unbettable/ungradable mark it void for the UI and the grader."""
from __future__ import annotations

from datetime import datetime, timezone

VOID_STATUSES = {"cancelled", "scratched", "no_contest", "draw"}
STATUSES = {"scheduled", "replacement", "missed_weight", "cancelled", "scratched",
            "final", "draw", "no_contest"}


def _ids(f: dict) -> set:
    return {x["id"] for x in f["fighters"]}


def diff_status(prev_fights: list[dict], new_fights: list[dict], prev_status: dict,
                now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {k: dict(v) for k, v in (prev_status or {}).items()}
    new_by_id = {f["fight_id"]: f for f in new_fights}
    for f in new_fights:
        cur = out.get(f["fight_id"], {"status": "scheduled", "events": []})
        if f.get("result") == "win":
            cur["status"] = "final"
        elif f.get("result") == "draw_or_nc":
            cur["status"] = "draw"  # ESPN cannot distinguish draw from NC; both void
        elif f.get("result") == "cancelled":
            cur["status"] = "cancelled"
        out[f["fight_id"]] = cur
    for p in prev_fights or []:
        if p["fight_id"] in new_by_id:
            continue
        # fight vanished: replacement if one fighter is on a new bout, else cancelled
        repl = next((f for f in new_fights if _ids(f) & _ids(p) and f["fight_id"] not in
                     {q["fight_id"] for q in prev_fights}), None)
        st = out.setdefault(p["fight_id"], {"status": "scheduled", "events": []})
        if st["status"] not in ("cancelled", "scratched"):
            st["status"] = "scratched" if repl else "cancelled"
            st["events"].append({"at": ts, "type": st["status"],
                                 "detail": f"{' vs '.join(x['name'] for x in p['fighters'])} left the card"})
        if repl:
            r = out.setdefault(repl["fight_id"], {"status": "scheduled", "events": []})
            r["status"] = "replacement"
            r["short_notice"] = True
            r["events"].append({"at": ts, "type": "replacement",
                                "detail": f"replaces {' vs '.join(x['name'] for x in p['fighters'])}"})
    return out


def apply_overrides(status: dict, overrides: dict) -> dict:
    """overrides: {fight_id: {"status": "missed_weight", "detail": "..."}}"""
    for fid, o in (overrides or {}).items():
        st = o.get("status")
        if st not in STATUSES:
            continue
        cur = status.setdefault(fid, {"status": "scheduled", "events": []})
        if cur["status"] in ("final", "draw") and st not in VOID_STATUSES:
            continue
        cur["status"] = st
        cur.setdefault("events", []).append({"at": o.get("at"), "type": st, "detail": o.get("detail", "manual")})
    return status


def is_void(status: dict, fight_id: str) -> bool:
    return (status.get(fight_id) or {}).get("status") in VOID_STATUSES
