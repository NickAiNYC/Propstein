"""
PropStein Live Sniper — Extension API tests (api/extension_router.py)
====================================================================
Covers the security contract from docs/LIVE_SNIPER_AUDIT.md:

* Server-side entitlement before session issuance; fail closed (503) when
  verification is unavailable, 401/403 on bad credentials.
* Scoped session tokens: HMAC structure, expiry, tamper resistance,
  wrong-plan rejection, jti revocation.
* Kill switch disables health.ok and fails every protected route closed.
* Per-principal rate limiting on session issuance (429).
* Honest model coverage: synthetic demobook only; every real-book source
  receives NO COVERAGE for drive-level markets (audit §3.3.1).
* The additive include in api/main.py actually mounts the router.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import api.extension_router as ext
from api.extension_router import (
    DEFAULT_SESSION_TTL_SECONDS,
    drive_survival_adjusted,
    issue_session_token,
    router,
    verify_session_token,
)

ENV_VARS = (
    "APP_ENV",
    "PROPWIRE_ALLOW_DEV_AUTH_BYPASS",
    "WHOP_API_KEY",
    "EXTENSION_SESSION_SECRET",
    "EXTENSION_KILL_SWITCH",
    "EXTENSION_SESSION_TTL_SECONDS",
)


@pytest.fixture
def client():
    """Standalone mount of the extension router (no api.main import graph)."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    ext._REVOKED_JTI.clear()
    ext._RATE_BUCKETS.clear()
    yield
    ext._REVOKED_JTI.clear()
    ext._RATE_BUCKETS.clear()


@pytest.fixture
def dev_auth(monkeypatch, _clean_env):
    # Explicit dependency on _clean_env guarantees setup ORDER: clean first,
    # then set — otherwise autouse-vs-requested instantiation order can wipe
    # these variables between setup and the request under test.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PROPWIRE_ALLOW_DEV_AUTH_BYPASS", "1")


@pytest.fixture
def prod_signing(monkeypatch, _clean_env):
    """Production-style signing: explicit secret, APP_ENV untouched."""
    monkeypatch.setenv("EXTENSION_SESSION_SECRET", "test-secret-0123456789")


def _sign_in(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/extension/session",
        headers={"Authorization": "Bearer dev-bypass"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(data: dict) -> dict:
    return {"Authorization": f"Bearer {data['token']}"}


# ---------------------------------------------------------------------------
# Health / kill switch
# ---------------------------------------------------------------------------


def test_health_reports_ok_by_default(client):
    r = client.get("/api/v1/extension/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["killSwitch"] is False
    assert body["minExtensionVersion"] == "0.1.0"
    assert body["sessionTtlSeconds"] == DEFAULT_SESSION_TTL_SECONDS


def test_kill_switch_fails_everything_closed(client, monkeypatch, dev_auth):
    # Obtain a session BEFORE flipping the switch, then verify the switch
    # fails every protected route closed (with AND without a token).
    data = _sign_in(client)
    monkeypatch.setenv("EXTENSION_KILL_SWITCH", "1")
    health = client.get("/api/v1/extension/health").json()
    assert health["ok"] is False
    assert health["killSwitch"] is True
    # Session issuance and protected routes fail CLOSED under the switch.
    assert client.post("/api/v1/extension/session").status_code == 503
    assert client.get("/api/v1/markets/model-coverage", headers=_bearer(data)).status_code == 503


# ---------------------------------------------------------------------------
# Session issuance — entitlement is server-side, fail closed
# ---------------------------------------------------------------------------


def test_session_fails_closed_without_entitlement_config(client):
    # No WHOP_API_KEY, no dev bypass → 503, never a free session.
    assert client.post("/api/v1/extension/session").status_code == 503


def test_production_signing_fails_closed_without_secret(client, monkeypatch):
    # APP_ENV defaults to production and no signing secret is configured:
    # even a verified membership must not yield a session (fail closed).
    monkeypatch.setenv("WHOP_API_KEY", "k-test")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "mem_123", "status": "active"}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    r = client.post("/api/v1/extension/session", headers={"Authorization": "Bearer mem_123"})
    assert r.status_code == 503


def test_session_issued_after_dev_bypass(client, dev_auth):
    data = _sign_in(client)
    assert data["tier"] == "pro"
    assert data["token_type"] == "pste-ext-v1"
    assert len(data["token"].split(".")) == 3
    # ~15 minute expiry by default.
    ttl = time.mktime(time.strptime(data["expires_at"][:19], "%Y-%m-%dT%H:%M:%S")) - time.mktime(
        time.strptime(data["issued_at"][:19], "%Y-%m-%dT%H:%M:%S")
    )
    assert 890 <= ttl <= 910


def test_session_missing_bearer_with_whop_key(client, monkeypatch):
    monkeypatch.setenv("WHOP_API_KEY", "k-test")
    assert client.post("/api/v1/extension/session").status_code == 401


def test_session_whop_active_membership(client, monkeypatch, prod_signing):
    monkeypatch.setenv("WHOP_API_KEY", "k-test")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "mem_123", "status": "active"}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    r = client.post("/api/v1/extension/session", headers={"Authorization": "Bearer mem_123"})
    assert r.status_code == 200, r.text
    assert r.json()["principal"] == "mem_123"


def test_session_whop_canceled_membership_rejected(client, monkeypatch, prod_signing):
    monkeypatch.setenv("WHOP_API_KEY", "k-test")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "mem_123", "status": "canceled"}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    r = client.post("/api/v1/extension/session", headers={"Authorization": "Bearer mem_123"})
    assert r.status_code == 403


