"""Same-Game Parlay (SGP) Correlation Under-Adjustment Detector.

Empirical research in FINDINGS.md established that same-player receptions-over and
yards-over exhibit strong positive correlation: phi ~ 0.65 and ~1.34x - 1.50x
joint probability lift over independent assumptions.

Sportsbooks apply correlation haircuts to SGP pricing, but their automated
pricing engines frequently under-adjust on specific volume profiles, offering
positive EV opportunities on correlated Over/Over or Under/Under combinations.

This detector scans paired player lines on the active slate, simulates the exact
joint Negative-Binomial / Gamma process, and flags candidate SGPs where the book's
haircut is insufficient.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from src.model import ReceivingModel, american_to_decimal, american_to_prob
    from src.parlay import Leg, ParlayPricer
except ImportError:
    from model import ReceivingModel, american_to_decimal, american_to_prob
    from parlay import Leg, ParlayPricer

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOTS = ROOT / "viewer" / "snapshots_2026_w7.json"
DEFAULT_FEED = ROOT / "viewer" / "live_odds_feed.json"
DEFAULT_OUTPUT = ROOT / "viewer" / "sgp_candidates.json"


@dataclass(frozen=True)
class SGPCandidate:
    player_id: str
    player_name: str
    team: str
    opponent: str
    pairing: str  # "OVER_OVER" | "UNDER_UNDER"
    rec_line: float
    yd_line: float
    rec_odds: int
    yd_odds: int
    phi_correlation: float
    p_model_joint: float
    p_independent: float
    correlation_lift: float
    benchmark_sgp_odds: str
    expected_value_pct: float
    edge_detected: bool
    status: str
    reason: str


class SGPDetector:
    def __init__(
        self,
        alpha: float = 0.1097,
        k: float = 1.555,
        n_sims: int = 50_000,
        seed: int = 42,
        min_ev_hurdle: float = 0.05,
    ):
        self.model = ReceivingModel(
            rec_params=None,
            ypr_params=None,
            alpha=alpha,
            k=k,
            means=None,
            sds=None,
            cols=None,
        )
        self.pricer = ParlayPricer(self.model, n_sims=n_sims, seed=seed)
        self.min_ev = min_ev_hurdle

    def evaluate_pair(
        self,
        player_name: str,
        player_id: str,
        team: str,
        opponent: str,
        mu_rec: float,
        mu_ypr: float,
        rec_line: float,
        yd_line: float,
        rec_odds: int = -115,
        yd_odds: int = -115,
        offered_sgp_decimal: float | None = None,
    ) -> list[SGPCandidate]:
        candidates: list[SGPCandidate] = []
        phi = self.pricer.leg_correlation(mu_rec, mu_ypr, rec_line, yd_line)

        for side in ["over", "under"]:
            legs = [
                Leg(player_name, "receptions", side, rec_line, rec_odds, mu_rec, mu_ypr),
                Leg(player_name, "receiving_yards", side, yd_line, yd_odds, mu_rec, mu_ypr),
            ]
            res = self.pricer.price(legs)
            p_joint = res["p_model_joint"]
            p_indep = res["p_model_independent"]
            lift = res["correlation_lift"]

            # Standard retail book SGP payout model:
            # Independent decimal = d1 * d2 (e.g. 1.87 * 1.87 = 3.50 -> +250)
            # Standard book correlation discount reduces decimal payout by ~20% for phi ~ 0.65
            indep_dec = float(american_to_decimal(rec_odds) * american_to_decimal(yd_odds))
            book_dec = offered_sgp_decimal if offered_sgp_decimal is not None else (indep_dec * 0.80)

            ev = (p_joint * (book_dec - 1)) - (1 - p_joint)
            is_edge = ev >= self.min_ev

            # Format American odds string for benchmark SGP payout
            if book_dec >= 2.0:
                plus_odds = int(round((book_dec - 1.0) * 100))
                odds_str = f"+{plus_odds}"
            else:
                minus_odds = int(round(-100.0 / (book_dec - 1.0)))
                odds_str = str(minus_odds)

            pair_key = f"{side.upper()}_{side.upper()}"
            status = "QUALIFIED_SGP_EDGE" if is_edge else "CORRELATED_EFFICIENT"
            reason = (
                f"Model joint win rate ({p_joint:.1%}) outpaces book payout hurdle "
                f"({1.0/book_dec:.1%}) by {ev:.1%} EV"
                if is_edge
                else "Book correlation haircut sufficiently prices joint probability"
            )

            candidates.append(
                SGPCandidate(
                    player_id=player_id,
                    player_name=player_name,
                    team=team,
                    opponent=opponent,
                    pairing=pair_key,
                    rec_line=rec_line,
                    yd_line=yd_line,
                    rec_odds=rec_odds,
                    yd_odds=yd_odds,
                    phi_correlation=round(phi, 3),
                    p_model_joint=round(p_joint, 4),
                    p_independent=round(p_indep, 4),
                    correlation_lift=round(lift, 3),
                    benchmark_sgp_odds=odds_str,
                    expected_value_pct=round(ev * 100, 2),
                    edge_detected=is_edge,
                    status=status,
                    reason=reason,
                )
            )

        return candidates

    def scan_slate(self, snapshots_path: Path | str = DEFAULT_SNAPSHOTS) -> list[SGPCandidate]:
        p = Path(snapshots_path)
        if not p.exists():
            return []

        snaps = json.loads(p.read_text(encoding="utf-8"))
        by_player: dict[str, dict[str, Any]] = {}
        for s in snaps:
            pid = s.get("player_id")
            if not pid:
                continue
            by_player.setdefault(pid, {})[s.get("market")] = s

        all_candidates: list[SGPCandidate] = []

        for pid, markets in by_player.items():
            if "receptions" not in markets or "receiving_yards" not in markets:
                continue

            rec_snap = markets["receptions"]
            yd_snap = markets["receiving_yards"]

            proj_rec = rec_snap.get("projection") or {}
            params = proj_rec.get("distribution_params") or {}
            mu_rec = params.get("mu_rec")
            proj_yd = yd_snap.get("projection") or {}
            params_yd = proj_yd.get("distribution_params") or {}
            mu_ypr = params_yd.get("mu_ypr")

            if mu_rec is None or mu_ypr is None:
                continue

            # Check quotes if available, otherwise use fair lines
            q_rec = rec_snap.get("quote") or {}
            q_yd = yd_snap.get("quote") or {}

            rec_line = q_rec.get("line") if q_rec.get("line") is not None else proj_rec.get("fair_line")
            yd_line = q_yd.get("line") if q_yd.get("line") is not None else proj_yd.get("fair_line")

            rec_odds = q_rec.get("over_odds") if q_rec.get("over_odds") is not None else -115
            yd_odds = q_yd.get("over_odds") if q_yd.get("over_odds") is not None else -115

            if rec_line is None or yd_line is None:
                continue

            pair_res = self.evaluate_pair(
                player_name=rec_snap.get("player_name", "Unknown"),
                player_id=pid,
                team=rec_snap.get("team", "UNK"),
                opponent=rec_snap.get("opponent", "UNK"),
                mu_rec=float(mu_rec),
                mu_ypr=float(mu_ypr),
                rec_line=float(rec_line),
                yd_line=float(yd_line),
                rec_odds=int(rec_odds),
                yd_odds=int(yd_odds),
            )
            all_candidates.extend(pair_res)

        all_candidates.sort(key=lambda c: c.expected_value_pct, reverse=True)
        return all_candidates


def main():
    parser = argparse.ArgumentParser(description="PropStein SGP Under-Adjustment Detector")
    parser.add_argument("--snapshots", type=str, default=str(DEFAULT_SNAPSHOTS), help="Path to snapshots JSON")
    parser.add_argument("--min-ev", type=float, default=5.0, help="Minimum EV percentage hurdle (e.g. 5.0 for 5%%)")
    parser.add_argument("--export", type=str, default=str(DEFAULT_OUTPUT), help="Output path for candidates JSON")
    args = parser.parse_args()

    detector = SGPDetector(min_ev_hurdle=args.min_ev / 100.0)
    candidates = detector.scan_slate(args.snapshots)
    edges = [c for c in candidates if c.edge_detected]

    print(f"Scanned {len(candidates)//2} paired receiver slates:")
    print(f"Found {len(edges)} SGP combinations clearing the {args.min_ev:.1f}% EV hurdle:\n")

    for idx, e in enumerate(edges[:10], 1):
        print(
            f"{idx}. {e.player_name} ({e.team} vs {e.opponent}) — {e.pairing}\n"
            f"   Rec: {e.rec_line} | Yds: {e.yd_line} | Benchmark Odds: {e.benchmark_sgp_odds}\n"
            f"   Correlation Phi: {e.phi_correlation:.2f} | Joint Prob: {e.p_model_joint:.1%} (Lift: {e.correlation_lift:.2f}x)\n"
            f"   Expected Value: +{e.expected_value_pct:.1f}%\n"
        )

    out_p = Path(args.export)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(
        json.dumps(
            {
                "total_pairs_scanned": len(candidates) // 2,
                "qualified_edges_count": len(edges),
                "min_ev_hurdle_pct": args.min_ev,
                "candidates": [asdict(c) for c in candidates],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Exported SGP analysis to {out_p}")


if __name__ == "__main__":
    main()
