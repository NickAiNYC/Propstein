from pathlib import Path
import pytest
from src.services.arb_ledger import (
    compute_entry_receipt_hash,
    compute_receipt_hash,
    verify_receipt,
    calculate_clv,
    build_verifiable_receipt,
    ArbLedgerService,
)
from src.agents.persistence import TruthStore


def test_sha256_receipt_hashing_and_tamper_detection():
    data = {
        "alert_id": "alert_test_101",
        "market": "PTS",
        "prop_type": "points",
        "line": 28.5,
        "entry_line": 28.5,
        "entry_odds_book": 1.909091,
        "fair_prob": 0.58,
        "source_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "model_version": "propwire-dist-v2.4",
        "status": "PENDING",
    }
    h1 = compute_entry_receipt_hash(data)
    assert isinstance(h1, str) and len(h1) == 64
    data["entry_receipt_hash"] = h1
    h_full = compute_receipt_hash(data)
    data["receipt_hash"] = h_full

    # Verification passes with untampered data
    res = verify_receipt(data)
    assert res["verified"] is True

    # Tampering with line fails verification
    tampered = dict(data)
    tampered["line"] = 29.5
    tampered_res = verify_receipt(tampered)
    assert tampered_res["verified"] is False


def test_clv_calculation():
    # Entry odds 2.10 (+110) closing at 1.90 (-111) -> CLV = (2.10 - 1.90) / 1.90 = +10.53%
    res = calculate_clv(2.10, 1.90)
    assert res["clv_pct"] == 10.5263
    assert res["clv_ratio"] == 0.105263

    # Negative CLV when price moved against bettor
    res_neg = calculate_clv(1.85, 2.00)
    assert res_neg["clv_pct"] == -7.5000


def test_arb_ledger_service_grading_and_receipt(tmp_path):
    truth = TruthStore(sqlite_path=tmp_path / "test.db")
    ledger = ArbLedgerService(truth_store=truth)

    alert_id = "test_alert_999"
    truth.upsert_arb_history({
        "alert_id": alert_id,
        "player_id": "giannis_1",
        "player_name": "Giannis Antetokounmpo",
        "market": "PTS",
        "side": "OVER",
        "line": 31.5,
        "entry_line": 31.5,
        "entry_odds_book": 1.95,
        "fair_line": 34.2,
        "fair_prob": 0.62,
        "source_hash": "abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "status": "PENDING",
    })

    # Grade the alert
    updated = ledger.grade_alert(
        alert_id=alert_id,
        closing_line=32.5,
        closing_odds_book=1.80,
        actual_stat=36.0,
        result="won",
    )
    assert updated is not None
    assert updated["status"] == "GRADED"
    assert updated["clv_pct"] > 0
    assert updated["result"] == "won"

    # Fetch self-contained receipt
    receipt = ledger.get_receipt(alert_id)
    assert receipt is not None
    assert receipt["claim"] == "No LLM in Decision Path — Verified SHA-256 Receipt"
    assert receipt["alert_id"] == alert_id
    assert receipt["verified"] is True
    assert "receipt_hash" in receipt

    # Public ledger contains graded entry
    pub = ledger.get_public_ledger(limit=10)
    assert pub["total_graded_alerts"] >= 1
    assert len(pub["receipts"]) >= 1


def test_api_receipt_and_history_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app

    monkeypatch.setenv("PROPSTEIN_API_KEY", "test-private-history-key")
    client = TestClient(app)

    # 1. Test public arb ledger performance endpoint
    res_ledger = client.get("/api/ledger?limit=10")
    assert res_ledger.status_code == 200
    ledger_data = res_ledger.json()
    assert "total_graded_alerts" in ledger_data
    assert "average_clv_beat_pct" in ledger_data
    assert "receipts" in ledger_data

    # 2. Test paginated sniper history endpoint
    res_hist = client.get("/api/sniper/history?limit=10")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert "total_alerts" in hist_data
    assert "items" in hist_data

    # 3. Test private history requires auth when private_only=True
    res_unauth = client.get("/api/sniper/history?private_only=true")
    assert res_unauth.status_code == 401

    # 4. Authorized request passes
    res_auth = client.get(
        "/api/sniper/history?private_only=true",
        headers={"X-PropWire-API-Key": "test-private-history-key"},
    )
    assert res_auth.status_code == 200


