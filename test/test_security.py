"""
Security & Compliance Regression Tests
======================================
1. Stripe webhook fail-closed: returns 503 on missing STRIPE_WEBHOOK_SECRET
   AND returns 503 on invalid HMAC signature.
2. Authenticated POST /api/clv/log: rejects unauthenticated append with 401,
   and scopes writes to picks_log_{user_id}.jsonl.
3. Subprocess injection hardening on /api/run-week/stream: rejects non-int
   season and week query params with 400 before subprocess call.
"""

import json
import os
import tempfile
import pytest
from starlette.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_stripe_webhook_returns_503_on_missing_secret(client, monkeypatch):
    """Assert Stripe webhook fails closed with 503 when STRIPE_WEBHOOK_SECRET is unset."""
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    
    payload = json.dumps({"id": "evt_test_123", "type": "checkout.session.completed"})
    headers = {
        "Stripe-Signature": "t=1700000000,v1=bad_signature_hash",
        "Content-Type": "application/json",
    }
    
    # Test primary billing webhook
    res = client.post("/api/billing/webhook", data=payload, headers=headers)
    assert res.status_code == 503
    assert "not configured" in res.json().get("detail", "").lower()

    # Test legacy webhook alias
    res_legacy = client.post("/webhooks/stripe", data=payload, headers=headers)
    assert res_legacy.status_code == 503


def test_stripe_webhook_returns_400_on_invalid_hmac(client, monkeypatch):
    """Assert Stripe webhook fails closed with 400 when HMAC signature verification fails.

    400 (permanent client error), NOT 503: a 503 tells Stripe to retry an event
    that can never authenticate. Fail-closed contract per merged PR #32:
    unset secret -> 503, bad signature -> 400, valid signature -> 200.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_key_12345")

    payload = json.dumps({"id": "evt_test_123", "type": "checkout.session.completed"})
    headers = {
        "Stripe-Signature": "t=1700000000,v1=invalid_hmac_hash_00000000",
        "Content-Type": "application/json",
    }

    res = client.post("/api/billing/webhook", data=payload, headers=headers)
    assert res.status_code == 400
    assert "invalid stripe webhook signature" in res.json().get("detail", "").lower()


def test_clv_log_requires_auth(client):
    """Assert POST /api/clv/log strictly rejects unauthenticated append with 401."""
    body = {
        "player": "CeeDee Lamb",
        "market": "receiving_yards",
        "side": "over",
        "line": 78.5,
    }
    res = client.post("/api/clv/log", json=body)
    assert res.status_code == 401
    assert "authentication required" in res.json().get("detail", "").lower()


def test_clv_log_scoped_to_user_id(client, monkeypatch, tmp_path):
    """Assert authenticated POST /api/clv/log writes strictly to picks_log_{user_id}.jsonl."""
    monkeypatch.setenv("PICKS_LOG", str(tmp_path / "picks_log.jsonl"))
    
    body = {
        "user_id": "quant_trader_42",
        "player": "Puka Nacua",
        "market": "receiving_yards",
        "side": "over",
        "line": 84.5,
        "odds": -110,
        "model_prob": 0.62,
        "market_prob": 0.52,
        "edge": 0.10,
    }
    headers = {
        "Authorization": "Bearer test_bearer_token_secret",
    }
    
    res = client.post("/api/clv/log", json=body, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["user_id"] == "quant_trader_42"

    target_file = tmp_path / "picks_log_quant_trader_42.jsonl"
    assert target_file.exists()
    with open(target_file, "r") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 1
    assert lines[0]["player"] == "Puka Nacua"
    assert lines[0]["user_id"] == "quant_trader_42"


def test_run_week_stream_rejects_non_int_params(client):
    """Assert /api/run-week/stream validates season and week as strict integers, rejecting with 400."""
    # Non-integer season
    res = client.get("/api/run-week/stream?season=invalid&week=1")
    assert res.status_code == 400
    assert "strict integer" in res.json().get("detail", "").lower()

    # Non-integer week
    res = client.get("/api/run-week/stream?season=2026&week=abc")
    assert res.status_code == 400
    assert "strict integer" in res.json().get("detail", "").lower()

    # Injection / shell meta-character attempts
    res = client.get("/api/run-week/stream?season=2026;whoami&week=1")
    assert res.status_code == 400

    res = client.get("/api/run-week/stream?season=2026&week=1%20||%20ls")
    assert res.status_code == 400

