"""
Billing Endpoint Security Regression Tests (P2, v175)
====================================================
POST /api/billing/create-checkout-session (and the portal sibling) must:

1. Reject unauthenticated callers with 401 BEFORE any Stripe API call.
2. Derive the billing user_id SERVER-SIDE from the authenticated session
   token — request-body user_id is ignored (no cross-user session minting).
3. Return the Stripe (or simulated) checkout URL for authenticated callers.
4. Rate-limit session creation to 3 requests/min per principal+IP (429).
5. Fail closed (401) on foreign tokens when a server key is configured.
6. Clamp client-supplied success/cancel/return URLs to the app origin.
"""

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import api.main as api_main
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_billing_rate_limit():
    """Isolate the process-local sliding-window limiter between tests."""
    api_main._billing_rate_buckets.clear()
    yield
    api_main._billing_rate_buckets.clear()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Deterministic auth + redirect-clamp environment for every test."""
    for var in ("PROPSTEIN_API_KEY", "PROPWIRE_API_KEY", "APP_URL", "STRIPE_SECRET_KEY", "PROPSTEIN_PAID_SIGNUPS_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    # Existing authentication tests exercise the checkout path with the
    # operator gate explicitly open. Production defaults to frozen.
    monkeypatch.setenv("PROPSTEIN_PAID_SIGNUPS_ENABLED", "1")


def test_paid_signups_frozen_by_default_even_for_authenticated_user(client, monkeypatch):
    monkeypatch.delenv("PROPSTEIN_PAID_SIGNUPS_ENABLED", raising=False)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("BillingService was invoked while paid signups are frozen")

    monkeypatch.setattr("src.services.billing.BillingService", _must_not_be_called)
    res = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly"},
        headers={"X-PropStein-API-Key": "authenticated_research_user"},
    )
    assert res.status_code == 503
    assert "frozen" in res.json()["detail"].lower()


def _install_fake_billing(monkeypatch, recorded):
    """Replace BillingService with a recorder; stub the sniper engine."""

    class FakeBillingService:
        def __init__(self, truth_store=None):
            pass

        def create_checkout_session(self, *, user_id, email=None, plan="pro_monthly",
                                    success_url=None, cancel_url=None):
            recorded.update(
                user_id=user_id, email=email, plan=plan,
                success_url=success_url, cancel_url=cancel_url,
            )
            return {
                "checkout_url": "https://checkout.stripe.com/pay/cs_test_123",
                "session_id": "cs_test_123",
                "plan": plan,
            }

    monkeypatch.setattr("src.services.billing.BillingService", FakeBillingService)
    monkeypatch.setattr(api_main, "get_sniper_engine", lambda: SimpleNamespace(truth=None))


def test_checkout_session_unauthenticated_returns_401(client, monkeypatch):
    """No session token -> 401, and BillingService must never be reached."""
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("BillingService was invoked by an unauthenticated request")

    monkeypatch.setattr("src.services.billing.BillingService", _must_not_be_called)

    res = client.post("/api/billing/create-checkout-session", json={"plan": "pro_monthly"})
    assert res.status_code == 401
    assert "authentication" in res.json()["detail"].lower()

    # Same contract via the Authorization header left empty and body-only identity.
    res2 = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly", "user_id": "usr_somebody"},
        headers={"Authorization": "Bearer "},
    )
    assert res2.status_code == 401


def test_checkout_session_authenticated_returns_stripe_url(client, monkeypatch):
    """Valid session token -> 200 + Stripe checkout URL; identity is server-side."""
    recorded = {}
    _install_fake_billing(monkeypatch, recorded)

    res = client.post(
        "/api/billing/create-checkout-session",
        json={
            "plan": "pro_monthly",
            "user_id": "victim_user",  # must be IGNORED — impersonation attempt
            "email": "buyer@example.com",
            "success_url": "https://evil.example.com/phish",
            "cancel_url": "/?checkout=cancelled",
        },
        headers={"X-PropStein-API-Key": "test_session_token_123456"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["checkout_url"].startswith("https://checkout.stripe.com/pay/")
    assert body["plan"] == "pro_monthly"

    # user_id derived from the TOKEN, not the payload (token < 48 chars: kept verbatim).
    assert recorded["user_id"] == "test_session_token_123456"
    assert recorded["user_id"] != "victim_user"
    assert recorded["email"] == "buyer@example.com"

    # Foreign-origin redirect target discarded; relative path clamped to app origin.
    assert recorded["success_url"] is None
    assert recorded["cancel_url"] == "https://propstein.vercel.app/?checkout=cancelled"


def test_checkout_session_rate_limited_after_three_requests(client, monkeypatch):
    """Sliding window: 3 allowed per principal+IP, 4th within a minute -> 429."""
    recorded = {}
    _install_fake_billing(monkeypatch, recorded)

    headers = {"X-PropStein-API-Key": "rate_limit_test_token"}
    statuses = [
        client.post("/api/billing/create-checkout-session", json={"plan": "pro_monthly"}, headers=headers).status_code
        for _ in range(4)
    ]
    assert statuses == [200, 200, 200, 429]
    assert "rate limit" in client.post(
        "/api/billing/create-checkout-session", json={"plan": "pro_monthly"}, headers=headers
    ).json()["detail"].lower()


def test_checkout_session_invalid_token_fails_closed_when_server_key_set(client, monkeypatch):
    """With PROPSTEIN_API_KEY configured, any foreign token is rejected 401."""
    monkeypatch.setenv("PROPSTEIN_API_KEY", "server_managed_key_do_not_share")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("BillingService was invoked with a foreign token")

    monkeypatch.setattr("src.services.billing.BillingService", _must_not_be_called)

    res = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly"},
        headers={"X-PropStein-API-Key": "not_the_server_key"},
    )
    assert res.status_code == 401
    assert "invalid session token" in res.json()["detail"].lower()

    # The matching server key still passes (auth only — Stripe call mocked away).
    recorded = {}
    _install_fake_billing(monkeypatch, recorded)
    res_ok = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly"},
        headers={"X-PropStein-API-Key": "server_managed_key_do_not_share"},
    )
    assert res_ok.status_code == 200


@pytest.mark.parametrize("method,path", [
    ("get", "/api/sniper/webhooks"),
    ("post", "/api/sniper/webhooks"),
    ("post", "/api/sniper/webhooks/test"),
    ("post", "/api/sniper/polymarket-ws-state"),
    ("post", "/api/sniper/simulate-substitution"),
    ("post", "/api/sniper/feed-stale"),
    ("post", "/api/sniper/simulate-scratch"),
    ("post", "/api/sniper/explain"),
    ("get", "/api/sniper/history?private_only=true"),
])
def test_private_sniper_routes_reject_missing_or_foreign_key(client, monkeypatch, method, path):
    monkeypatch.setenv("PROPSTEIN_API_KEY", "server_managed_key_do_not_share")
    monkeypatch.delenv("PROPWIRE_API_KEY", raising=False)
    monkeypatch.setattr(api_main, "get_sniper_engine", lambda: (_ for _ in ()).throw(
        AssertionError("private route reached engine before authentication")))
    call = getattr(client, method)
    assert call(path).status_code == 401
    assert call(path, headers={"X-PropStein-API-Key": "foreign"}).status_code == 401
    assert call(path, headers={"X-PropStein-API-Key": "pw_quant_live_key"}).status_code == 401


def test_private_history_fails_closed_when_no_key_configured(client):
    assert client.get("/api/sniper/history?user_id=someone",
                      headers={"X-PropStein-API-Key": "anything"}).status_code == 401


def test_legacy_literal_key_never_unlocks_pro(monkeypatch):
    from src.services.billing import BillingService

    service = BillingService.__new__(BillingService)
    service.whop_api_key = None
    assert service.check_user_entitlement(api_key="pw_quant_live_key")["is_pro"] is False
    monkeypatch.setenv("PROPSTEIN_API_KEY", "new-secret-key")
    assert service.check_user_entitlement(api_key="pw_quant_live_key")["is_pro"] is False
    assert service.check_user_entitlement(api_key="new-secret-key")["is_pro"] is True


def test_checkout_session_long_token_derives_hashed_principal(client, monkeypatch):
    """Long tokens hash to a stable sanitized principal (clv/log scoping rule)."""
    recorded = {}
    _install_fake_billing(monkeypatch, recorded)

    long_token = "x" * 64
    res = client.post(
        "/api/billing/create-checkout-session",
        json={"plan": "pro_monthly"},
        headers={"Authorization": f"Bearer {long_token}"},
    )
    assert res.status_code == 200
    import hashlib
    assert recorded["user_id"] == hashlib.sha256(long_token.encode()).hexdigest()[:16]


def test_portal_session_unauthenticated_returns_401(client, monkeypatch):
    """Portal endpoint shares the same guard class: anonymous -> 401 first."""
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("BillingService was invoked by an unauthenticated portal request")

    monkeypatch.setattr("src.services.billing.BillingService", _must_not_be_called)

    res = client.post("/api/billing/create-portal-session", json={"customer_id": "cus_123"})
    assert res.status_code == 401