def test_public_verify_landing_page():
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    # Fully public, zero-auth landing page works for anyone in incognito
    res = client.get("/verify/sub_alert_1")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "Verified receipt" in res.text
    assert "No LLM in Decision Path" in res.text

    # Route at /verify without param also serves the landing page
    res_base = client.get("/verify")
    assert res_base.status_code == 200


def test_stripe_billing_checkout_and_webhook(monkeypatch):
    import secrets
    from fastapi.testclient import TestClient
    from api.main import app
    from src.services.billing import verify_stripe_webhook_signature

    client = TestClient(app)
    uid = f"usr_test_{secrets.token_hex(4)}"
    # Exercise the billing contract under an explicit operator reopening.
    # Production checkout remains frozen by default (see test_api_security).
    monkeypatch.setenv("PROPSTEIN_PAID_SIGNUPS_ENABLED", "1")

    # 1. Create checkout session for $29/mo.
    #    P2 contract (v175): checkout requires an authenticated session token
    #    (401 otherwise, BEFORE any Stripe call) and derives the billing
    #    user_id SERVER-SIDE from that token — the payload user_id below is a
    #    decoy that must be ignored. Re-contracted from the anonymous-200 era.
    res_checkout = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly", "user_id": "decoy_must_be_ignored", "email": "sharp@example.com"},
        headers={"X-PropStein-API-Key": uid},
    )
    assert res_checkout.status_code == 200
    ch_data = res_checkout.json()
    assert "checkout_url" in ch_data
    assert ch_data["plan"] == "pro_monthly"
    # Server-side identity: the session token (sanitized verbatim < 48 chars)
    # becomes the billing user, and the payload decoy never reaches the ledger.
    assert "decoy_must_be_ignored" not in ch_data.get("checkout_url", "")

    # 2. Check billing status defaults to free observer before payment
    res_status = client.get(f"/api/billing/status?user_id={uid}")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["is_pro"] is False
    assert status_data["tier"] == "free"

    # 3. Simulate an idempotent, properly SIGNED Stripe webhook (fail-closed era:
    #    the endpoint refuses unsigned events when STRIPE_WEBHOOK_SECRET is set)
    import hashlib
    import hmac as _hmac
    import json as _json
    import os as _os
    import time as _time

    webhook_payload = {
        "id": "evt_test_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_test_{uid}",
                "client_reference_id": uid,
                "customer": f"cus_{uid}",
                "subscription": f"sub_{uid}",
                "metadata": {"user_id": uid, "plan": "pro_monthly"},
            }
        },
    }

    secret = "whsec_test_propwire_fail_closed"
    prev_secret = _os.environ.get("STRIPE_WEBHOOK_SECRET")
    try:
        # 3a. Unsigned request with NO configured secret must be REJECTED (fail-closed, 503)
        _os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        res_unsigned = client.post("/api/billing/webhook", json=webhook_payload)
        assert res_unsigned.status_code == 503, "unsigned webhooks must not unlock PRO"

        # 3b. With a secret configured, a bad/missing signature must be REJECTED (400)
        _os.environ["STRIPE_WEBHOOK_SECRET"] = secret
        res_tampered = client.post(
            "/api/billing/webhook",
            content=_json.dumps(webhook_payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={int(_time.time())},v1={'0' * 64}",
            },
        )
        assert res_tampered.status_code == 400

        # 3c. Correctly signed request is processed
        raw = _json.dumps(webhook_payload).encode()
        ts = int(_time.time())
        computed = _hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        res_webhook = client.post(
            "/api/billing/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={ts},v1={computed}",
            },
        )
        assert res_webhook.status_code == 200
        wh_result = res_webhook.json()
        assert wh_result["processed"] is True
    finally:
        if prev_secret is None:
            _os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        else:
            _os.environ["STRIPE_WEBHOOK_SECRET"] = prev_secret

    # 4. Now user status must be PRO
    res_status_pro = client.get(f"/api/billing/status?user_id={uid}")
    assert res_status_pro.status_code == 200
    pro_data = res_status_pro.json()
    assert pro_data["is_pro"] is True
    assert pro_data["tier"] == "pro"
    assert pro_data["plan"] == "pro_monthly"

    # 5. Customer portal creation (P2 contract v175: same auth surface as checkout)
    res_portal = client.post(
        "/api/billing/create-portal-session",
        json={"customer_id": f"cus_{uid}"},
        headers={"X-PropStein-API-Key": uid},
    )
    assert res_portal.status_code == 200
    assert "portal_url" in res_portal.json()


