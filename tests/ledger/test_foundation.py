"""Ledger schema, append-only chain, cohorts, prices, and the research API."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from starlette.testclient import TestClient

from src.crypto_utils import canonical_json_sha256
from src.ledger.close_match import LINE_CHANGED, CloseQuote, match_close
from src.ledger.context_gate import UNVERIFIED_CONTEXT, VERIFIED_CONTEXT, reference_context_status
from src.ledger.gates import public_gate_flags, read_independent_gates
from src.ledger.historical_gaps import inventory_historical_gaps, summarize_gaps
from src.ledger.language import find_forbidden
from src.ledger.metrics import evaluate_prices
from src.ledger.registry import STRUCTURAL_DISCLAIMER, artifact_sha256, require_active_registration
from src.ledger.slip_audit import Leg, UnconfirmedLegRejected, audit_confirmed_legs
from src.ledger.store import (
    LedgerUnavailable,
    add_intended_quote,
    add_placement,
    count_rows,
    create_research_reference,
    create_slip_audit,
    import_signal_row,
    latest_registration,
    population_counts,
    record_closing_reference,
    verify_passport_chain,
)
from src.ledger.export import export_ledger_jsonl

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _signal_row(**overrides):
    row = {
        "schema": "propstein.prospective_board.v1",
        "event_id": "evt-synthetic",
        "event_start_at": "2026-11-08T18:00:00+00:00",
        "captured_at": "2026-11-08T12:00:00+00:00",
        "game_id": "2026_10_AAA_BBB",
        "player_id": "player-synthetic",
        "market": "receptions",
        "model_version": "negbin-gamma-v3.2",
    }
    row.update(overrides)
    body = {key: value for key, value in row.items() if key != "record_sha256"}
    row["record_sha256"] = canonical_json_sha256(body)
    return row


def test_schema_has_required_tables_and_no_stake_column(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
        tables = {row["table_name"] for row in cur.fetchall()}
        required = {
            "users", "evidence_passports", "research_references", "prospective_signals",
            "slip_audits", "slip_legs", "rule_registry", "rule_registrations",
            "audit_findings", "ledger_events", "closing_references", "settlements",
            "attestations", "historical_evidence_gaps", "intended_quotes", "placements",
            "withdrawals", "gate_flag_events",
        }
        assert required <= tables
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name ILIKE '%stake%'
            """
        )
        assert cur.fetchall() == []
        cur.execute(
            """
            SELECT c.relname AS table_name, count(*) AS count
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND NOT t.tgisinternal
              AND t.tgname LIKE '%reject_%'
            GROUP BY c.relname
            """
        )
        trigger_counts = {row["table_name"]: row["count"] for row in cur.fetchall()}
    for table in required:
        assert trigger_counts.get(table, 0) >= 3
    assert count_rows(admin_conn, "attestations") == 0


def test_registration_hash_and_clock(admin_conn):
    registration = latest_registration(admin_conn)
    assert registration is not None
    assert registration["artifact_sha256"] == artifact_sha256()
    assert registration["release_id"] == "slip_audit_structural_v1"
    registered_at = registration["registered_at"]
    assert registered_at.tzinfo is not None
    assert datetime.now(timezone.utc) - registered_at < timedelta(hours=6)
    artifact = require_active_registration(registration)
    assert artifact["structural_disclaimer"] == STRUCTURAL_DISCLAIMER
    assert artifact["language_permissions"] == {"edge": False, "pick": False, "stake": False}
    with pytest.raises(Exception):
        require_active_registration({"artifact_sha256": "ab" * 32, "release_id": "slip_audit_structural_v1"})


def test_append_only_rejects_update_delete_and_truncate(admin_conn, app_conn):
    with app_conn.cursor() as cur:
        cur.execute("INSERT INTO users (pseudonym) VALUES ('append-only-user') RETURNING id")
        user_id = cur.fetchone()["id"]
    app_conn.commit()
    with pytest.raises(psycopg2.Error) as app_error:
        with app_conn.cursor() as cur:
            cur.execute("UPDATE users SET pseudonym = 'rewritten' WHERE id = %s", (user_id,))
    app_conn.rollback()
    assert app_error.value.pgcode in {"42501", "55000"}
    with pytest.raises(psycopg2.Error) as owner_error:
        with admin_conn.cursor() as cur:
            cur.execute("UPDATE users SET pseudonym = 'rewritten' WHERE id = %s", (user_id,))
    admin_conn.rollback()
    assert owner_error.value.pgcode == "55000"
    with pytest.raises(psycopg2.Error):
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    admin_conn.rollback()
    with pytest.raises(psycopg2.Error):
        with admin_conn.cursor() as cur:
            cur.execute("TRUNCATE ledger_events")
    admin_conn.rollback()
    with app_conn.cursor() as cur:
        cur.execute("SELECT pseudonym FROM users WHERE id = %s", (user_id,))
        assert cur.fetchone()["pseudonym"] == "append-only-user"


