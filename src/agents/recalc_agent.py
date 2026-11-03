"""
Agent 3: ProjectionRecalcAgent (The Money Path)

ARCHITECTURAL LAW:
- The pricing function remains strictly deterministic:
  `price_prop(player_state, market_state, game_state) -> { distribution, fair_prob, edge }`
- Calls the exact Negative Binomial + Compound Gamma formulation from `src/model.py`
  for NFL receiving props, and calibrated distributional parameterization for NBA.
- For live games, computes the REMAINING-GAME distribution conditioned on
  `minutes_remaining`, `usage_rate`, and `remaining_opportunities` + accumulated stats.
- Strictly idempotent: replaying the same event produces the exact same `PropProjection`.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from src.agents.persistence import TOPIC_PROJECTION, DurableRedisStreamBus, TruthStore
from src.agents.schemas import (
    MODEL_VERSION,
    InjuryEventPayload,
    LineupEventPayload,
    PropProjection,
    StructuredAgentLog,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch
from src.model import american_to_decimal, devig_two_way, ev_per_unit, kelly_fraction

logger = logging.getLogger("propwire.agent.recalc")

BASE_DIR = Path(__file__).resolve().parents[2]
VIEWER_DIR = BASE_DIR / "viewer"

# Calibrated dispersion constants from src/model.py
DEFAULT_NB_ALPHA = 0.185
DEFAULT_GAMMA_K = 2.15


def _compound_yards_prob_over(mu_rec: float, mu_ypr: float, line: float, alpha: float = DEFAULT_NB_ALPHA, k: float = DEFAULT_GAMMA_K) -> float:
    """Exact tail of the compound NB-Gamma distribution from `src/model.py`."""
    if line <= 0:
        return 0.99
    if mu_rec <= 1e-6 or mu_ypr <= 1e-6:
        return 0.01
    r = 1.0 / max(alpha, 1e-4)
    p = r / (r + mu_rec)
    rv = stats.nbinom(r, p)
    n_max = int(max(24, rv.ppf(0.9999) + 4))
    ns = np.arange(1, n_max + 1)
    pn = rv.pmf(ns)
    scale = mu_ypr / k
    sf = stats.gamma.sf(line, a=ns * k, scale=scale)
    return float(np.clip(np.dot(pn, sf), 0.001, 0.999))


def _compound_yards_quantile(mu_rec: float, mu_ypr: float, q: float, alpha: float = DEFAULT_NB_ALPHA, k: float = DEFAULT_GAMMA_K) -> float:
    lo, hi = 0.0, 350.0
    for _ in range(42):
        mid = (lo + hi) / 2.0
        if _compound_yards_prob_over(mu_rec, mu_ypr, mid, alpha=alpha, k=k) > (1.0 - q):
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 1)


def _nb_count_prob_over(mu: float, line: float, alpha: float = 0.14) -> float:
    """Discrete Negative Binomial survival function for count props (receptions, rebounds, assists, 3PM)."""
    if line <= 0:
        return 0.99
    if mu <= 1e-6:
        return 0.01
    r = 1.0 / max(alpha, 1e-4)
    p = r / (r + mu)
    return float(np.clip(stats.nbinom.sf(math.floor(line), r, p), 0.001, 0.999))


def bayesian_remaining_game_update(
    *,
    prior_rate_per_min: float,
    observed_stat: float,
    elapsed_minutes: float,
    minutes_remaining: float,
    usage_multiplier: float = 1.0,
    personal_fouls: int = 0,
    period: int = 1,
    prior_strength_minutes: float = 24.0,
) -> dict[str, float]:
    """
    Live Conjugate Gamma-Poisson / Gamma-Normal Bayesian Posterior Update:
    Combines pre-game prior rate (`prior_rate_per_min` weighted by `prior_strength_minutes`)
    with observed in-game production (`observed_stat` over `elapsed_minutes`), adjusted for
    active `usage_multiplier` (from `lineup.substitution` / usage vacuum) and `foul_trouble`
    expected-minutes penalty.
    """
    eff_elapsed = max(0.0, float(elapsed_minutes))
    obs_stat = max(0.0, float(observed_stat))
    prior_pseudo_count = max(0.1, prior_rate_per_min * prior_strength_minutes)
    posterior_rate_per_min = (prior_pseudo_count + obs_stat) / (prior_strength_minutes + eff_elapsed)

    # Apply foul-trouble expected-minutes discount
    foul_penalty_min = 0.0
    if (period == 1 and personal_fouls >= 2) or (period == 2 and personal_fouls >= 3) or (period == 3 and personal_fouls >= 4) or (period >= 4 and personal_fouls >= 5):
        foul_penalty_min = min(float(minutes_remaining) * 0.30, 4.5)

    adj_minutes_remaining = max(0.5, float(minutes_remaining) - foul_penalty_min)
    posterior_remaining_mu = max(0.2, posterior_rate_per_min * adj_minutes_remaining * usage_multiplier)
    return {
        "posterior_rate_per_min": round(posterior_rate_per_min, 4),
        "adj_minutes_remaining": round(adj_minutes_remaining, 2),
        "posterior_remaining_mu": round(posterior_remaining_mu, 3),
        "foul_penalty_minutes": round(foul_penalty_min, 2),
    }


def price_prop(
    player_state: dict[str, Any],
    market_state: dict[str, Any],
    game_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Deterministic Core Pricing Function:
    `price_prop(player_state, market_state, game_state) -> { distribution, fair_prob, edge }`

    Never invokes an LLM. Pure mathematical distributional calculation.
    """
    game_state = game_state or {}
    sport = str(player_state.get("sport", "nfl")).lower()
    market = str(market_state.get("market", "receiving_yards" if sport == "nfl" else "points")).lower()
    line = float(market_state.get("line", player_state.get("line", 50.5)))

    # Remaining-game scaling for live in-game states
    is_live = bool(game_state.get("is_live", False))
    full_minutes = 60.0 if sport == "nfl" else 34.0
    base_minutes = float(player_state.get("base_minutes", player_state.get("baseline_minutes", full_minutes)))
    minutes_projection = float(player_state.get("minutes_projection", base_minutes))
    minutes_remaining = float(game_state.get("minutes_remaining", minutes_projection))
    live_accumulated = float(game_state.get("live_stat_accumulated", 0.0))

    base_usage = float(player_state.get("base_usage_rate", player_state.get("baseline_usage", 0.22)))
    usage_rate = float(player_state.get("usage_rate", base_usage))
    usage_multiplier = max(0.25, min(2.2, usage_rate / max(base_usage, 1e-4)))

    minutes_multiplier = max(0.05, min(1.8, (minutes_remaining if is_live else minutes_projection) / max(base_minutes, 1.0)))
    combined_scale = minutes_multiplier * usage_multiplier

    remaining_needed = max(0.0, line - live_accumulated)

    if sport == "nfl":
        base_mu_rec = float(player_state.get("base_mu_rec", player_state.get("mu_rec", 4.6)))
        base_mu_ypr = float(player_state.get("base_mu_ypr", player_state.get("mu_ypr", 11.8)))
        alpha = float(player_state.get("alpha", DEFAULT_NB_ALPHA))
        k = float(player_state.get("k", DEFAULT_GAMMA_K))

        adj_mu_rec = round(base_mu_rec * combined_scale, 4)
        adj_mu_ypr = round(base_mu_ypr * (1.0 + 0.15 * (usage_multiplier - 1.0)), 4)

        if market in ("receptions", "player_receptions"):
            fair_prob_over = _nb_count_prob_over(adj_mu_rec, remaining_needed, alpha=alpha)
            r = 1.0 / max(alpha, 1e-4)
            p = r / (r + adj_mu_rec)
            rv = stats.nbinom(r, p)
            fair_line = round(live_accumulated + float(rv.ppf(0.5)), 1)
            ci_low = round(live_accumulated + float(rv.ppf(0.10)), 1)
            ci_high = round(live_accumulated + float(rv.ppf(0.90)), 1)
            mu = round(live_accumulated + adj_mu_rec, 2)
            sd = round(math.sqrt(adj_mu_rec + alpha * (adj_mu_rec ** 2)), 2)
        else:
            fair_prob_over = _compound_yards_prob_over(adj_mu_rec, adj_mu_ypr, remaining_needed, alpha=alpha, k=k)
            rem_median = _compound_yards_quantile(adj_mu_rec, adj_mu_ypr, 0.50, alpha=alpha, k=k)
            fair_line = round(live_accumulated + rem_median, 1)
            ci_low = round(live_accumulated + _compound_yards_quantile(adj_mu_rec, adj_mu_ypr, 0.10, alpha=alpha, k=k), 1)
            ci_high = round(live_accumulated + _compound_yards_quantile(adj_mu_rec, adj_mu_ypr, 0.90, alpha=alpha, k=k), 1)
            mu = round(live_accumulated + adj_mu_rec * adj_mu_ypr, 2)
            var_y = adj_mu_rec * (adj_mu_ypr ** 2) * (1.0 / k + 1.0 + alpha * adj_mu_rec)
            sd = round(math.sqrt(max(var_y, 1.0)), 2)
        rem_opps = round(adj_mu_rec * 1.48, 1)
    else:
        # NBA Distributional Engine
        default_base_mu = (
            float(player_state["rate_per_min"]) * base_minutes
            if "rate_per_min" in player_state
            else 22.5
        )
        base_mu = float(player_state.get("base_mu", default_base_mu))
        base_sd = float(player_state.get("base_sd", max(1.5, 0.24 * base_mu)))
        adj_mu_rem = max(0.2, base_mu * combined_scale)
        adj_sd_rem = max(1.0, base_sd * math.sqrt(max(0.1, minutes_multiplier)) * (0.85 + 0.15 * usage_multiplier))

        if market in ("threes", "rebounds", "assists"):
            alpha_nba = 0.12 if market != "threes" else 0.22
            fair_prob_over = _nb_count_prob_over(adj_mu_rem, remaining_needed, alpha=alpha_nba)
            r = 1.0 / alpha_nba
            p = r / (r + adj_mu_rem)
            rv = stats.nbinom(r, p)
            fair_line = round(live_accumulated + float(rv.ppf(0.5)), 1)
            ci_low = round(live_accumulated + float(rv.ppf(0.10)), 1)
            ci_high = round(live_accumulated + float(rv.ppf(0.90)), 1)
        else:
            # Points / PRA continuous Gamma-Normal hybrid tail (strictly non-negative)
            shape_g = max(1.5, (adj_mu_rem / adj_sd_rem) ** 2)
            scale_g = (adj_sd_rem ** 2) / max(adj_mu_rem, 0.1)
            fair_prob_over = float(np.clip(stats.gamma.sf(remaining_needed, a=shape_g, scale=scale_g), 0.001, 0.999))
            fair_line = round(live_accumulated + float(stats.gamma.ppf(0.50, a=shape_g, scale=scale_g)), 1)
            ci_low = round(live_accumulated + float(stats.gamma.ppf(0.10, a=shape_g, scale=scale_g)), 1)
            ci_high = round(live_accumulated + float(stats.gamma.ppf(0.90, a=shape_g, scale=scale_g)), 1)

        mu = round(live_accumulated + adj_mu_rem, 2)
        sd = round(adj_sd_rem, 2)
        adj_mu_rec = None
        adj_mu_ypr = None
        alpha = None
        k = None
        rem_opps = round(minutes_remaining * usage_rate * 2.1, 1)

    fair_prob_under = round(1.0 - fair_prob_over, 4)
    fair_prob_over = round(fair_prob_over, 4)

    # Market state comparison (de-vigged consensus or direct implied probability)
    over_odds = int(market_state.get("over_odds", -110))
    under_odds = int(market_state.get("under_odds", -110))
    if "implied_prob_over" in market_state and market_state["implied_prob_over"] is not None:
        mkt_p_over = float(market_state["implied_prob_over"])
        mkt_p_under = float(market_state.get("implied_prob_under", 1.0 - mkt_p_over))
    else:
        mkt_p_over, mkt_p_under = devig_two_way(over_odds, under_odds)

    edge_over = round(fair_prob_over - mkt_p_over, 4)
    edge_under = round(fair_prob_under - mkt_p_under, 4)

    if edge_over >= edge_under:
        best_side = "OVER"
        fair_prob = fair_prob_over
        implied_prob = round(mkt_p_over, 4)
        edge = edge_over
        active_odds = over_odds
    else:
        best_side = "UNDER"
        fair_prob = fair_prob_under
        implied_prob = round(mkt_p_under, 4)
        edge = edge_under
        active_odds = under_odds

    ev = round(ev_per_unit(fair_prob, active_odds), 4)
    kelly = round(kelly_fraction(fair_prob, active_odds, cap=float(market_state.get("kelly_cap", 0.015))), 5)

    # Narrower relative CI interval -> higher model confidence score [0.50, 0.96]
    rel_spread = (ci_high - ci_low) / max(mu, 5.0)
    confidence_score = round(float(np.clip(0.92 - 0.18 * rel_spread, 0.52, 0.96)), 3)

    return {
        "distribution": {
            "mu": mu,
            "sd": sd,
            "fair_line": fair_line,
            "ci_80_low": ci_low,
            "ci_80_high": ci_high,
            "alpha": alpha,
            "k": k,
            "mu_rec": adj_mu_rec,
            "mu_ypr": adj_mu_ypr,
            "minutes_projection": round(minutes_projection, 1),
            "minutes_remaining": round(minutes_remaining if is_live else minutes_projection, 1),
            "usage_rate": round(usage_rate, 4),
            "remaining_opportunities": rem_opps,
            "confidence_score": confidence_score,
        },
        "fair_prob": fair_prob,
        "fair_prob_over": fair_prob_over,
        "fair_prob_under": fair_prob_under,
        "implied_prob": implied_prob,
        "best_side": best_side,
        "edge": edge,
        "edge_pct": round(edge * 100.0, 2),
        "mispricing_bps": round(edge * 10000.0, 1),
        "ev_per_unit": ev,
        "kelly_stake": kelly,
        "active_odds": active_odds,
    }