def _full_sniper_alert(alert_id: str):
    """Minimal-but-complete SniperAlert as produced by the SniperAgent 5-gate path."""
    from datetime import datetime, timezone as _tz

    from src.agents.schemas import SniperAlert

    return SniperAlert(
        alert_id=alert_id,
        prop_id="giannis_antetokounmpo:points",
        sport="nba",
        game_id="nba_2026_1029_bos_mil",
        player_id="giannis_antetokounmpo",
        player_name="Giannis Antetokounmpo",
        team="MIL",
        opponent="BOS",
        market="points",
        side="OVER",
        venue_type="sportsbook",
        book="DraftKings",
        line=31.5,
        odds_american=-112,
        fair_line=34.2,
        fair_prob=0.641,
        implied_prob=0.529,
        edge_pct=11.2,
        mispricing_bps=1120.0,
        ev_per_unit=0.19,
        kelly_stake=0.028,
        confidence_score=0.87,
        liquidity_score=0.91,
        clv_expectation=0.041,
        feed_age_seconds=2.1,
        deep_link="https://sportsbook.draftkings.com/nba/giannis-pts",
        catalyst_reason="line_move",
        reasoning_chain="NegBin fair 34.2 vs DK 31.5 (-112)",
        source_hash="a" * 64,
        created_at=datetime(2026, 10, 29, 19, 0, 0, tzinfo=_tz.utc),
    )


def test_receipt_hash_locked_at_alert_creation_before_any_share(tmp_path):
    """
    Mission W2 (Trust Engine): `entry_receipt_hash` and `receipt_hash` MUST be
    persisted in `arb_history` at the exact moment the SniperAlert is created —
    BEFORE any share/verify action — and the share/read path must only ever
    read (never regenerate) those stored hashes.
    """
    from src.services.arb_ledger import ArbLedgerService, verify_receipt

    truth = TruthStore(sqlite_path=tmp_path / "prehash.db")
    alert = _full_sniper_alert("sniper_prehash_001")

    # The moment the alert fires (insert_sniper_alert auto-records arb_history)
    truth.insert_sniper_alert(alert)

    # 1. Row exists IMMEDIATELY — no share button involved
    row = truth.get_arb_history("sniper_prehash_001")
    assert row is not None, "arb_history row must exist the moment the alert fires"
    assert row["status"] == "PENDING"

    # 2. Both hashes are locked at creation, full SHA-256 length
    assert row["entry_receipt_hash"] and len(row["entry_receipt_hash"]) == 64
    assert row["receipt_hash"] and len(row["receipt_hash"]) == 64

    # 3. The stored row verifies cryptographically BEFORE any share action
    assert verify_receipt(row)["verified"] is True

    # 4. Share/read path (get_receipt) returns the SAME stored hash — read-only
    ledger = ArbLedgerService(truth_store=truth)
    receipt = ledger.get_receipt("sniper_prehash_001")
    assert receipt is not None
    assert receipt["entry_receipt_hash"] == row["entry_receipt_hash"]
    assert receipt["receipt_hash"] == row["receipt_hash"]

    # 5. Grading preserves the entry-time hash and re-locks the full hash
    ledger.grade_alert(
        alert_id="sniper_prehash_001",
        closing_line=33.5,
        closing_odds_american=-105,
        actual_stat=36.0,
    )
    graded = truth.get_arb_history("sniper_prehash_001")
    assert graded["status"] == "GRADED"
    assert graded["entry_receipt_hash"] == row["entry_receipt_hash"], "entry hash must never change"
    assert graded["receipt_hash"] != row["receipt_hash"], "full hash re-locks with closing data"
    assert verify_receipt(graded)["verified"] is True
