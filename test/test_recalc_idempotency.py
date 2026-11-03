"""
Money-path tests for Agent 1 (`InjuryEventAgent`), Agent 3 (`ProjectionRecalcAgent`),
Agent 5 (`PolymarketSpecialistAgent`), and LangGraph `SniperTerminalEngine`:
- Replay idempotency (replaying the same event yields identical `PropProjection`).
- End-to-end simulated late scratch milestone (<5s into `projections` table
  with `source_hash` and `feed_age_seconds`).
- Polymarket CLOB `token_id` enforcement and top-5 ranking by `mispricing_bps * liquidity_score`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agents.graph import SniperTerminalEngine
from src.agents.injury_agent import InjuryEventAgent
from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.agents.polymarket_agent import PolymarketSpecialistAgent
from src.agents.recalc_agent import ProjectionRecalcAgent, price_prop
from src.agents.schemas import InjuryEventPayload, compute_source_hash
from src.agents.stale_kill_switch import StaleKillSwitch


def _make_engine(tmp_path: Path) -> SniperTerminalEngine:
    bus = DurableRedisStreamBus(
        redis_url="redis://localhost:6399/0",
        wal_db_path=tmp_path / "wal.db",
    )
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    return SniperTerminalEngine(bus=bus, truth_store=truth, kill_switch=StaleKillSwitch())


def test_recalc_agent_replay_idempotency(tmp_path: Path):
    """
    CRITICAL ARCHITECTURAL REQUIREMENT:
    Replaying the exact same injury event produces the exact same PropProjection
    (`mu`, `sd`, `fair_line`, `fair_prob_over`, `fair_prob_under`, `source_hash`).
    """
    now = datetime(2026, 10, 29, 22, 0, 0, tzinfo=timezone.utc)
    bus = DurableRedisStreamBus(redis_url="redis://localhost:6399/0", wal_db_path=tmp_path / "wal.db")
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    recalc = ProjectionRecalcAgent(bus=bus, truth_store=truth)

    raw_payload = {
        "sport": "nba",
        "game_id": "nba_20261029_det_phi",
        "player_id": "nba_joel_embiid",
        "player_name": "Joel Embiid",
        "team": "PHI",
        "opponent": "DET",
        "status": "OUT",
        "body_part": "knee",
        "source_provider": "official_report",
        "vacated_minutes": 34.0,
        "vacated_usage": 0.34,
        "beneficiaries": [
            {
                "player_id": "nba_tyrese_maxey",
                "player_name": "Tyrese Maxey",
                "team": "PHI",
                "position": "PG",
                "added_minutes": 3.5,
                "added_usage_rate": 0.055,
            }
        ],
        "is_live": False,
        "source_hash": compute_source_hash({"embiid": "OUT", "ts": "2026-10-29T22:00:00Z"}),
        "fetched_at": now,
    }
    injury_ev = InjuryEventPayload.model_validate(raw_payload)

    player_state = {
        "sport": "nba",
        "player_id": "nba_tyrese_maxey",
        "player_name": "Tyrese Maxey",
        "team": "PHI",
        "opponent": "DET",
        "position": "PG",
        "baseline_minutes": 37.0,
        "baseline_usage": 0.295,
        "rate_per_min": 0.77,
        "fano_factor": 1.45,
        "confidence_score": 0.84,
    }
    market_state = {
        "prop_id": "nba_tyrese_maxey_pts",
        "market": "points",
        "line": 26.5,
        "over_odds": -110,
        "under_odds": -110,
    }
    game_state = {"game_id": "nba_20261029_det_phi", "is_live": False, "minutes_remaining": 37.0}

    proj_1 = recalc.recalculate_from_injury(
        injury_event=injury_ev,
        player_state=player_state,
        market_state=market_state,
        game_state=game_state,
        now=now,
    )
    proj_2 = recalc.recalculate_from_injury(
        injury_event=injury_ev,
        player_state=player_state,
        market_state=market_state,
        game_state=game_state,
        now=now,
    )

    assert proj_1.mu == proj_2.mu
    assert proj_1.sd == proj_2.sd
    assert proj_1.fair_line == proj_2.fair_line
    assert proj_1.fair_prob_over == proj_2.fair_prob_over
    assert proj_1.fair_prob_under == proj_2.fair_prob_under
    assert proj_1.source_hash == proj_2.source_hash
    assert proj_1.catalyst_reason == "injury_vacancy"
    assert proj_1.mu > 26.5


def test_injury_agent_deduplication_by_player_status_body_part(tmp_path: Path):
    """
    Agent 1 (`InjuryEventAgent`) must hash `{player_id, status, body_part}` and
    skip duplicate re-firing on identical status.
    """
    now = datetime.now(timezone.utc)
    bus = DurableRedisStreamBus(redis_url="redis://localhost:6399/0", wal_db_path=tmp_path / "wal.db")
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    injury_agent = InjuryEventAgent(bus=bus, truth_store=truth)

    payload = {
        "sport": "nfl",
        "game_id": "nfl_2026_w9_lar_sea",
        "player_id": "nfl_cooper_kupp",
        "player_name": "Cooper Kupp",
        "team": "LAR",
        "opponent": "SEA",
        "status": "QUESTIONABLE",
        "body_part": "Ankle",
    }
    first = injury_agent.ingest_event(payload, now=now)
    second = injury_agent.ingest_event(payload, now=now)

    assert first["emitted"] is True
    assert second["emitted"] is False  # Deduplicated
    assert second["decision"] == "DEDUP_SKIPPED"

    # Status change from QUESTIONABLE -> OUT fires new event
    payload_out = dict(payload, status="OUT")
    third = injury_agent.ingest_event(payload_out, now=now)
    assert third["emitted"] is True
    assert third["payload"].status == "OUT"


def test_late_scratch_milestone_under_5_seconds(tmp_path: Path):
    """
    Phase 1 Milestone Verification:
    A simulated late scratch flows through `InjuryEventAgent` -> Redis Stream
    -> LangGraph `StateGraph` -> `ProjectionRecalcAgent` -> `projections` table
    with `source_hash` and `feed_age_seconds` in under 5 seconds.
    """
    engine = _make_engine(tmp_path)
    result = engine.simulate_late_scratch()

    assert result["within_5s_sla"] is True
    assert result["elapsed_ms"] < 5000.0
    assert result["source_hash"]
    assert "nba_tyrese_maxey_pts" in result["projections"]

    saved_proj = engine.truth.get_projection("nba_tyrese_maxey_pts")
    assert saved_proj is not None
    assert saved_proj.source_hash
    assert saved_proj.feed_age_seconds >= 0.0
    assert saved_proj.catalyst_reason == "injury_vacancy"


def test_polymarket_specialist_token_id_enforcement_and_top_5_ranking(tmp_path: Path):
    """
    Phase 2 Milestone Verification:
    1. Rejects records that only pass Gamma `market_id` without `clobTokenIds`/`token_id`.
    2. Returns top 5 mispriced props ranked descending by `mispricing_bps * liquidity_score`.
    """
    engine = _make_engine(tmp_path)
    snapshot = engine.seed_terminal_state()

    poly_board = snapshot["polymarket_board"]
    assert len(poly_board) >= 5

    top_5 = poly_board[:5]
    ranking_scores = [item["ranking_score"] for item in top_5]
    assert ranking_scores == sorted(ranking_scores, reverse=True)

    for item in top_5:
        assert item["token_id"].startswith("0x")
        assert item["ranking_score"] == pytest.approx(
            item["mispricing_bps"] * item["liquidity_score"],
            abs=0.5,
        )

    # Verify passing Gamma market_id without token_id raises ValueError
    proj = next(iter(engine.projections_by_prop_id.values()))
    with pytest.raises(ValueError, match="token_id"):
        engine.polymarket_agent.evaluate_clob_market(
            {"market_id": "gamma_12345", "yes_ask": 0.50},
            proj,
        )


def test_decoupled_5s_substitution_triggers_immediate_bayesian_recalc_on_last_known_odds(tmp_path: Path):
    """
    Secret Sauce Architectural Rule:
    Never let a 30-second odds feed block a 5-second play-by-play event.
    A substitution (`PLAYER1_ID -> PLAYER2_ID`) triggers `simulate_live_substitution`
    immediately, updates the 5-man court lineup, computes the Bayesian remaining-game
    posterior (`bayesian_remaining_game_update`), and evaluates against `last_known_odds`.
    """
    engine = _make_engine(tmp_path)
    engine.seed_terminal_state()

    res = engine.simulate_live_substitution(
        game_id="2026_nba_mil_bos",
        team="MIL",
    )
    assert res["status"] == "ok"
    assert res["within_5s_pbp_budget"] is True
    assert res["used_last_known_odds_cache"] is True
    assert res["bayesian_update"]["posterior_remaining_mu"] > 0
    assert res["sub_in"]["sub_status"] == "SUB_IN"
    assert res["sub_out"]["sub_status"] == "SUB_OUT"


def test_player_id_bridge_exact_and_fuzzy_resolution(tmp_path: Path):
    """
    Verifies the 24h `player_id_mapping` bridge across Polymarket `/v1/sports/players`,
    `propline` normalized book keys, `nba_api` person IDs, and fuzzy `(name, team, position)`.
    """
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    truth.upsert_player_mapping(
        canonical_player_id="nba_giannis",
        sport="nba",
        player_name="Giannis Antetokounmpo",
        team="MIL",
        position="PF",
        polymarket_player_id="poly_giannis_34",
        propline_player_key="nba:mil:giannis_antetokounmpo",
        nba_api_person_id="203507",
    )

    assert truth.resolve_canonical_player_id(polymarket_player_id="poly_giannis_34") == "nba_giannis"
    assert truth.resolve_canonical_player_id(propline_player_key="nba:mil:giannis_antetokounmpo") == "nba_giannis"
    assert truth.resolve_canonical_player_id(nba_api_person_id="203507") == "nba_giannis"
    assert (
        truth.resolve_canonical_player_id(
            player_name="G. Antetokounmpo Jr.",
            team="MIL",
            position="PF",
            sport="nba",
        )
        == "nba_giannis"
    )

