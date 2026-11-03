"""UFC fighter ratings (Elo) + finish-hazard round totals.

Elo: 1500 start, K=40 for a fighter's first 5 UFC fights, 28 after; finishes
move ratings 15% more than decisions. Draws/NC/cancellations do not update.

Pre-fight adjustments (Elo points, PRIORS - not fitted, see backtest()):
  reach  : +4 per inch of reach advantage (only when both reaches are known)
  age    : -12 per year a fighter is older than 32
  layoff : -25 if > 400 days since the fighter's last UFC fight
  weight : -20 for the first fight after moving UP a weight class

Rounds totals: P(fight ends before time L) = p_finish * F(L), where p_finish
blends the weight-class finish rate with both fighters' shrunk finish rates
and F is the empirical within-fight finish-time CDF for that scheduled length.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Optional

BASE, K_NEW, K_EST, FINISH_MULT = 1500.0, 40.0, 28.0, 1.15
REACH_PTS, AGE_PTS, AGE_PIVOT = 4.0, 12.0, 32
LAYOFF_DAYS, LAYOFF_PTS, MOVE_UP_PTS = 400, 25.0, 20.0
SHRINK_K = 6.0

WEIGHT_ORDER = ["Strawweight", "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
                "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight"]


def class_rank(wc: Optional[str]) -> Optional[int]:
    if not wc:
        return None
    w = wc.replace("W ", "").replace("Women's ", "").replace("LHW", "Light Heavyweight")
    w = {"Light Heavy": "Light Heavyweight"}.get(w, w)
    return WEIGHT_ORDER.index(w) if w in WEIGHT_ORDER else None


def _ts(s: str) -> float:
    from .espn import _parse_ts
    t = _parse_ts(s)
    return t.timestamp() if t else 0.0


def elo_prob(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Ratings:
    def __init__(self) -> None:
        self.r: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.last: dict[str, float] = {}
        self.cls: dict[str, int] = {}
        self.fin: dict[str, list[int]] = {}  # [finishes involved, fights]
        self.hist: dict[str, list[dict]] = {}
        self.names: dict[str, str] = {}
        self.class_fin: dict[str, list[int]] = {}
        self.finish_times: dict[int, list[float]] = {3: [], 5: []}

    # ---- fitting -------------------------------------------------------
    def fit(self, fights: list[dict], until_ts: Optional[float] = None) -> "Ratings":
        for f in sorted(fights, key=lambda x: _ts(x["start"])):
            t = _ts(f["start"])
            if until_ts is not None and t >= until_ts:
                break
            self.update(f)
        return self

    def update(self, f: dict) -> None:
        if not f.get("completed") or len(f["fighters"]) != 2:
            return
        a, b = f["fighters"]
        t = _ts(f["start"])
        for x in (a, b):
            self.names[x["id"]] = x["name"]
        wc = f.get("weight_class") or "?"
        finished = f.get("went_distance") is False
        cf = self.class_fin.setdefault(wc, [0, 0])
        cf[0] += int(finished)
        cf[1] += 1
        if finished and f.get("end_time_rounds") is not None:
            self.finish_times.setdefault(f["sched_rounds"], []).append(f["end_time_rounds"])
        for x in (a, b):
            fr = self.fin.setdefault(x["id"], [0, 0])
            fr[0] += int(finished)
            fr[1] += 1
        if f.get("result") == "win":
            ra, rb = self.rating(a["id"]), self.rating(b["id"])
            sa = 1.0 if a["winner"] else 0.0
            ea = elo_prob(ra, rb)
            mult = FINISH_MULT if finished else 1.0
            ka = (K_NEW if self.n.get(a["id"], 0) < 5 else K_EST) * mult
            kb = (K_NEW if self.n.get(b["id"], 0) < 5 else K_EST) * mult
            self.r[a["id"]] = ra + ka * (sa - ea)
            self.r[b["id"]] = rb + kb * ((1 - sa) - (1 - ea))
        for x, o in ((a, b), (b, a)):
            self.n[x["id"]] = self.n.get(x["id"], 0) + 1
            self.last[x["id"]] = t
            cr = class_rank(f.get("weight_class"))
            if cr is not None:
                self.cls[x["id"]] = cr
            self.hist.setdefault(x["id"], []).append({
                "date": f["start"][:10], "opponent": o["name"], "event": f.get("event_name"),
                "result": "W" if x["winner"] else ("L" if o["winner"] else "D/NC"),
                "finish": finished, "round": f.get("end_round"),
            })

    def rating(self, fid: str) -> float:
        return self.r.get(fid, BASE)

    # ---- prediction ----------------------------------------------------
    def adjustments(self, fid: str, bio: dict, opp_bio: dict, fight: dict) -> dict:
        adj = {}
        ra, rb = (bio or {}).get("reach_in"), (opp_bio or {}).get("reach_in")
        if ra and rb:
            adj["reach"] = REACH_PTS * (float(ra) - float(rb))
        age = (bio or {}).get("age")
        if age and age > AGE_PIVOT:
            adj["age"] = -AGE_PTS * (age - AGE_PIVOT)
        t = _ts(fight["start"])
        if fid in self.last and t - self.last[fid] > LAYOFF_DAYS * 86400:
            adj["layoff"] = -LAYOFF_PTS
        cr = class_rank(fight.get("weight_class"))
        if cr is not None and fid in self.cls and cr > self.cls[fid]:
            adj["weight_class_up"] = -MOVE_UP_PTS
        return {k: round(v, 1) for k, v in adj.items()}

    def win_prob(self, fight: dict, bios: dict) -> dict:
        a, b = fight["fighters"]
        adj_a = self.adjustments(a["id"], bios.get(a["id"], {}), bios.get(b["id"], {}), fight)
        adj_b = self.adjustments(b["id"], bios.get(b["id"], {}), bios.get(a["id"], {}), fight)
        ea = self.rating(a["id"]) + sum(adj_a.values())
        eb = self.rating(b["id"]) + sum(adj_b.values())
        p = elo_prob(ea, eb)
        return {"p": [round(p, 4), round(1 - p, 4)],
                "elo": [round(self.rating(a["id"]), 1), round(self.rating(b["id"]), 1)],
                "fights": [self.n.get(a["id"], 0), self.n.get(b["id"], 0)],
                "adjustments": [adj_a, adj_b]}

    def p_finish(self, fight: dict) -> float:
        wc = fight.get("weight_class") or "?"
        cf = self.class_fin.get(wc, [0, 0])
        all_f = [sum(v[0] for v in self.class_fin.values()), sum(v[1] for v in self.class_fin.values())]
        g = all_f[0] / all_f[1] if all_f[1] else 0.5
        base = (cf[0] + SHRINK_K * g) / (cf[1] + SHRINK_K)
        rates = []
        for x in fight["fighters"]:
            fr = self.fin.get(x["id"], [0, 0])
            rates.append((fr[0] + SHRINK_K * base) / (fr[1] + SHRINK_K))
        p = 0.5 * base + 0.25 * rates[0] + 0.25 * rates[1]
        if fight.get("sched_rounds") == 5:
            p = min(0.95, p * 1.1)
        return p

    def finish_cdf(self, sched: int, line: float) -> float:
        times = sorted(self.finish_times.get(sched) or self.finish_times.get(3) or [])
        if not times:
            return min(1.0, line / sched)
        return bisect.bisect_right(times, line) / len(times)

    def p_over(self, fight: dict, line: float) -> float:
        return round(1.0 - self.p_finish(fight) * self.finish_cdf(fight.get("sched_rounds") or 3, line), 4)


def backtest(fights: list[dict], warmup: int = 300) -> dict:
    """Walk-forward (results only, no market prices): Brier/log-loss of the
    Elo h2h probability vs a coin flip. NOT a CLV test - edge stays NO EDGE."""
    r = Ratings()
    n = 0
    brier = ll = 0.0
    seen = 0
    for f in sorted(fights, key=lambda x: _ts(x["start"])):
        if f.get("result") == "win" and seen >= warmup:
            a, _ = f["fighters"]
            p = elo_prob(r.rating(a["id"]), r.rating(f["fighters"][1]["id"]))
            y = 1.0 if a["winner"] else 0.0
            brier += (p - y) ** 2
            ll += -math.log(max(1e-9, p if y else 1 - p))
            n += 1
        r.update(f)
        seen += 1
    return {"n": n, "brier": round(brier / n, 4) if n else None,
            "log_loss": round(ll / n, 4) if n else None,
            "coinflip_brier": 0.25, "coinflip_log_loss": round(math.log(2), 4),
            "type": "walk-forward results-only (not closing-line CLV)"}