class ProjectionRecalcAgent:
    """
    Triggered by `injury.*`, `lineup.*`, or `game_clock.*` events.
    Recomputes deterministic player prop distributions and persists
    idempotent `PropProjection` records to Postgres/TruthStore and
    `propwire.events.projection`.
    """

    AGENT_NAME = "ProjectionRecalcAgent"

    def __init__(
        self,
        stream_bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
        bus: DurableRedisStreamBus | None = None,
    ):
        self.stream_bus = stream_bus or bus or DurableRedisStreamBus()
        self.truth_store = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self.baseline_catalog: dict[str, dict[str, Any]] = {}
        self._load_baseline_catalog()

    def _load_baseline_catalog(self) -> None:
        """Load baseline player parameters from committed NFL and NBA slates."""
        nfl_path = VIEWER_DIR / "slate_2026_w7.json"
        if nfl_path.exists():
            try:
                rows = json.loads(nfl_path.read_text(encoding="utf-8"))
                for r in rows:
                    pid = str(r.get("player_id") or "")
                    if not pid:
                        continue
                    mu_rec = float(r.get("proj_receptions") or r.get("mu_rec") or 4.2)
                    proj_yds = float(r.get("proj_yards") or r.get("proj_receiving_yards") or 52.0)
                    mu_ypr = proj_yds / max(mu_rec, 0.5)
                    self.baseline_catalog[pid] = {
                        "sport": "nfl",
                        "player_id": pid,
                        "player_name": r.get("player_display_name", pid),
                        "team": r.get("team", "UNK"),
                        "opponent": r.get("opponent_team", "UNK"),
                        "position": r.get("position", "WR"),
                        "game_id": r.get("game_id", "2026_07_NFL"),
                        "market": "receiving_yards",
                        "line": float(r.get("fair_yards") or round(proj_yds - 2.5, 1)),
                        "base_mu_rec": mu_rec,
                        "base_mu_ypr": mu_ypr,
                        "base_minutes": 60.0,
                        "base_usage_rate": float(r.get("target_share") or 0.22),
                    }
            except Exception:
                pass

        for nba_file in ("nba_slate_2026-10-29.json", "nba_slate_2026-10-23.json", "nba_slate_2026-10-22.json"):
            p = VIEWER_DIR / nba_file
            if p.exists():
                try:
                    rows = json.loads(p.read_text(encoding="utf-8"))
                    for r in rows:
                        pid = str(r.get("player_id") or "")
                        if not pid or pid in self.baseline_catalog:
                            continue
                        mu_pts = float(r.get("proj_points") or r.get("fair_points") or 21.5)
                        sd_pts = float(r.get("sd_points") or max(2.5, 0.28 * mu_pts))
                        mins = float(r.get("proj_minutes") or 33.0)
                        self.baseline_catalog[pid] = {
                            "sport": "nba",
                            "player_id": pid,
                            "player_name": r.get("player_display_name", pid),
                            "team": r.get("team", "UNK"),
                            "opponent": r.get("opponent_team", "UNK"),
                            "position": r.get("position", "PG"),
                            "game_id": r.get("game_id", "nba-20261029"),
                            "market": "points",
                            "line": float(r.get("fair_points") or round(mu_pts - 0.5, 1)),
                            "base_mu": mu_pts,
                            "base_sd": sd_pts,
                            "base_minutes": mins,
                            "base_usage_rate": float(r.get("usage_rate") or 0.25),
                        }
                except Exception:
                    pass

    def get_or_create_baseline(self, player_id: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        if player_id in self.baseline_catalog:
            return dict(self.baseline_catalog[player_id])
        fb = fallback or {}
        sport = str(fb.get("sport", "nba")).lower()
        return {
            "sport": sport,
            "player_id": player_id,
            "player_name": fb.get("player_name", player_id),
            "team": fb.get("team", "UNK"),
            "opponent": fb.get("opponent", "UNK"),
            "position": fb.get("position", "G" if sport == "nba" else "WR"),
            "game_id": fb.get("game_id", "live_game"),
            "market": fb.get("market", "points" if sport == "nba" else "receiving_yards"),
            "line": float(fb.get("line", 22.5 if sport == "nba" else 54.5)),
            "base_mu": float(fb.get("base_mu", 23.0)),
            "base_sd": float(fb.get("base_sd", 6.2)),
            "base_mu_rec": float(fb.get("base_mu_rec", 4.8)),
            "base_mu_ypr": float(fb.get("base_mu_ypr", 12.1)),
            "base_minutes": float(fb.get("base_minutes", 34.0 if sport == "nba" else 60.0)),
            "base_usage_rate": float(fb.get("base_usage_rate", 0.24)),
        }

    def recalculate_from_event(
        self,
        event_type: str,
        event_payload: dict[str, Any],
        *,
        source_hash: str | None = None,
        fetched_at: datetime | None = None,
        now: datetime | None = None,
    ) -> list[PropProjection]:
        """
        Idempotently recompute projections for all affected players from an
        `injury.*`, `lineup.*`, or `game_clock.*` event.
        """
        t0 = time.perf_counter()
        shash = source_hash or event_payload.get("source_hash") or compute_source_hash(event_payload)
        if fetched_at is None:
            raw_ft = event_payload.get("fetched_at")
            if isinstance(raw_ft, str):
                fetched_at = datetime.fromisoformat(raw_ft.replace("Z", "+00:00"))
            elif isinstance(raw_ft, datetime):
                fetched_at = raw_ft
            else:
                fetched_at = datetime.now(timezone.utc)

        is_live = bool(event_payload.get("is_live", False))
        feed_type = "injury" if "injury" in event_type else "lineup"
        is_stale, age_s, _, stale_reason = self.kill_switch.evaluate(
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            prop_id=str(event_payload.get("game_id", "game")),
            feed_type=feed_type,  # type: ignore[arg-type]
            fetched_at=fetched_at,
            source_hash=shash,
            is_live=is_live,
            now=now,
        )

        computed_ts = now or datetime.now(timezone.utc)
        outputs: list[PropProjection] = []

        # 1. Process primary player in event
        primary_pid = str(event_payload.get("player_id", ""))
        status = str(event_payload.get("status", "")).upper()
        sub_type = str(event_payload.get("sub_type", "")).lower()

        if primary_pid and status not in ("OUT", "SCRATCHED"):
            base = self.get_or_create_baseline(primary_pid, event_payload)
            market = str(event_payload.get("market") or base["market"])
            line = float(event_payload.get("line") or base["line"])

            mins_delta = float(event_payload.get("minutes_projection_delta", 0.0))
            if status == "QUESTIONABLE":
                mins_delta = -0.25 * base["base_minutes"]
            elif status == "DOUBTFUL":
                mins_delta = -0.65 * base["base_minutes"]

            new_minutes = max(4.0, base["base_minutes"] + mins_delta)
            new_usage = max(0.08, base["base_usage_rate"] + float(event_payload.get("usage_rate_delta", 0.0)))

            catalyst: Any = "baseline"
            detail = ""
            if sub_type == "foul_trouble":
                catalyst = "foul_trouble"
                detail = f"Foul trouble ({event_payload.get('personal_fouls', 3)} PF in P{event_payload.get('period', 2)}): {mins_delta:+.1f} min"
            elif sub_type in ("substitution", "confirmed_starter"):
                catalyst = "substitution" if sub_type == "substitution" else "usage_surge"
                detail = f"Lineup {sub_type}: {mins_delta:+.1f} min"
            elif "clock" in event_type:
                catalyst = "live_pace"
                detail = "Live possession clock update"

            player_state = {
                **base,
                "minutes_projection": new_minutes,
                "usage_rate": new_usage,
            }
            game_state = {
                "is_live": is_live,
                "minutes_remaining": float(event_payload.get("clock_remaining_minutes", new_minutes)),
                "live_stat_accumulated": float(event_payload.get("live_stat_accumulated", 0.0)),
            }
            priced = price_prop(player_state, {"market": market, "line": line}, game_state)
            dist = priced["distribution"]
            prop_id = f"{base['game_id']}::{primary_pid}::{market}"

            proj = PropProjection(
                prop_id=prop_id,
                sport=base["sport"],
                game_id=base["game_id"],
                player_id=primary_pid,
                player_name=base["player_name"],
                team=base["team"],
                opponent=base["opponent"],
                position=base["position"],
                market=market,
                line=line,
                mu=dist["mu"],
                sd=dist["sd"],
                alpha=dist["alpha"],
                k=dist["k"],
                mu_rec=dist["mu_rec"],
                mu_ypr=dist["mu_ypr"],
                fair_line=dist["fair_line"],
                fair_prob_over=priced["fair_prob_over"],
                fair_prob_under=priced["fair_prob_under"],
                ci_80_low=dist["ci_80_low"],
                ci_80_high=dist["ci_80_high"],
                confidence_score=dist["confidence_score"],
                minutes_projection=dist["minutes_projection"],
                minutes_remaining=dist["minutes_remaining"],
                usage_rate=dist["usage_rate"],
                remaining_opportunities=dist["remaining_opportunities"],
                catalyst_reason=catalyst,
                catalyst_detail=detail,
                model_version=MODEL_VERSION,
                source_hash=shash,
                fetched_at=fetched_at,
                computed_at=computed_ts,
                feed_age_seconds=age_s,
                is_stale=is_stale,
            )
            self.truth_store.upsert_projection(proj)
            self.stream_bus.xadd(TOPIC_PROJECTION, proj.model_dump(mode="json"), source_hash=shash)
            outputs.append(proj)

        # 2. Process all teammates / beneficiaries absorbing vacated usage & minutes
        beneficiaries = event_payload.get("beneficiaries") or event_payload.get("impacted_beneficiaries") or []
        catalyst_player = event_payload.get("player_name", primary_pid)
        for b in beneficiaries:
            b_dict = b if isinstance(b, dict) else b.model_dump()
            b_pid = str(b_dict.get("player_id", ""))
            if not b_pid:
                continue
            base = self.get_or_create_baseline(
                b_pid,
                {
                    "sport": event_payload.get("sport", "nba"),
                    "player_name": b_dict.get("player_name", b_pid),
                    "team": b_dict.get("team", event_payload.get("team", "UNK")),
                    "opponent": event_payload.get("opponent", "UNK"),
                    "position": b_dict.get("position", "G"),
                    "game_id": event_payload.get("game_id", "live_game"),
                },
            )
            market = str(b_dict.get("market") or event_payload.get("market") or base["market"])
            line = float(b_dict.get("line") or base["line"])

            added_mins = float(b_dict.get("added_minutes", 0.0))
            added_targets = float(b_dict.get("added_targets", 0.0))
            added_usage = float(b_dict.get("added_usage_rate", 0.0))
            if added_usage == 0.0 and (added_mins > 0 or added_targets > 0):
                added_usage = 0.035 if added_mins >= 4.0 else 0.025

            new_minutes = min(42.0 if base["sport"] == "nba" else 60.0, base["base_minutes"] + added_mins)
            new_usage = min(0.42, base["base_usage_rate"] + added_usage)

            # For NFL target absorption, boost base_mu_rec directly by added_targets * catch_rate
            adj_base = dict(base)
            if base["sport"] == "nfl" and added_targets > 0:
                adj_base["base_mu_rec"] = base["base_mu_rec"] + (added_targets * 0.66)

            player_state = {
                **adj_base,
                "minutes_projection": new_minutes,
                "usage_rate": new_usage,
            }
            game_state = {
                "is_live": is_live,
                "minutes_remaining": float(event_payload.get("clock_remaining_minutes", new_minutes)),
                "live_stat_accumulated": float(b_dict.get("live_stat_accumulated", 0.0)),
            }
            priced = price_prop(player_state, {"market": market, "line": line}, game_state)
            dist = priced["distribution"]
            prop_id = f"{base['game_id']}::{b_pid}::{market}"

            catalyst_label = "injury_vacancy" if status in ("OUT", "SCRATCHED", "DOUBTFUL") else "usage_surge"
            detail = (
                f"{catalyst_player} {status or sub_type}: "
                f"+{added_mins:.1f} min, +{added_usage * 100:.1f}% usage"
                if base["sport"] == "nba"
                else f"{catalyst_player} {status}: +{added_targets:.1f} proj targets"
            )

            proj = PropProjection(
                prop_id=prop_id,
                sport=base["sport"],
                game_id=base["game_id"],
                player_id=b_pid,
                player_name=base["player_name"],
                team=base["team"],
                opponent=base["opponent"],
                position=base["position"],
                market=market,
                line=line,
                mu=dist["mu"],
                sd=dist["sd"],
                alpha=dist["alpha"],
                k=dist["k"],
                mu_rec=dist["mu_rec"],
                mu_ypr=dist["mu_ypr"],
                fair_line=dist["fair_line"],
                fair_prob_over=priced["fair_prob_over"],
                fair_prob_under=priced["fair_prob_under"],
                ci_80_low=dist["ci_80_low"],
                ci_80_high=dist["ci_80_high"],
                confidence_score=dist["confidence_score"],
                minutes_projection=dist["minutes_projection"],
                minutes_remaining=dist["minutes_remaining"],
                usage_rate=dist["usage_rate"],
                remaining_opportunities=dist["remaining_opportunities"],
                catalyst_reason=catalyst_label,  # type: ignore[arg-type]
                catalyst_detail=detail,
                model_version=MODEL_VERSION,
                source_hash=shash,
                fetched_at=fetched_at,
                computed_at=computed_ts,
                feed_age_seconds=age_s,
                is_stale=is_stale,
            )
            self.truth_store.upsert_projection(proj)
            self.stream_bus.xadd(TOPIC_PROJECTION, proj.model_dump(mode="json"), source_hash=shash)
            outputs.append(proj)

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        for p in outputs:
            logger.info(
                StructuredAgentLog(
                    agent=self.AGENT_NAME,
                    event_type=event_type,
                    prop_id=p.prop_id,
                    latency_ms=latency_ms,
                    decision="HALTED_STALE" if is_stale else "RECALCULATED",
                    reason=f"{p.catalyst_reason}: fair={p.fair_line} P(over)={p.fair_prob_over:.3f} ({stale_reason})",
                    source_hash=shash,
                    feed_age_seconds=age_s,
                    is_stale=is_stale,
                ).model_dump_json()
            )

        return outputs

    def recalculate_from_injury(
        self,
        *,
        injury_event: InjuryEventPayload,
        player_state: dict[str, Any],
        market_state: dict[str, Any],
        game_state: dict[str, Any],
        now: datetime | None = None,
    ) -> PropProjection:
        """
        Deterministically recompute a single player's `PropProjection` given
        an `InjuryEventPayload` and explicit `player_state`/`market_state`/`game_state`.
        Strictly idempotent on replay.
        """
        now_dt = now or datetime.now(timezone.utc)
        is_stale, age_s, _ = self.kill_switch.check_freshness(
            fetched_at=injury_event.fetched_at,
            feed_type="injury",
            is_live=injury_event.is_live,
            now=now_dt,
        )

        pid = str(player_state["player_id"])
        sport = str(player_state.get("sport", injury_event.sport))
        base_mins = float(player_state.get("baseline_minutes", player_state.get("base_minutes", 35.0)))
        base_usage = float(player_state.get("baseline_usage", player_state.get("base_usage_rate", 0.25)))

        added_mins = 0.0
        added_usage = 0.0
        added_targets = 0.0
        for ben in injury_event.beneficiaries:
            if ben.player_id == pid:
                added_mins += ben.added_minutes
                added_usage += ben.added_usage_rate
                added_targets += ben.added_targets

        adj_player = dict(player_state)
        adj_player["minutes_projection"] = min(44.0 if sport == "nba" else 60.0, base_mins + added_mins)
        adj_player["usage_rate"] = min(0.45, base_usage + added_usage)
        if sport == "nfl" and added_targets > 0:
            base_rec = float(player_state.get("mu_rec", player_state.get("base_mu_rec", 5.0)))
            catch_rate = float(player_state.get("catch_rate", 0.70))
            adj_player["base_mu_rec"] = base_rec + added_targets * catch_rate

        priced = price_prop(adj_player, market_state, game_state)
        dist = priced["distribution"]
        prop_id = str(market_state.get("prop_id") or f"{injury_event.game_id}::{pid}::{market_state['market']}")

        proj = PropProjection(
            prop_id=prop_id,
            sport=sport,  # type: ignore[arg-type]
            game_id=str(game_state.get("game_id", injury_event.game_id)),
            player_id=pid,
            player_name=str(player_state.get("player_name", pid)),
            team=str(player_state.get("team", injury_event.team)),
            opponent=str(player_state.get("opponent", injury_event.opponent)),
            position=str(player_state.get("position", "PG" if sport == "nba" else "WR")),
            market=str(market_state["market"]),
            line=float(market_state["line"]),
            mu=dist["mu"],
            sd=dist["sd"],
            alpha=dist["alpha"],
            k=dist["k"],
            mu_rec=dist["mu_rec"],
            mu_ypr=dist["mu_ypr"],
            fair_line=dist["fair_line"],
            fair_prob_over=priced["fair_prob_over"],
            fair_prob_under=priced["fair_prob_under"],
            ci_80_low=dist["ci_80_low"],
            ci_80_high=dist["ci_80_high"],
            confidence_score=float(player_state.get("confidence_score", dist["confidence_score"])),
            minutes_projection=dist["minutes_projection"],
            minutes_remaining=dist["minutes_remaining"],
            usage_rate=dist["usage_rate"],
            remaining_opportunities=dist["remaining_opportunities"],
            catalyst_reason="injury_vacancy",
            catalyst_detail=injury_event.notes or f"{injury_event.player_name} {injury_event.status}",
            model_version=MODEL_VERSION,
            source_hash=injury_event.source_hash,
            fetched_at=injury_event.fetched_at,
            computed_at=now_dt,
            feed_age_seconds=age_s,
            is_stale=is_stale,
        )
        self.truth_store.upsert_projection(proj)
        self.stream_bus.xadd(TOPIC_PROJECTION, proj.model_dump(mode="json"), source_hash=proj.source_hash)
        return proj

    def recalculate_from_lineup(
        self,
        *,
        lineup_event: LineupEventPayload,
        player_state: dict[str, Any],
        market_state: dict[str, Any],
        game_state: dict[str, Any],
        now: datetime | None = None,
    ) -> PropProjection:
        """
        Deterministically recompute a single player's `PropProjection` given
        a `LineupEventPayload` and explicit `player_state`/`market_state`/`game_state`.
        """
        now_dt = now or datetime.now(timezone.utc)
        is_stale, age_s, _ = self.kill_switch.check_freshness(
            fetched_at=lineup_event.fetched_at,
            feed_type="lineup",
            is_live=lineup_event.is_live,
            now=now_dt,
        )

        pid = str(player_state["player_id"])
        sport = str(player_state.get("sport", lineup_event.sport))
        base_mins = float(player_state.get("baseline_minutes", player_state.get("base_minutes", 35.0)))
        base_usage = float(player_state.get("baseline_usage", player_state.get("base_usage_rate", 0.25)))

        added_mins = lineup_event.minutes_projection_delta if lineup_event.player_id == pid else 0.0
        added_usage = lineup_event.usage_rate_delta if lineup_event.player_id == pid else 0.0
        added_opps = lineup_event.remaining_opportunities_delta if lineup_event.player_id == pid else 0.0

        for ben in lineup_event.beneficiaries:
            if ben.player_id == pid:
                added_mins += ben.added_minutes
                added_usage += ben.added_usage_rate
                added_opps += ben.added_targets

        adj_player = dict(player_state)
        adj_player["minutes_projection"] = max(8.0, min(44.0 if sport == "nba" else 60.0, base_mins + added_mins))
        adj_player["usage_rate"] = max(0.08, min(0.45, base_usage + added_usage))
        if sport == "nfl" and added_opps != 0.0:
            base_rec = float(player_state.get("mu_rec", player_state.get("base_mu_rec", 5.0)))
            catch_rate = float(player_state.get("catch_rate", 0.72))
            adj_player["base_mu_rec"] = max(0.5, base_rec + added_opps * catch_rate)

        priced = price_prop(adj_player, market_state, game_state)
        dist = priced["distribution"]
        prop_id = str(market_state.get("prop_id") or f"{lineup_event.game_id}::{pid}::{market_state['market']}")

        catalyst_reason = "usage_surge"
        if lineup_event.sub_type == "foul_trouble":
            catalyst_reason = "foul_trouble"
        elif lineup_event.sub_type == "substitution":
            catalyst_reason = "substitution"

        proj = PropProjection(
            prop_id=prop_id,
            sport=sport,  # type: ignore[arg-type]
            game_id=str(game_state.get("game_id", lineup_event.game_id)),
            player_id=pid,
            player_name=str(player_state.get("player_name", pid)),
            team=str(player_state.get("team", lineup_event.team)),
            opponent=str(player_state.get("opponent", lineup_event.opponent)),
            position=str(player_state.get("position", "PG" if sport == "nba" else "WR")),
            market=str(market_state["market"]),
            line=float(market_state["line"]),
            mu=dist["mu"],
            sd=dist["sd"],
            alpha=dist["alpha"],
            k=dist["k"],
            mu_rec=dist["mu_rec"],
            mu_ypr=dist["mu_ypr"],
            fair_line=dist["fair_line"],
            fair_prob_over=priced["fair_prob_over"],
            fair_prob_under=priced["fair_prob_under"],
            ci_80_low=dist["ci_80_low"],
            ci_80_high=dist["ci_80_high"],
            confidence_score=float(player_state.get("confidence_score", dist["confidence_score"])),
            minutes_projection=dist["minutes_projection"],
            minutes_remaining=dist["minutes_remaining"],
            usage_rate=dist["usage_rate"],
            remaining_opportunities=dist["remaining_opportunities"],
            catalyst_reason=catalyst_reason,  # type: ignore[arg-type]
            catalyst_detail=f"{lineup_event.player_name} {lineup_event.sub_type}",
            model_version=MODEL_VERSION,
            source_hash=lineup_event.source_hash,
            fetched_at=lineup_event.fetched_at,
            computed_at=now_dt,
            feed_age_seconds=age_s,
            is_stale=is_stale,
        )
        self.truth_store.upsert_projection(proj)
        self.stream_bus.xadd(TOPIC_PROJECTION, proj.model_dump(mode="json"), source_hash=proj.source_hash)
        return proj