def test_session_whop_lookup_failure_rejected(client, monkeypatch, prod_signing):
    monkeypatch.setenv("WHOP_API_KEY", "k-test")

    class FakeResponse:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    r = client.post("/api/v1/extension/session", headers={"Authorization": "Bearer mem_missing"})
    assert r.status_code == 401


def test_session_rate_limited_per_principal(client, dev_auth):
    for _ in range(10):
        assert client.post("/api/v1/extension/session").status_code == 200
    assert client.post("/api/v1/extension/session").status_code == 429


# ---------------------------------------------------------------------------
# Scoped token verification — tamper / expiry / plan / revocation
# ---------------------------------------------------------------------------


def test_market_routes_require_scoped_token(client, dev_auth):
    assert client.get("/api/v1/markets/model-coverage").status_code == 401
    r = client.post(
        "/api/v1/markets/evaluate",
        json={"source": "demobook", "marketType": "drive_reception_1plus", "driveId": "d4"},
    )
    assert r.status_code == 401


def test_tampered_signature_rejected(client, dev_auth):
    data = _sign_in(client)
    h, p, sig = data["token"].split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    with pytest.raises(Exception):
        verify_session_token(f"{h}.{p}.{flipped}")
    r = client.get(
        "/api/v1/markets/model-coverage",
        headers={"Authorization": f"Bearer {h}.{p}.{flipped}"},
    )
    assert r.status_code == 401


