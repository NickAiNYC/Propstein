"""ESPN public UFC scoreboard/athlete feeds -> normalized fights.

Source decision: ESPN's public site API (already used by PropStein for NFL/NBA
schedules, photos and box scores) is the UFC card, result and fighter-bio
source. UFCStats is NOT scraped: it publishes no API or data licence, so the
per-fight strike/takedown stats it carries stay out of scope until a licensed
source exists (documented in research/ufc-gate1/IMPLEMENTATION.md).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
ATHLETE = "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{id}"
UA = {"User-Agent": "PropStein-ufc/1.0"}


def get_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if len(s) == 22 and s[16] == "+":  # 2026-10-31T21:00+00:00
        s = s[:16] + ":00" + s[16:]
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_competition(event: dict, comp: dict) -> dict:
    st = comp.get("status") or {}
    stype = st.get("type") or {}
    fighters = []
    for c in sorted(comp.get("competitors") or [], key=lambda x: x.get("order", 9)):
        ath = c.get("athlete") or {}
        rec = next((r.get("summary") for r in c.get("records") or [] if r.get("type") == "total"), None)
        fighters.append({
            "id": str(c.get("id")),
            "name": ath.get("displayName") or ath.get("fullName"),
            "record": rec,
            "flag": (ath.get("flag") or {}).get("href"),
            "winner": bool(c.get("winner")),
        })
    completed = bool(stype.get("completed"))
    name = stype.get("name", "")
    if completed:
        if any(f["winner"] for f in fighters):
            result = "win"
        else:
            result = "draw_or_nc"
    elif name in ("STATUS_CANCELED", "STATUS_POSTPONED"):
        result = "cancelled"
    else:
        result = None
    sched = ((comp.get("format") or {}).get("regulation") or {}).get("periods") or 3
    end_round = st.get("period") if completed else None
    clock = st.get("clock") if completed else None
    end_time = None
    if completed and end_round:
        end_time = round((end_round - 1) + min(float(clock or 0), 300.0) / 300.0, 4)
    went_distance = None
    if completed and end_round:
        went_distance = bool(end_round >= sched and float(clock or 0) >= 299.0)
    return {
        "fight_id": str(comp.get("id")),
        "event_id": str(event.get("id")),
        "event_name": event.get("name"),
        "start": comp.get("date") or event.get("date"),
        "weight_class": (comp.get("type") or {}).get("abbreviation"),
        "sched_rounds": int(sched),
        "status_name": name,
        "completed": completed,
        "result": result,
        "end_round": end_round,
        "end_time_rounds": end_time,
        "went_distance": went_distance,
        "fighters": fighters,
    }


def parse_scoreboard(data: dict) -> list[dict]:
    fights = []
    for ev in data.get("events") or []:
        for comp in ev.get("competitions") or []:
            if len(comp.get("competitors") or []) == 2:
                fights.append(parse_competition(ev, comp))
    return fights


def fetch_range(dates: str) -> list[dict]:
    """dates = 'YYYY', 'YYYYMMDD' or 'YYYYMMDD-YYYYMMDD'."""
    return parse_scoreboard(get_json(f"{SCOREBOARD}?dates={dates}&limit=1000"))


def next_card(fights: list[dict], now: datetime, grace_hours: float = 8.0) -> list[dict]:
    """All fights of the earliest event whose last fight has not ended long ago."""
    by_event: dict[str, list[dict]] = {}
    for f in fights:
        by_event.setdefault(f["event_id"], []).append(f)
    best = None
    for eid, fs in by_event.items():
        starts = [t for t in (_parse_ts(f["start"]) for f in fs) if t]
        if not starts:
            continue
        if max(starts).timestamp() + grace_hours * 3600 < now.timestamp():
            continue
        if best is None or min(starts) < best[0]:
            best = (min(starts), fs)
    return sorted(best[1], key=lambda f: f["start"]) if best else []


def fetch_athlete(aid: str) -> dict:
    try:
        a = get_json(ATHLETE.format(id=aid)).get("athlete") or {}
    except Exception:
        return {}
    reach = a.get("reach")
    if reach is None and a.get("displayReach"):
        try:
            reach = float(str(a["displayReach"]).replace('"', "").strip())
        except ValueError:
            reach = None
    return {
        "age": a.get("age"),
        "height": a.get("displayHeight"),
        "reach_in": reach,
        "stance": (a.get("stance") or {}).get("text"),
        "weight_class": (a.get("weightClass") or {}).get("text"),
        "headshot": (a.get("headshot") or {}).get("href"),
    }
