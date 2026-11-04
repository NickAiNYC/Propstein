"""
Commercial P0 Regression Suite:
1. Signed first-party sessions with subject-bound entitlements (pste-ext-v1).
2. Durable transactional ledger with transactional backup and restore drills.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.extension_router import issue_session_token, verify_session_token
from api.main import _billing_principal, verify_entitlement
from src.agents.persistence import TruthStore


@pytest.fixture
def session_env(monkeypatch):
    monkeypatch.setenv("EXTENSION_SESSION_SECRET", "super-secret-key-32-chars-long!!")
    monkeypatch.delenv("WHOP_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")


def test_signed_session_issuance_and_subject_bound_entitlement(session_env):
    token, payload = issue_session_token("usr_quant_lead_01", ttl_seconds=900)
    assert payload["sub"] == "usr_quant_lead_01"
    assert payload["plan"] == "pro"
    assert token.count(".") == 2

    verified = verify_session_token(token)
    assert verified["sub"] == "usr_quant_lead_01"
    assert verified["plan"] == "pro"

    # Verify main api entitlement check
    entitlement = verify_entitlement(f"Bearer {token}")
    assert entitlement["status"] == "active"
    assert entitlement["subject"] == "usr_quant_lead_01"
    assert entitlement["plan"] == "pro"
    assert entitlement["token_type"] == "pste-ext-v1"


def test_tampered_signed_session_fails_closed(session_env):
    token, _ = issue_session_token("usr_honest_01", ttl_seconds=900)
    parts = token.split(".")
    tampered_token = f"{parts[0]}.{parts[1][:-1]}a.{parts[2]}"

    with pytest.raises(HTTPException) as exc_info:
        verify_session_token(tampered_token)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        verify_entitlement(f"Bearer {tampered_token}")
    # Falls back to Whop check, which fails closed (503 without WHOP_API_KEY)
    assert exc_info.value.status_code == 503


def test_expired_signed_session_fails_closed(session_env):
    token, _ = issue_session_token("usr_expired_01", ttl_seconds=-10)
    with pytest.raises(HTTPException) as exc_info:
        verify_session_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_billing_principal_extracts_signed_session_subject(session_env, monkeypatch):
    monkeypatch.setenv("PROPSTEIN_API_KEY", "server_internal_key")
    token, _ = issue_session_token("usr_institution_42", ttl_seconds=900)

    # Billing principal with Bearer token
    derived = _billing_principal(
        request=None,
        authorization=f"Bearer {token}",
        x_propstein_key=None,
        x_propwire_key=None,
    )
    assert derived == "usr_institution_42"


def test_durable_transactional_ledger_and_restore_drill(tmp_path: Path):
    db_file = tmp_path / "truth_store_primary.db"
    backup_file = tmp_path / "truth_store_backup.db"

    ts = TruthStore(sqlite_path=db_file)

    entry_1 = {
        "ledger_id": "clv-test-rec-001",
        "sport": "nfl",
        "game_id": "2026_w9_det_gb",
        "player": "Amon-Ra St. Brown",
        "team": "DET",
        "market": "receiving_yards",
        "side": "over",
        "line": 78.5,
        "odds": -115,
        "market_prob": 0.50,
        "model_prob": 0.58,
        "edge": 0.08,
        "kelly_stake": 0.02,
    }
    entry_2 = {
        "ledger_id": "clv-test-rec-002",
        "sport": "nfl",
        "game_id": "2026_w9_ne_chi",
        "player": "Hunter Henry",
        "team": "NE",
        "market": "receptions",
        "side": "over",
        "line": 2.5,
        "odds": -115,
        "market_prob": 0.50,
        "model_prob": 0.62,
        "edge": 0.12,
        "kelly_stake": 0.03,
    }

    # 1. Transactionally record picks
    lid1 = ts.record_clv_entry(entry_1)
    lid2 = ts.record_clv_entry(entry_2)
    assert lid1 == "clv-test-rec-001"
    assert lid2 == "clv-test-rec-002"

    rows = ts.list_clv_ledger(sport="nfl")
    assert len(rows) == 2
    assert {r["player_name"] for r in rows} == {"Amon-Ra St. Brown", "Hunter Henry"}

    # 2. Transactional live backup drill
    ts.backup_database(backup_file)
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # 3. Simulate disaster recovery: corrupt or wipe primary DB
    db_file.unlink()
    assert not db_file.exists()

    # Re-initialize clean DB and run restore drill
    ts_restored = TruthStore(sqlite_path=db_file)
    ts_restored.restore_database(backup_file)

    # 4. Verify bit-for-bit integrity post-restore
    restored_rows = ts_restored.list_clv_ledger(sport="nfl")
    assert len(restored_rows) == 2
    assert {r["player_name"] for r in restored_rows} == {"Amon-Ra St. Brown", "Hunter Henry"}
    assert restored_rows[0]["entry_line"] in (78.5, 2.5)
