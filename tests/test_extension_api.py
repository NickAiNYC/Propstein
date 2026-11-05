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
    "ALLOW_INSECURE_DEV_TOKENS",
    "EXTENSION_SESSION_STORE",
    "EXTENSION_SESSION_VERSION",
    "REDIS_URL",
    "WEB_CONCURRENCY",
    "UVICORN_WORKERS",
    "GUNICORN_WORKERS",
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
    ext._INSECURE_DEV_WARNED = False
    ext.use_memory_store()
    ext._REVOKED_JTI.clear()
    ext._RATE_BUCKETS.clear()
    ext._SESSION_VERSIONS.clear()
    yield
    ext.use_memory_store()
    ext._REVOKED_JTI.clear()
    ext._RATE_BUCKETS.clear()
    ext._SESSION_VERSIONS.clear()


@pytest.fixture
def dev_auth(monkeypatch, _clean_env):
    # Explicit dependency on _clean_env guarantees setup ORDER: clean first,
    # then set — otherwise autouse-vs-requested instantiation order can wipe
    # these variables between setup and the request under test.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PROPWIRE_ALLOW_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("ALLOW_INSECURE_DEV_TOKENS", "1")


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


class _FakeRedis:
    """Enough of the Redis client for the session store's eval/get/set calls."""

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def ping(self):
        return True

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = str(value)
        return True

    def eval(self, script, numkeys, key, now, window, limit, member):
        now = float(now)
        window = float(window)
        limit = int(limit)
        zset = self.zsets.setdefault(key, {})
        expired = [item for item, score in zset.items() if score <= now - window]
        for item in expired:
            del zset[item]
        if len(zset) >= limit:
            return [0, len(zset)]
        zset[member] = now
        return [1, len(zset)]


def test_startup_refuses_without_secret_or_opt_in(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EXTENSION_SESSION_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_DEV_TOKENS", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        ext.enforce_runtime_security()


def test_startup_ignores_insecure_flag_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EXTENSION_SESSION_SECRET", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_DEV_TOKENS", "1")
    assert ext._session_secret() is None
    with pytest.raises(RuntimeError, match="Refusing to start"):
        ext.enforce_runtime_security()