def test_expired_token_rejected(client, dev_auth):
    token, _payload = issue_session_token("mem_x", ttl_seconds=1)
    time.sleep(1.2)
    r = client.get("/api/v1/markets/model-coverage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_plan_token_rejected(client, dev_auth):
    import base64
    import hashlib
    import hmac as hmac_mod
    import json

    secret = ext._session_secret()
    now = int(time.time())
    header = ext._b64url(json.dumps({"alg": "HS256", "typ": "pste-ext-v1"}).encode())
    payload = ext._b64url(
        json.dumps({"sub": "mem_x", "plan": "free", "iat": now, "exp": now + 600, "jti": "j1"}).encode()
    )
    sig = ext._b64url(hmac_mod.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    r = client.get(
        "/api/v1/markets/model-coverage",
        headers={"Authorization": f"Bearer {header}.{payload}.{sig}"},
    )
    assert r.status_code == 403
    _ = (base64, hmac_mod)


def test_revoked_token_rejected(client, dev_auth):
    data = _sign_in(client)
    # Revoke via the endpoint (authenticated by the token being revoked).
    r = client.post("/api/v1/extension/session/revoke", headers=_bearer(data))
    assert r.status_code == 200
    assert r.json()["revoked"] is True
    # The same token no longer unlocks the market surface.
    assert client.get("/api/v1/markets/model-coverage", headers=_bearer(data)).status_code == 401


# ---------------------------------------------------------------------------
# Model coverage + evaluation — the honesty contract
# ---------------------------------------------------------------------------


def test_model_coverage_returns_synthetic_roster(client, dev_auth):
    data = _sign_in(client)
    r = client.get("/api/v1/markets/model-coverage", headers=_bearer(data))
    assert r.status_code == 200
    body = r.json()
    players = {entry["playerName"] for entry in body["roster"]}
    assert players == {"Travis Kelce", "Rashee Rice", "Hunter Henry", "Juwan Johnson"}
    assert body["coverage"][0]["confidence"] == "uncalibrated"
    assert body["coverage"][0]["provenance"] == "SYNTHETIC_DEMO_PARAMETERS"


def test_evaluate_demobook_kelce_matches_spec_example(client, dev_auth):
    data = _sign_in(client)
    r = client.post(
        "/api/v1/markets/evaluate",
        headers=_bearer(data),
        json={
            "source": "demobook",
            "eventId": "2026_09_NE_KC",
            "playerId": "nfl_travis_kelce",
            "playerName": "Travis Kelce",
            "marketType": "drive_reception_1plus",
            "selection": "YES",
            "americanOdds": 160,
            "driveId": "d4",
        },
    )
    assert r.status_code == 200
    model = r.json()["model"]
    assert model["modelVersion"] == "DRIVE-REC-V1"
    assert model["confidence"] == "uncalibrated"
    # q=0.1841, N=8, s=0.72 → P=0.4399 (the spec worked example: P=44%).
    assert model["probability"] == pytest.approx(0.4399178427, abs=1e-6)
    lo, hi = model["probabilityInterval"]
    assert lo < model["probability"] < hi


def test_evaluate_real_book_source_is_no_coverage(client, dev_auth):
    data = _sign_in(client)
    r = client.post(
        "/api/v1/markets/evaluate",
        headers=_bearer(data),
        json={
            "source": "draftkings",
            "playerId": "nfl_travis_kelce",
            "marketType": "drive_reception_1plus",
            "americanOdds": 160,
            "driveId": "d4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] is None
    assert body["status"] == "NO_COVERAGE"
    assert "no drive-level model coverage" in body["reasons"][0]


def test_evaluate_real_book_alias_is_no_coverage(client, dev_auth):
    data = _sign_in(client)
    for source in ("fanduel", "polymarket", "bovada"):
        r = client.post(
            "/api/v1/markets/evaluate",
            headers=_bearer(data),
            json={"source": source, "marketType": "drive_reception_1plus", "driveId": "d4"},
        )
        assert r.json()["status"] == "NO_COVERAGE"


def test_evaluate_non_drive_market_is_no_coverage(client, dev_auth):
    data = _sign_in(client)
    r = client.post(
        "/api/v1/markets/evaluate",
        headers=_bearer(data),
        json={"source": "demobook", "marketType": "receptions_over", "americanOdds": -110, "line": 5.5},
    )
    assert r.json()["status"] == "NO_COVERAGE"


def test_evaluate_drive_market_without_drive_binding_is_no_coverage(client, dev_auth):
    data = _sign_in(client)
    r = client.post(
        "/api/v1/markets/evaluate",
        headers=_bearer(data),
        json={"source": "demobook", "marketType": "drive_reception_1plus", "playerId": "nfl_travis_kelce"},
    )
    assert r.json()["status"] == "NO_COVERAGE"


def test_evaluate_unknown_player_is_no_coverage(client, dev_auth):
    data = _sign_in(client)
    r = client.post(
        "/api/v1/markets/evaluate",
        headers=_bearer(data),
        json={"source": "demobook", "marketType": "drive_reception_1plus", "playerName": "Nobody Here", "driveId": "d4"},
    )
    assert r.json()["status"] == "NO_COVERAGE"


def test_drive_survival_formula_matches_extension_numerics():
    # Cross-check against the TypeScript implementation values
    # (extensions/packages/core/src/drive-reception-model.ts).
    assert drive_survival_adjusted(0.1841, 8, 0.72) == pytest.approx(0.4399178427, abs=1e-9)
    assert drive_survival_adjusted(0.2276, 8, 0.72) == pytest.approx(0.5080689259, abs=1e-9)
    assert drive_survival_adjusted(0.105, 8, 0.72) == pytest.approx(0.2864960498, abs=1e-9)
    assert drive_survival_adjusted(0.091, 8, 0.72) == pytest.approx(0.2545049157, abs=1e-9)


# ---------------------------------------------------------------------------
# Additive include in api/main.py
# ---------------------------------------------------------------------------


def test_router_is_mounted_on_main_app():
    from api.main import app as main_app

    with TestClient(main_app) as main_client:
        r = main_client.get("/api/v1/extension/health")
        assert r.status_code == 200
        assert r.json()["service"] == "propstein-extension-api"
