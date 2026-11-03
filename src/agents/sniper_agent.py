"""
Agent 6: SniperAgent (The Decision Gate) + Post-Decision Narrator.

ARCHITECTURAL LAW:
- Evaluates the strict 5-gate filter deterministically:
  1. `edge_pct >= effective_edge_gate_pct()` (3.0% normal, 10.0% NFL Week 1)
  2. `confidence_score >= min_confidence_score`
  3. `feed_age_seconds <= threshold` and `not is_stale` (Stale Kill Switch)
  4. `liquidity_score >= min_liquidity_score`
  5. `clv_expectation >= min_clv_expectation`
- Writes passing `SniperAlert` records to `sniper_alerts` and `clv_ledger`.
- Never silently drops: every suppression is logged via `StructuredAgentLog`
  and stored in `TruthStore`.
- The post-decision narrator (`narrate_locked_alert`) runs ONLY after all
  numbers (`fair_prob`, `edge_pct`, `kelly_stake`) are immutable.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.agents.persistence import (
    STREAM_SNIPER,
    DurableRedisStreamBus,
    TruthStore,
)
from src.agents.schemas import (
    MODEL_VERSION,
    MarketMovePayload,
    PropProjection,
    SniperAlert,
    SniperGateConfig,
    StructuredAgentLog,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch
from src.agents.urgency import (
    classify_edge_tier,
    compute_urgency_score,
    should_show_decaying_badge,
)
from src.model import ev_per_unit, kelly_fraction
from src.services.webhook_dispatcher import WebhookDispatcher


def narrate_locked_alert(alert: SniperAlert, projection: PropProjection) -> str:
    """
    Post-decision read-only narrator.
    Generates `reasoning_chain` strictly AFTER `fair_prob`, `edge_pct`, and
    all 5 sniper gates are locked. Cannot alter any numerical field.
    """
    dist_tag = (
        f"NegBin/Gamma (mu={projection.mu:.1f}, sd={projection.sd:.1f}, "
        f"80% CI [{projection.ci_80_low:.1f}, {projection.ci_80_high:.1f}])"
    )
    catalyst_map = {
        "injury_vacancy": f"Injury vacancy absorption ({projection.catalyst_detail or 'teammate scratch'})",
        "usage_surge": f"Live usage/minute surge ({projection.catalyst_detail or 'rotation shift'})",
        "foul_trouble": f"Starter foul-trouble rotation delta ({projection.catalyst_detail or 'early fouls'})",
        "substitution": f"Live lineup substitution delta ({projection.catalyst_detail or 'pbp trigger'})",
        "live_pace": f"Remaining-game live pace scaling ({projection.minutes_remaining:.1f}m rem)",
        "baseline": "Pre-game calibrated distributional prior",
    }
    catalyst_desc = catalyst_map.get(projection.catalyst_reason, projection.catalyst_reason)

    return (
        f"[{alert.sport.upper()} {alert.market.upper()}] {alert.player_name} ({alert.team}) "
        f"{alert.side} {alert.line} @ {alert.book} ({alert.odds_american:+d}). "
        f"Calibrated {dist_tag} prices Fair Line at {alert.fair_line:.1f} "
        f"(P_fair={alert.fair_prob * 100:.1f}% vs P_implied={alert.implied_prob * 100:.1f}%, "
        f"Edge=+{alert.edge_pct:.2f}% / +{alert.mispricing_bps:.0f} bps, "
        f"E[CLV]=+{alert.clv_expectation * 100:.2f}%). "
        f"Catalyst: {catalyst_desc}. "
        f"Receipt: sha256:{alert.source_hash[:12]} (age={alert.feed_age_seconds:.1f}s, "
        f"liq={alert.liquidity_score:.2f})."
    )


class SniperGateEvaluation( dict ):
    """Structured result of evaluating the 5 sniper gates."""


class SniperAgent:
    """
    Agent 6: Evaluates `(PropProjection, MarketMovePayload)` pairs against the
    5-gate Sniper filter. Fires `SniperAlert` and writes to `clv_ledger` only
    when all 5 gates pass. Logs every suppression with exact gate failure reason.
    """

    def __init__(
        self,
        bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
        webhook_dispatcher: WebhookDispatcher | None = None,
    ) -> None:
        self.bus = bus or DurableRedisStreamBus()
        self.truth = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self.webhook_dispatcher = webhook_dispatcher or WebhookDispatcher(
            truth_store=self.truth,
            bus=self.bus,
        )

    @staticmethod
    def estimate_clv_expectation(
        fair_prob: float,
        implied_prob: float,
        catalyst_reason: str,
        liquidity_score: float,
        venue_type: str = "sportsbook",
    ) -> float:
        """
        Deterministic expected Closing Line Value (CLV) estimate in probability units.
        Catalyst-driven re-pricings (injury_vacancy, foul_trouble, usage_surge)
        capture a higher fraction of raw edge before market close.
        """
        raw_edge = fair_prob - implied_prob
        if raw_edge <= 0:
            return round(raw_edge, 4)

        catalyst_retention = {
            "injury_vacancy": 0.72,
            "foul_trouble": 0.65,
            "usage_surge": 0.62,
            "substitution": 0.58,
            "live_pace": 0.55,
            "baseline": 0.48,
        }.get(catalyst_reason, 0.50)

        venue_factor = 0.88 if venue_type == "polymarket" else 0.78
        liq_factor = max(0.4, min(1.0, float(liquidity_score)))
        return round(raw_edge * catalyst_retention * venue_factor * liq_factor, 4)

    def evaluate_candidate(
        self,
        projection: PropProjection,
        market: MarketMovePayload,
        gate_config: SniperGateConfig | None = None,
        now: datetime | None = None,
    ) -> tuple[SniperAlert | None, StructuredAgentLog]:
        """
        Evaluate a projection + market state against all 5 Sniper gates.
        Returns `(SniperAlert | None, StructuredAgentLog)`.
        """
        t0 = time.perf_counter()
        now_dt = now or datetime.now(timezone.utc)
        cfg = gate_config or SniperGateConfig(
            sport=projection.sport,
            is_live=market.is_live,
        )

        # Determine higher-edge side (OVER/YES vs UNDER/NO)
        edge_over = (projection.fair_prob_over - market.implied_prob_over) * 100.0
        edge_under = (projection.fair_prob_under - market.implied_prob_under) * 100.0

        if edge_over >= edge_under:
            side = "YES" if market.venue_type == "polymarket" else "OVER"
            fair_prob = projection.fair_prob_over
            implied_prob = market.implied_prob_over
            odds_american = market.over_odds
            edge_pct = round(edge_over, 2)
        else:
            side = "NO" if market.venue_type == "polymarket" else "UNDER"
            fair_prob = projection.fair_prob_under
            implied_prob = market.implied_prob_under
            odds_american = market.under_odds
            edge_pct = round(edge_under, 2)

        mispricing_bps = round((fair_prob - implied_prob) * 10000.0, 1)

        # Freshness / Stale Kill Switch check across BOTH projection & market quote
        proj_stale, proj_age_s, proj_limit_s = self.kill_switch.check_freshness(
            fetched_at=projection.fetched_at,
            feed_type="injury" if projection.catalyst_reason == "injury_vacancy" else "lineup",
            is_live=market.is_live,
            now=now_dt,
        )
        mkt_stale, mkt_age_s, mkt_limit_s = self.kill_switch.check_freshness(
            fetched_at=market.fetched_at,
            feed_type="odds",
            is_live=market.is_live,
            now=now_dt,
        )
        effective_age_s = round(max(projection.feed_age_seconds, proj_age_s, mkt_age_s), 2)
        user_age_limit_s = cfg.effective_feed_age_limit("odds")
        is_stale = bool(
            projection.is_stale
            or proj_stale
            or mkt_stale
            or (effective_age_s > user_age_limit_s)
        )

        clv_expectation = self.estimate_clv_expectation(
            fair_prob=fair_prob,
            implied_prob=implied_prob,
            catalyst_reason=projection.catalyst_reason,
            liquidity_score=market.liquidity_score,
            venue_type=market.venue_type,
        )

        combined_hash = compute_source_hash(
            {
                "projection_hash": projection.source_hash,
                "market_hash": market.source_hash,
                "model_version": projection.model_version,
            }
        )

        # Evaluate the 5 strict gates in priority order:
        # Gate 3 (Stale Kill Switch) checked first so stale feeds are explicitly tagged HALTED_STALE
        failed_gates: list[str] = []
        if is_stale:
            failed_gates.append(
                f"GATE_3_STALE_FEED(age={effective_age_s:.1f}s > limit={min(mkt_limit_s, user_age_limit_s):.1f}s)"
            )

        required_edge_pct = cfg.effective_edge_gate_pct()
        if edge_pct < required_edge_pct:
            failed_gates.append(
                f"GATE_1_INSUFFICIENT_EDGE(edge={edge_pct:.2f}% < gate={required_edge_pct:.2f}%)"
            )

        if projection.confidence_score < cfg.min_confidence_score:
            failed_gates.append(
                f"GATE_2_LOW_CONFIDENCE(conf={projection.confidence_score:.2f} < gate={cfg.min_confidence_score:.2f})"
            )

        if market.liquidity_score < cfg.min_liquidity_score:
            failed_gates.append(
                f"GATE_4_THIN_LIQUIDITY(liq={market.liquidity_score:.2f} < gate={cfg.min_liquidity_score:.2f})"
            )

        if clv_expectation < cfg.min_clv_expectation:
            failed_gates.append(
                f"GATE_5_LOW_CLV_EXPECTATION(clv={clv_expectation:.4f} < gate={cfg.min_clv_expectation:.4f})"
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        if failed_gates:
            decision = "HALTED_STALE" if is_stale else "SUPPRESSED"
            reason = "; ".join(failed_gates)
            log_entry = StructuredAgentLog(
                agent="SniperAgent",
                event_type="sniper.gate_evaluated",
                prop_id=projection.prop_id,
                latency_ms=latency_ms,
                decision=decision,
                reason=reason,
                source_hash=combined_hash,
                feed_age_seconds=effective_age_s,
                is_stale=is_stale,
            )
            self.truth.record_event(
                event_type="sniper.suppressed",
                prop_id=projection.prop_id,
                game_id=projection.game_id,
                player_id=projection.player_id,
                payload={
                    "failed_gates": failed_gates,
                    "edge_pct": edge_pct,
                    "confidence_score": projection.confidence_score,
                    "liquidity_score": market.liquidity_score,
                    "clv_expectation": clv_expectation,
                    "feed_age_seconds": effective_age_s,
                },
                source_hash=combined_hash,
                fetched_at=market.fetched_at,
                feed_age_seconds=effective_age_s,
                is_stale=is_stale,
                decision=decision,
                reason=reason,
                latency_ms=latency_ms,
            )
            return None, log_entry

        # All 5 gates passed -> Lock numerical pricing & stake first
        ev_unit = round(ev_per_unit(fair_prob, odds_american), 4)
        kelly = round(
            min(
                cfg.kelly_cap,
                0.25 * kelly_fraction(fair_prob, odds_american, cap=cfg.kelly_cap * 4.0),
            ),
            4,
        )

        mins_kickoff = getattr(projection, "minutes_until_kickoff", None)
        effective_mins = mins_kickoff if mins_kickoff is not None else 45.0
        urgency = compute_urgency_score(effective_mins)
        tier = classify_edge_tier(edge_pct)
        decaying = should_show_decaying_badge(
            edge_when_detected=edge_pct,
            current_edge=edge_pct,
            minutes_until_kickoff=effective_mins,
        )

        alert = SniperAlert(
            alert_id=f"sniper_{projection.prop_id}_{combined_hash[:8]}",
            prop_id=projection.prop_id,
            sport=projection.sport,
            game_id=projection.game_id,
            player_id=projection.player_id,
            player_name=projection.player_name,
            team=projection.team,
            opponent=projection.opponent,
            market=projection.market,
            side=side,
            venue_type=market.venue_type,
            book=market.book,
            line=market.line,
            odds_american=odds_american,
            fair_line=projection.fair_line,
            fair_prob=round(fair_prob, 4),
            implied_prob=round(implied_prob, 4),
            edge_pct=edge_pct,
            mispricing_bps=mispricing_bps,
            ev_per_unit=ev_unit,
            kelly_stake=kelly,
            confidence_score=projection.confidence_score,
            liquidity_score=market.liquidity_score,
            clv_expectation=clv_expectation,
            feed_age_seconds=effective_age_s,
            is_stale=False,
            deep_link=market.deep_link,
            catalyst_reason=projection.catalyst_reason,
            reasoning_chain="",
            source_hash=combined_hash,
            model_version=projection.model_version,
            urgency_score=urgency,
            edge_tier=tier,
            is_decaying=decaying,
            minutes_until_kickoff=mins_kickoff,
            created_at=now_dt,
        )

        # Post-decision narrator runs ONLY after all numbers are locked
        alert.reasoning_chain = narrate_locked_alert(alert, projection)

        # Persist to TruthStore (sniper_alerts + clv_ledger) and publish to Redis stream
        self.truth.save_sniper_alert(alert)
        self.bus.xadd(
            STREAM_SNIPER,
            {
                "event_type": "sniper.alert_fired",
                "alert_id": alert.alert_id,
                "prop_id": alert.prop_id,
                "payload": alert.model_dump(mode="json"),
            },
        )
        if self.webhook_dispatcher is not None:
            self.webhook_dispatcher.dispatch_alert(
                alert,
                async_dispatch=True,
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        log_entry = StructuredAgentLog(
            agent="SniperAgent",
            event_type="sniper.alert_fired",
            prop_id=projection.prop_id,
            latency_ms=latency_ms,
            decision="FIRED",
            reason=f"ALL_5_GATES_PASSED(edge={edge_pct:.2f}%, conf={projection.confidence_score:.2f}, liq={market.liquidity_score:.2f}, clv={clv_expectation:.4f})",
            source_hash=combined_hash,
            feed_age_seconds=effective_age_s,
            is_stale=False,
        )
        self.truth.record_event(
            event_type="sniper.alert_fired",
            prop_id=projection.prop_id,
            game_id=projection.game_id,
            player_id=projection.player_id,
            payload=alert.model_dump(mode="json"),
            source_hash=combined_hash,
            fetched_at=market.fetched_at,
            feed_age_seconds=effective_age_s,
            is_stale=False,
            decision="FIRED",
            reason=log_entry.reason,
            latency_ms=latency_ms,
        )
        return alert, log_entry