def test_dev_without_opt_in_refuses_to_start(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("EXTENSION_SESSION_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_DEV_TOKENS", raising=False)
    assert ext._session_secret() is None
    with pytest.raises(RuntimeError, match="Refusing to start"):
        ext.enforce_runtime_security()


def test_dev_opt_in_uses_builtin_secret_and_warns(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("EXTENSION_SESSION_SECRET", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_DEV_TOKENS", "1")
    ext._INSECURE_DEV_WARNED = False
    assert ext._session_secret() == ext._DEV_SESSION_SECRET
    assert "ALLOW_INSECURE_DEV_TOKENS=1" in capsys.readouterr().err
    ext.enforce_runtime_security()


def test_production_multi_worker_memory_store_refuses(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXTENSION_SESSION_SECRET", "real-session-secret")
    monkeypatch.setenv("EXTENSION_SESSION_STORE", "memory")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError, match="in-memory"):
        ext.enforce_runtime_security()


def test_production_multi_worker_redis_store_starts(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXTENSION_SESSION_SECRET", "real-session-secret")
    monkeypatch.setenv("EXTENSION_SESSION_STORE", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://session-store.internal:6379/0")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    fake = _FakeRedis()
    monkeypatch.setattr("api.session_store.connect_redis", lambda url: fake)
    ext.enforce_runtime_security()
    token, payload = issue_session_token("mem_1", 600)
    ext.get_store().revoke(payload["jti"], payload["exp"])
    with pytest.raises(HTTPException) as caught:
        verify_session_token(token)
    assert caught.value.status_code == 401


def test_redis_store_rate_limit_matches_memory_window():
    from api.session_store import RATE_LIMIT_LUA, RedisSessionStore

    assert "ZREMRANGEBYSCORE" in RATE_LIMIT_LUA
    assert "count >= limit" in RATE_LIMIT_LUA
    store = RedisSessionStore(_FakeRedis())
    now = time.time()
    for _ in range(10):
        assert store.check_and_record("principal", now, 60, 10) is True
    assert store.check_and_record("principal", now, 60, 10) is False


def test_session_version_claim_rejects_stale_token(client, dev_auth):
    data = _sign_in(client)
    ext.get_store().set_session_version("dev-bypass", 2)
    assert client.get("/api/v1/markets/model-coverage", headers=_bearer(data)).status_code == 401
    fresh = _sign_in(client)
    assert client.get("/api/v1/markets/model-coverage", headers=_bearer(fresh)).status_code == 200


def test_extension_session_version_env_invalidates_tokens(client, dev_auth, monkeypatch):
    data = _sign_in(client)
    monkeypatch.setenv("EXTENSION_SESSION_VERSION", "2")
    assert client.get("/api/v1/markets/model-coverage", headers=_bearer(data)).status_code == 401


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


def test_router_is_mounted_on_main_app(monkeypatch):
    # _clean_env removes the suite signing secret; startup now refuses without one.
    monkeypatch.setenv("EXTENSION_SESSION_SECRET", "test-secret-0123456789")
    from api.main import app as main_app

    with TestClient(main_app) as main_client:
        r = main_client.get("/api/v1/extension/health")
        assert r.status_code == 200
        assert r.json()["service"] == "propstein-extension-api"


def test_extension_placements_and_telemetry_routes(client, monkeypatch):
    # 1. Placement route with unknown forged signal fails closed (400)
    forged_payload = {
        "audit_id": "audit-forged-1",
        "signal_id": "sig-uncommitted-forged-id-9999",
        "market_key": "unknown:pts:20.5",
        "user_reported_price": -110,
        "user_reported_line": 20.5,
        "book": "draftkings",
        "achieved_at": "2026-11-04T18:00:00Z",
    }
    resp_bad = client.post("/api/v1/extension/placements", json=forged_payload)
    assert resp_bad.status_code == 400
    assert resp_bad.json()["detail"]["error"] == "SIGNAL_NOT_IN_LEDGER"

    # 2. Placement route with committed forecast in feed succeeds (200)
    valid_placement_payload = {
        "audit_id": "audit-valid-1234",
        "signal_id": "syn_a_ne_chi_player_a_yds_open",
        "market_key": "player_a:receiving_yards:34.5",
        "user_reported_price": -110,
        "user_reported_line": 34.5,
        "book": "Synthetic Book A",
        "model_fair_line": 43.5,
        "achieved_at": "2026-11-04T18:00:00Z",
        "client_observed_latency_ms": 142,
    }
    resp = client.post("/api/v1/extension/placements", json=valid_placement_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["audit_id"] == "audit-valid-1234"
    assert data["status"] == "RECORDED"

    # 3. Placement route with test bypass flag succeeds for synthetic testing
    monkeypatch.setenv("PROPSTEIN_TEST_ALLOW_MOCK_SIGNALS", "1")
    resp_bypass = client.post("/api/v1/extension/placements", json=forged_payload)
    assert resp_bypass.status_code == 200
    assert resp_bypass.json()["ok"] is True

    # 4. Telemetry batch route
    telemetry_payload = {
        "events": [
            {
                "book": "draftkings",
                "outcome": "MATCHED",
                "details": "player_last_name + market_scope + line_bucket",
                "client_latency_ms": 85,
                "timestamp": "2026-11-04T18:01:00Z",
            },
            {
                "book": "fanduel",
                "outcome": "AMBIGUOUS",
                "details": "multiple players share surname on active slate",
                "client_latency_ms": 110,
                "timestamp": "2026-11-04T18:01:05Z",
            },
        ]
    }
    resp_telem = client.post("/api/v1/extension/telemetry", json=telemetry_payload)
    assert resp_telem.status_code == 200
    assert resp_telem.json()["ok"] is True
    assert resp_telem.json()["count"] == 2


def test_match_telemetry_evaluation_metrics():
    from src.match_telemetry_eval import evaluate_match_telemetry

    # 1. Empty telemetry stream
    empty_summary = evaluate_match_telemetry([])
    assert empty_summary.total_attempts == 0
    assert empty_summary.matched_count == 0
    assert empty_summary.match_success_rate == 0.0
    assert empty_summary.drift_alarm is False

    # 2. Synthetic telemetry stream with multiple books, ambiguous matches, and extraction discrepancy
    events = [
        # Book A: 3 attempts, 2 MATCHED, 1 AMBIGUOUS -> 66.7% match rate (<70% default threshold, drift alarm)
        {"book": "draftkings", "outcome": "MATCHED", "details": "player:mahomes:pass_yds:275.5"},
        {"book": "draftkings", "outcome": "MATCHED", "details": "player:kelce:rec_yds:65.5 [discrepancy noted]"},
        {"book": "draftkings", "outcome": "AMBIGUOUS", "details": "player:smith:multi_name"},
        # Book B: 2 attempts, 2 MATCHED -> 100% match rate
        {"book": "fanduel", "outcome": "MATCHED", "details": "player:mahomes:pass_yds:275.5"},
        {"book": "fanduel", "outcome": "MATCHED", "details": "player:kelce:rec_yds:65.5"},
    ]

    summary = evaluate_match_telemetry(events, min_book_match_rate_threshold=0.70)
    assert summary.total_attempts == 5
    assert summary.matched_count == 4
    assert summary.match_success_rate == round(4 / 5, 4)
    assert summary.outcome_counts == {"MATCHED": 4, "AMBIGUOUS": 1}
    assert summary.per_book_match_rate["draftkings"] == round(2 / 3, 4)
    assert summary.per_book_match_rate["fanduel"] == 1.0
    # 1 out of 4 MATCHED had "discrepancy" in details
    assert summary.extraction_error_rate == 0.25
    # Cross book consistency: 3 markets ("player:mahomes:pass_yds:275.5" has {MATCHED}, "player:kelce:rec_yds:65.5 [discrepancy noted]" has {MATCHED}, "player:smith:multi_name" has {AMBIGUOUS}, "player:kelce:rec_yds:65.5" has {MATCHED})
    assert 0.0 <= summary.cross_book_consistency_rate <= 1.0
    # Drift alarm triggered on draftkings (66.7% < 70%)
    assert summary.drift_alarm is True
    assert any("draftkings" in reason for reason in summary.drift_reasons)

    # Check dict conversion
    d = summary.as_dict()
    assert d["total_attempts"] == 5
    assert d["drift_alarm"] is True

