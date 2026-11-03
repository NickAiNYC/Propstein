"""
Money-path tests for Agent 6 (`SniperAgent`) 5-gate filter, Week-1 10% gate,
Stale Kill Switch enforcement, and CLV ledger persistence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.agents.schemas import (
    MarketMovePayload,
    PropProjection,
    SniperGateConfig,
    compute_source_hash,
)
from src.agents.sniper_agent import SniperAgent
from src.agents.stale_kill_switch import StaleKillSwitch


def _make_fixtures(tmp_path: Path):
    bus = DurableRedisStreamBus(
        redis_url="redis://localhost:6399/0",  # Forces deterministic WAL mode in tests
        wal_db_path=tmp_path / "test_wal.db",
    )
    truth = TruthStore(sqlite_path=tmp_path / "test_truth.db")
    kill_switch = StaleKillSwitch()
    agent = SniperAgent(bus=bus, truth_store=truth, kill_switch=kill_switch)
    return agent, truth, bus


def _sample_projection(
    now: datetime,
    fair_prob_over: float = 0.61,
    confidence_score: float = 0.84,
    sport: str = "nba",
    age_seconds: float = 4.0,
    is_stale: bool = False,
) -> PropProjection:
    fetched = now - timedelta(seconds=age_seconds)
    return PropProjection(
        prop_id="nba_tyrese_maxey_pts",
        sport=sport,  # type: ignore[arg-type]
        game_id="nba_20261029_det_phi",
        player_id="nba_tyrese_maxey",
        player_name="Tyrese Maxey",
        team="PHI",
        opponent="DET",
        position="PG",
        market="points",
        line=26.5,
        mu=30.2,
        sd=6.4,
        fair_line=29.8,
        fair_prob_over=fair_prob_over,
        fair_prob_under=round(1.0 - fair_prob_over, 4),
        ci_80_low=22.0,
        ci_80_high=38.5,
        confidence_score=confidence_score,
        minutes_projection=39.5,
        minutes_remaining=39.5,
        usage_rate=0.345,
        remaining_opportunities=23.5,
        catalyst_reason="injury_vacancy",
        catalyst_detail="Joel Embiid OUT",
        source_hash=compute_source_hash({"test": "proj", "p": fair_prob_over}),
        fetched_at=fetched,
        feed_age_seconds=age_seconds,
        is_stale=is_stale,
    )


def _sample_market(
    now: datetime,
    implied_prob_over: float = 0.515,
    liquidity_score: float = 0.90,
    sport: str = "nba",
    is_live: bool = False,
    age_seconds: float = 3.0,
) -> MarketMovePayload:
    fetched = now - timedelta(seconds=age_seconds)
    return MarketMovePayload(
        prop_id="nba_tyrese_maxey_pts",
        sport=sport,  # type: ignore[arg-type]
        game_id="nba_20261029_det_phi",
        player_id="nba_tyrese_maxey",
        player_name="Tyrese Maxey",
        team="PHI",
        opponent="DET",
        market="points",
        venue_type="sportsbook",
        book="DraftKings",
        line=26.5,
        over_odds=-110,
        under_odds=-110,
        implied_prob_over=implied_prob_over,
        implied_prob_under=round(1.0 - implied_prob_over, 4),
        liquidity_score=liquidity_score,
        is_live=is_live,
        source_hash=compute_source_hash({"test": "mkt", "p": implied_prob_over}),
        fetched_at=fetched,
    )


def test_all_five_gates_pass_fires_alert_and_logs_clv(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, truth, _ = _make_fixtures(tmp_path)

    proj = _sample_projection(now, fair_prob_over=0.61, confidence_score=0.85)
    mkt = _sample_market(now, implied_prob_over=0.51, liquidity_score=0.92)

    alert, log = agent.evaluate_candidate(proj, mkt, now=now)
    assert alert is not None
    assert log.decision == "FIRED"
    assert alert.edge_pct == pytest.approx(10.0, abs=0.05)
    assert alert.fair_prob == 0.61
    assert alert.is_stale is False
    assert "Tyrese Maxey" in alert.reasoning_chain
    assert alert.source_hash

    # Verify TruthStore persistence in both sniper_alerts and clv_ledger
    recent_alerts = truth.get_recent_alerts(limit=5)
    assert len(recent_alerts) == 1
    assert recent_alerts[0]["alert_id"] == alert.alert_id

    clv = truth.get_clv_summary()
    assert clv["total_logged"] == 1


def test_gate_1_edge_threshold_and_nfl_week_1_10pct_gate(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, _, _ = _make_fixtures(tmp_path)

    # 1. Sub-3% edge (2.1%) -> suppressed under normal gate
    proj_small = _sample_projection(now, fair_prob_over=0.531, sport="nfl")
    mkt = _sample_market(now, implied_prob_over=0.510, sport="nfl")
    alert, log = agent.evaluate_candidate(proj_small, mkt, now=now)
    assert alert is None
    assert log.decision == "SUPPRESSED"
    assert "GATE_1_INSUFFICIENT_EDGE" in log.reason

    # 2. 6.5% edge in NFL Week 1 -> suppressed because Week 1 requires >= 10.0%
    proj_w1 = _sample_projection(now, fair_prob_over=0.575, sport="nfl")
    cfg_w1 = SniperGateConfig(sport="nfl", is_week_1=True, min_edge_pct=3.0)
    assert cfg_w1.effective_edge_gate_pct() == 10.0
    alert_w1, log_w1 = agent.evaluate_candidate(proj_w1, mkt, gate_config=cfg_w1, now=now)
    assert alert_w1 is None
    assert "GATE_1_INSUFFICIENT_EDGE" in log_w1.reason

    # 3. 11.5% edge in NFL Week 1 -> passes Week 1 10% gate
    proj_w1_pass = _sample_projection(now, fair_prob_over=0.625, sport="nfl")
    alert_w1_ok, log_w1_ok = agent.evaluate_candidate(proj_w1_pass, mkt, gate_config=cfg_w1, now=now)
    assert alert_w1_ok is not None
    assert log_w1_ok.decision == "FIRED"


def test_gate_2_confidence_gate_suppression(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, _, _ = _make_fixtures(tmp_path)

    proj = _sample_projection(now, fair_prob_over=0.62, confidence_score=0.45)
    mkt = _sample_market(now, implied_prob_over=0.50)
    cfg = SniperGateConfig(min_confidence_score=0.65)

    alert, log = agent.evaluate_candidate(proj, mkt, gate_config=cfg, now=now)
    assert alert is None
    assert log.decision == "SUPPRESSED"
    assert "GATE_2_LOW_CONFIDENCE" in log.reason


def test_gate_3_stale_kill_switch_halts_firing(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, truth, _ = _make_fixtures(tmp_path)

    # Live odds older than 20s threshold (e.g., 28s old) -> HALTED_STALE
    proj = _sample_projection(now, fair_prob_over=0.65, age_seconds=5.0)
    mkt_stale_live = _sample_market(now, implied_prob_over=0.50, is_live=True, age_seconds=28.0)

    alert, log = agent.evaluate_candidate(proj, mkt_stale_live, now=now)
    assert alert is None
    assert log.decision == "HALTED_STALE"
    assert log.is_stale is True
    assert "GATE_3_STALE_FEED" in log.reason

    # Verify suppression was logged in TruthStore
    suppressions = truth.get_recent_suppressions(limit=5)
    assert any(s["decision"] == "HALTED_STALE" for s in suppressions)


def test_gate_4_thin_liquidity_suppression(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, _, _ = _make_fixtures(tmp_path)

    proj = _sample_projection(now, fair_prob_over=0.63)
    mkt_thin = _sample_market(now, implied_prob_over=0.50, liquidity_score=0.12)
    cfg = SniperGateConfig(min_liquidity_score=0.30)

    alert, log = agent.evaluate_candidate(proj, mkt_thin, gate_config=cfg, now=now)
    assert alert is None
    assert log.decision == "SUPPRESSED"
    assert "GATE_4_THIN_LIQUIDITY" in log.reason


def test_gate_5_low_clv_expectation_suppression(tmp_path: Path):
    now = datetime.now(timezone.utc)
    agent, _, _ = _make_fixtures(tmp_path)

    proj = _sample_projection(now, fair_prob_over=0.545)
    mkt = _sample_market(now, implied_prob_over=0.510, liquidity_score=0.50)
    # Require an unusually high expected CLV (e.g. 5.0% closing edge retention)
    cfg = SniperGateConfig(min_clv_expectation=0.05)

    alert, log = agent.evaluate_candidate(proj, mkt, gate_config=cfg, now=now)
    assert alert is None
    assert log.decision == "SUPPRESSED"
    assert "GATE_5_LOW_CLV_EXPECTATION" in log.reason