def test_research_reference_chain_and_withheld_probability():
    from api.main import app

    client = TestClient(app)
    response = client.post("/api/v1/research-references", json={
        "pseudonym": "reader-1",
        "player_id": "00-0036358",
        "market": "player_receptions",
        "line": 8.5,
        "selection": "over",
        "observed_at": "2026-11-02T15:00:00+00:00",
        "event_id": "evt-ceedee-w8",
        "event_start_at": "2026-11-03T18:00:00+00:00",
        "book": "example",
        "quoted_american_odds": -110,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert "model_probability" not in body
    assert "model_probability" not in response.text
    assert body["model_coverage"] == "uncalibrated"
    assert body["model_version"] == "negbin-gamma-v3.2"
    assert body["context_status"] == UNVERIFIED_CONTEXT
    assert body["uncertainty_interval"] is None
    assert body["saved"] is True
    assert find_forbidden(response.text) == []

    import os
    conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT model_probability, event_id, event_start_at FROM research_references WHERE id = %s",
                (body["research_reference_id"],),
            )
            stored = cur.fetchone()
        assert stored["model_probability"] == pytest.approx(0.4722, abs=1e-4)
        assert stored["event_id"] == "evt-ceedee-w8"
        assert verify_passport_chain(conn, body["passport_id"]) is True
    finally:
        conn.close()
    chain = client.get(f"/api/v1/evidence-passports/{body['passport_id']}/chain")
    assert chain.status_code == 200
    assert chain.json()["valid"] is True
    assert "model_probability" not in chain.text


def test_missing_snapshot_saves_nothing():
    from api.main import app

    client = TestClient(app)
    import os
    conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
    try:
        before = count_rows(conn, "research_references")
    finally:
        conn.close()
    response = client.post("/api/v1/research-references", json={
        "pseudonym": "reader-2",
        "player_id": "no-such-player",
        "market": "player_receptions",
        "line": 4.5,
        "selection": "over",
        "observed_at": "2026-11-02T15:00:00+00:00",
        "event_id": "evt-missing",
        "event_start_at": "2026-11-03T18:00:00+00:00",
    })
    assert response.status_code == 409
    assert response.json()["saved"] is False
    assert response.json()["reason"] == "NO_SERVER_SNAPSHOT"
    conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
    try:
        assert count_rows(conn, "research_references") == before
    finally:
        conn.close()


@pytest.mark.parametrize("observed_at", ["2026-11-02T15:00:00", "2027-01-01T00:00:00+00:00", ""])
def test_bad_timestamps_save_nothing(observed_at):
    from api.main import app

    client = TestClient(app)
    payload = {
        "pseudonym": "reader-3",
        "player_id": "00-0036358",
        "market": "player_receptions",
        "line": 8.5,
        "selection": "over",
        "event_id": "evt-time",
        "event_start_at": "2026-11-03T18:00:00+00:00",
    }
    payload["observed_at"] = observed_at
    response = client.post("/api/v1/research-references", json=payload)
    assert response.status_code == 422
    assert response.json()["saved"] is False


def test_client_model_fields_and_stake_are_rejected():
    from api.main import app

    client = TestClient(app)
    base = {
        "pseudonym": "reader-4",
        "player_id": "00-0036358",
        "market": "player_receptions",
        "line": 8.5,
        "selection": "over",
        "observed_at": "2026-11-02T15:00:00+00:00",
        "event_id": "evt-client",
        "event_start_at": "2026-11-03T18:00:00+00:00",
    }
    for extra in ({"model_probability": 0.5}, {"model_version": "invented"}, {"stake": 10}):
        response = client.post("/api/v1/research-references", json={**base, **extra})
        assert response.status_code == 422


def test_context_gate_uses_existing_cutoff(monkeypatch):
    assert reference_context_status("missing-game", NOW) == UNVERIFIED_CONTEXT
    monkeypatch.setattr("scripts.autopilot.game_context_has_capture_times", lambda now=None: False)
    assert reference_context_status("g1", NOW) == UNVERIFIED_CONTEXT
    import pandas as pd

    monkeypatch.setattr("scripts.autopilot.game_context_has_capture_times", lambda now=None: True)
    monkeypatch.setattr(
        "src.features.load_games",
        lambda: pd.DataFrame([{
            "game_id": "g1",
            "spread_observed_at": "2026-11-01T00:00:00+00:00",
            "total_observed_at": "2026-11-01T00:00:00+00:00",
            "weather_observed_at": "2026-11-01T00:00:00+00:00",
        }]),
    )
    assert reference_context_status("g1", NOW) == VERIFIED_CONTEXT


def test_structural_audit_and_unconfirmed_rejection(app_conn):
    registration = latest_registration(app_conn)
    legs = [
        Leg("p1", "evt-a", "2026-11-08T18:00:00+00:00", "player_receptions", "over", 4.5, True, team="DAL"),
        Leg("p1", "evt-a", "2026-11-08T18:00:00+00:00", "player_reception_yds", "over", 55.5, True, team="DAL"),
    ]
    result = audit_confirmed_legs(legs, registration)
    rule_ids = {finding.rule_id for finding in result.findings}
    assert "STRUCT_SAME_PLAYER" in rule_ids
    assert "STRUCT_SAME_TEAM" in rule_ids
    assert "STRUCT_SAME_GAME" in rule_ids
    assert "STRUCT_DUPLICATE_SELECTION" not in rule_ids
    assert rule_ids.isdisjoint({
        "MODEL_LINE_MISMATCH", "MODEL_PRICE_MISMATCH", "JOINT_DEPENDENCE_HIGH",
        "PAYOUT_DISTRIBUTION_MISMATCH", "SCENARIO_SENSITIVITY", "DISAGREEMENT_INVESTIGATION",
    })
    assert all(finding.disclaimer == STRUCTURAL_DISCLAIMER for finding in result.findings)
    assert "shared" not in json.dumps([finding.detail for finding in result.findings]).lower()
    with pytest.raises(UnconfirmedLegRejected):
        audit_confirmed_legs([
            Leg("p1", "evt-a", "2026-11-08T18:00:00+00:00", "player_receptions", "over", 4.5, False),
        ], registration)

    low = audit_confirmed_legs([
        Leg("p9", "evt-z", "2026-11-08T18:00:00+00:00", "player_receptions", "over", 3.5, True,
            ocr_confidence=0.2, ocr_confirmed=False),
    ], registration)
    assert {finding.rule_id for finding in low.findings} >= {"OCR_LOW_CONFIDENCE", "OCR_UNCONFIRMED", "MISSING_REFERENCE"}


def test_slip_endpoint_rejects_unconfirmed_and_saves_structural_only():
    from api.main import app

    client = TestClient(app)
    rejected = client.post("/api/v1/slip-audits", json={
        "pseudonym": "slip-user",
        "legs": [{
            "player_id": "p1",
            "event_id": "evt-a",
            "event_start_at": "2026-11-08T18:00:00+00:00",
            "market": "player_receptions",
            "selection": "over",
            "line": 4.5,
            "user_confirmed": False,
        }],
    })
    assert rejected.status_code == 422
    assert rejected.json()["reason"] == "UNCONFIRMED_LEG"
    assert rejected.json()["saved"] is False
    saved = client.post("/api/v1/slip-audits", json={
        "pseudonym": "slip-user",
        "legs": [
            {
                "player_id": "p1", "event_id": "evt-a", "event_start_at": "2026-11-08T18:00:00+00:00",
                "team": "DAL", "market": "player_receptions", "selection": "over", "line": 4.5,
                "user_confirmed": True,
            },
            {
                "player_id": "p2", "event_id": "evt-a", "event_start_at": "2026-11-08T18:00:00+00:00",
                "team": "DAL", "market": "player_reception_yds", "selection": "under", "line": 40.5,
                "user_confirmed": True,
            },
        ],
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["disclaimer"] == STRUCTURAL_DISCLAIMER
    assert {item["rule_id"] for item in body["findings"]} == {"STRUCT_SAME_TEAM", "STRUCT_SAME_GAME", "MISSING_REFERENCE"}
    assert find_forbidden(saved.text) == []
    assert "model_probability" not in saved.text


def test_registry_mismatch_refuses_new_audit_and_keeps_old_id(admin_conn, app_conn):
    registration = latest_registration(app_conn)
    saved = create_slip_audit(app_conn, pseudonym="keep-id", legs=[
        Leg("p1", "evt-keep", "2026-11-08T18:00:00+00:00", "player_receptions", "over", 4.5, True),
    ])
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rule_registrations (release_id, artifact_sha256, artifact_canonical)
            VALUES ('slip_audit_structural_v1', %s, '{}')
            """,
            ("cd" * 32,),
        )
    with pytest.raises(LedgerUnavailable) as exc:
        create_slip_audit(admin_conn, pseudonym="keep-id", legs=[
            Leg("p1", "evt-keep", "2026-11-08T18:00:00+00:00", "player_receptions", "over", 5.5, True),
        ])
    assert exc.value.reason == "REGISTRY_HASH_MISMATCH"
    admin_conn.rollback()
    with app_conn.cursor() as cur:
        cur.execute("SELECT registration_id::text FROM slip_audits WHERE id = %s", (saved["slip_audit_id"],))
        assert cur.fetchone()["registration_id"] == registration["id"]


def test_historical_rows_are_not_backfilled_and_user_rows_skip_the_gate(app_conn):
    before = population_counts(app_conn)
    gap_row = {
        "schema": "propstein.prospective_board.v1",
        "game_id": "2026_08_ARI_DAL",
        "kickoff_at": "2026-11-01T18:00:00+00:00",
        "captured_at": "2026-11-01T17:00:00+00:00",
        "player_id": "00-0036358",
        "market": "receptions",
    }
    assert import_signal_row(
        app_conn, row=gap_row, cohort="prospective_full_board",
        source_name="unit-gap", locator="row:1",
    ) == "gap"
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, event_start_at, missing_fields
            FROM historical_evidence_gaps
            WHERE source_name = 'unit-gap'
            """
        )
        stored = cur.fetchone()
    assert stored["event_id"] is None
    assert stored["event_start_at"] is None
    assert "event_id" in stored["missing_fields"]
    assert "event_start_at" in stored["missing_fields"]

    backtest = _signal_row(event_id="evt-backtest", player_id="backtest-player")
    assert import_signal_row(
        app_conn, row=backtest, cohort="historical_backtest",
        source_name="unit-backtest", locator="row:1",
    ) == "signal"
    prospective = _signal_row(event_id="evt-prospective", player_id="prospective-player")
    assert import_signal_row(
        app_conn, row=prospective, cohort="prospective_full_board",
        source_name="unit-prospective", locator="row:1",
    ) == "signal"
    disguised = {
        "schema": "paper.backtest.v0",
        "event_id": "evt-disguised",
        "event_start_at": "2026-11-08T18:00:00+00:00",
        "captured_at": "2026-11-08T12:00:00+00:00",
    }
    disguised["record_sha256"] = canonical_json_sha256(
        {key: value for key, value in disguised.items() if key != "record_sha256"}
    )
    assert import_signal_row(
        app_conn, row=disguised, cohort="prospective_full_board",
        source_name="unit-disguised", locator="row:1",
    ) == "gap"

    board = ROOT / "snapshots" / "full_board_2026_w8_early_1300.jsonl"
    lines = [line for line in board.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, line in enumerate(lines, start=1):
        assert import_signal_row(
            app_conn, row=json.loads(line), cohort="prospective_full_board",
            source_name="snapshots/full_board_2026_w8_early_1300.jsonl", locator=f"line:{index}",
        ) == "gap"
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS n, bool_and(event_id IS NULL) AS all_null
            FROM historical_evidence_gaps
            WHERE source_name = 'snapshots/full_board_2026_w8_early_1300.jsonl'
            """
        )
        board_gaps = cur.fetchone()
    assert board_gaps["n"] == len(lines)
    assert board_gaps["all_null"] is True

    create_research_reference(
        app_conn,
        pseudonym="not-a-signal",
        player_id="00-0036358",
        market="player_receptions",
        line=8.5,
        selection="over",
        observed_at=datetime(2026, 11, 2, 15, tzinfo=timezone.utc),
        event_id="evt-user-only",
        event_start_at=datetime(2026, 11, 3, 18, tzinfo=timezone.utc),
        book=None,
        quoted_american_odds=None,
        snapshot_dir=ROOT / "snapshots",
    )
    after = population_counts(app_conn)
    assert after["committed_forecasts"] == before["committed_forecasts"] + 1
    assert after["committed_forecasts"] == 1 or after["committed_forecasts"] == before["committed_forecasts"] + 1


def test_close_match_populations_and_separate_clv(app_conn):
    before = population_counts(app_conn)
    row = _signal_row(event_id="evt-prices", player_id="price-player", market="player_receptions")
    assert import_signal_row(
        app_conn, row=row, cohort="prospective_full_board",
        source_name="unit-prices", locator="row:1",
    ) == "signal"
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM prospective_signals WHERE source_record_sha256 = %s",
            (row["record_sha256"],),
        )
        signal_id = cur.fetchone()["id"]
    intended = CloseQuote("evt-prices", "player_receptions", "over", 4.5, "nfl_player_prop_v1", -110, -110)
    moved = CloseQuote("evt-prices", "player_receptions", "over", 5.5, "nfl_player_prop_v1", -180, 150)
    same = CloseQuote("evt-prices", "player_receptions", "over", 4.5, "nfl_player_prop_v1", -150, 130)
    quoted_at = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    add_intended_quote(app_conn, signal_id=signal_id, quote=intended, book="example", quoted_at=quoted_at)
    changed = record_closing_reference(
        app_conn, signal_id=signal_id, placement_id=None, observed=moved,
        source_id="close-source-a", observed_at=datetime(2026, 11, 8, 17, tzinfo=timezone.utc),
    )
    assert changed["match_status"] == "UNMATCHED"
    assert changed["reason_code"] == LINE_CHANGED
    unplaced = evaluate_prices(
        intended=intended, placement=None, committed_close=moved, placement_close=None, model_probability=0.61,
    )
    assert unplaced.intended_clv is None
    assert unplaced.placement_clv is None
    assert unplaced.model_vs_close is None
    matched = record_closing_reference(
        app_conn, signal_id=signal_id, placement_id=None, observed=same,
        source_id="close-source-b", observed_at=datetime(2026, 11, 8, 17, 5, tzinfo=timezone.utc),
    )
    assert matched["match_status"] == "MATCHED"
    priced = evaluate_prices(
        intended=intended, placement=None, committed_close=same, placement_close=None, model_probability=0.61,
    )
    assert priced.intended_clv is not None and priced.intended_clv > 0
    assert priced.placement_clv is None
    assert priced.model_vs_close is not None
    assert "clv" not in "model_vs_close".replace("model_vs_close", "")
    assert set(priced.as_dict()) >= {"intended_clv", "placement_clv", "execution_slippage", "model_vs_close"}
    placement = CloseQuote("evt-prices", "player_receptions", "over", 4.5, "nfl_player_prop_v1", -130, 110)
    placement_id = add_placement(
        app_conn, signal_id=signal_id, ticket_ref="ticket-real-1", quote=placement,
        book="example", placed_at=quoted_at,
    )
    placed_close = record_closing_reference(
        app_conn, signal_id=None, placement_id=placement_id, observed=same,
        source_id="close-source-c", observed_at=datetime(2026, 11, 8, 17, 6, tzinfo=timezone.utc),
    )
    assert placed_close["match_status"] == "MATCHED"
    with_placement = evaluate_prices(
        intended=intended, placement=placement, committed_close=same, placement_close=same,
        model_probability=0.61,
    )
    assert with_placement.placement_clv is not None
    assert with_placement.execution_slippage is not None
    assert with_placement.execution_slippage > 0
    with pytest.raises(psycopg2.Error):
        with app_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO closing_references (
                  signal_id, event_id, event_start_at, source_id, market, selection, line,
                  settlement_rules, over_american_odds, under_american_odds, observed_at,
                  match_status, reason_code
                )
                SELECT id, event_id, event_start_at, 'bad-source', 'player_receptions', 'over', 9.5,
                       'nfl_player_prop_v1', -110, -110, now(), 'MATCHED', NULL
                FROM prospective_signals WHERE id = %s
                """,
                (signal_id,),
            )
    app_conn.rollback()
    after = population_counts(app_conn)
    assert after["committed_forecasts"] == before["committed_forecasts"] + 1
    assert after["closing_price_matches"] == before["closing_price_matches"] + 1
    assert after["closing_price_matches_committed"] == after["closing_price_matches"]
    assert after["closing_price_matches_placements"] == before["closing_price_matches_placements"] + 1
    assert after["placements"] == before["placements"] + 1
    assert after["missing_closing_quotes"] == before["missing_closing_quotes"]
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO settlements (
              signal_id, event_id, event_start_at, settlement_rules, result, settled_at
            )
            SELECT id, event_id, event_start_at, 'nfl_player_prop_v1', 'win', event_start_at
            FROM prospective_signals WHERE id = %s
            """,
            (signal_id,),
        )
        cur.execute(
            """
            INSERT INTO withdrawals (signal_id, event_id, event_start_at, withdrawn_at, reason_code)
            SELECT id, event_id, event_start_at, event_start_at, 'operator_withdrawal'
            FROM prospective_signals WHERE id = %s
            """,
            (signal_id,),
        )
    app_conn.commit()
    graded = population_counts(app_conn)
    assert graded["graded_forecasts"] == before["graded_forecasts"] + 1
    assert graded["withdrawals"] == before["withdrawals"] + 1
    direct = match_close(intended, moved)
    assert direct.reason_code == LINE_CHANGED
    assert direct.matched is False


def test_gate_flags_are_independent_and_not_qualified(admin_conn, tmp_path):
    flags = read_independent_gates(ROOT)
    public = public_gate_flags(flags)
    assert public == {"model_validation_passed": False, "paid_tier_clv_passed": False}
    assert "QUALIFIED" not in json.dumps(public)
    holdout = {
        "metrics": {"brier_skill_score_pct": 1.0},
    }
    (tmp_path / "viewer").mkdir()
    (tmp_path / "viewer" / "holdout_eval_2026_w1.json").write_text(json.dumps(holdout), encoding="utf-8")
    opened = read_independent_gates(tmp_path)
    assert opened["model_validation"]["passed"] is True
    assert opened["paid_tier_clv"]["passed"] is False
    with pytest.raises(psycopg2.Error):
        with admin_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gate_flag_events (flag_name, passed, basis) VALUES ('QUALIFIED', true, 'no')"
            )
    admin_conn.rollback()
    from api.main import app

    body = TestClient(app).get("/api/v1/ledger/gates").json()
    assert set(body) == {"model_validation_passed", "paid_tier_clv_passed"}
    assert body["model_validation_passed"] is False
    assert body["paid_tier_clv_passed"] is False


def test_historical_inventory_lists_missing_evidence():
    rows = inventory_historical_gaps(ROOT)
    summary = {item["source"]: item for item in summarize_gaps(rows)}
    board = summary["snapshots/full_board_2026_w8_early_1300.jsonl"]
    assert board["records"] == 472
    assert board["missing_fields"]["event_id"] == 472
    assert board["missing_fields"]["event_start_at"] == 472
    ledger = summary["viewer/clv_report_2026_w7.json"]
    assert ledger["records"] == 37
    assert ledger["missing_fields"]["event_id"] == 37
    audit = summary["viewer/clv_audit_report.json"]
    assert audit["records"] == 8
    assert audit["missing_fields"]["event_id"] == 8
    assert summary["public/clv_audit_report.json"]["records"] == 8
    for name in (
        "snapshots/snapshots_2026_w1.jsonl",
        "snapshots/snapshots_2026_w7.jsonl",
        "snapshots/snapshots_2026_w8.jsonl",
    ):
        assert summary[name]["missing_fields"]["event_id"] == summary[name]["records"]
        assert summary[name]["records"] > 0
    ufc = summary["viewer/ufc_ledger.json"]
    assert ufc["missing_fields"]["event_start_at"] == ufc["records"]
    assert all(row["event_id_present"] is False for row in rows if row["source"].endswith("full_board_2026_w8_early_1300.jsonl"))


def test_language_surface_and_export(tmp_path, app_conn):
    roots = [ROOT / "src" / "ledger", ROOT / "api" / "ledger_router.py"]
    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            if path.name == "language.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    hits = find_forbidden(node.value)
                    if hits:
                        offenders.append(f"{path}:{hits}")
    assert offenders == []
    destination = tmp_path / "ledger.jsonl"
    exported = export_ledger_jsonl(app_conn, destination)
    assert exported["anchoring"] == "not_implemented"
    assert exported["event_count"] >= 0


def test_attestations_remain_empty(admin_conn):
    assert count_rows(admin_conn, "attestations") == 0
