"""
PropWire Monetization Engine: Stripe & Whop Subscription Integration
====================================================================

Manages:
- $29/mo Sniper PRO (and $290/yr) Stripe Checkout Sessions
- Stripe Customer Portal for self-serve management/cancellation
- Idempotent Stripe webhook handling (HMAC-SHA256 signature verification)
- Whop entitlement fallback so existing memberships continue working
- Tier gating resolution (Free Observer vs Sniper PRO)
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
import urllib.request
import urllib.error

from src.agents.persistence import TruthStore

logger = logging.getLogger("propwire.billing")

STRIPE_API_BASE = "https://api.stripe.com/v1"
DEFAULT_PRO_MONTHLY_CENTS = 2900  # $29.00
DEFAULT_PRO_YEARLY_CENTS = 29000  # $290.00

# Mapping existing frozen plan IDs to clean institutional display names
PLAN_DISPLAY_NAMES: dict[str, str] = {
    "sniper_pro_monthly": "Quant PRO (Monthly)",
    "sniper_pro_yearly": "Quant PRO (Yearly)",
    "pro_monthly": "Quant PRO (Monthly)",
    "pro_yearly": "Quant PRO (Yearly)",
    "quant_api": "Quant API (Institutional)",
    "free_observer": "Free Observer",
}


def _stripe_request(endpoint: str, data: dict[str, Any], secret_key: str) -> dict[str, Any]:
    url = f"{STRIPE_API_BASE}/{endpoint.lstrip('/')}"
    encoded = urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_stripe_webhook_signature(
    payload_bytes: bytes,
    sig_header: str | None,
    webhook_secret: str,
    *,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verify Stripe webhook signature (t=timestamp,v1=signature) using standard library HMAC-SHA256.
    """
    if not sig_header or not webhook_secret:
        return False

    parts: dict[str, str] = {}
    for item in sig_header.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            parts[k] = v

    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False

    try:
        t_int = int(timestamp)
        now_int = int(time.time())
        if abs(now_int - t_int) > tolerance_seconds and tolerance_seconds > 0:
            logger.warning("Stripe webhook timestamp older than tolerance (%d vs %d)", t_int, now_int)
            return False
    except ValueError:
        return False

    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    computed = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


class BillingService:
    def __init__(self, truth_store: TruthStore | None = None):
        self.truth = truth_store or TruthStore()
        self.stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        self.stripe_webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        self.whop_api_key = os.environ.get("WHOP_API_KEY", "").strip()

    def create_checkout_session(
        self,
        *,
        user_id: str,
        email: str | None = None,
        plan: str = "pro_monthly",
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Creates a Stripe Checkout Session for $29/mo (or $290/yr).
        Falls back to a simulated session URL if STRIPE_SECRET_KEY is unset in development.
        """
        base_url = os.environ.get("APP_URL", "https://propstein.vercel.app").rstrip("/")
        succ_url = success_url or f"{base_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
        canc_url = cancel_url or f"{base_url}/?checkout=cancelled"

        is_yearly = plan == "pro_yearly"
        unit_amount = DEFAULT_PRO_YEARLY_CENTS if is_yearly else DEFAULT_PRO_MONTHLY_CENTS
        interval = "year" if is_yearly else "month"
        prod_name = "PropWire Sniper PRO (Yearly)" if is_yearly else "PropWire Sniper PRO ($29/mo)"

        if not self.stripe_secret_key:
            # Fallback simulated session for demo / testing without Stripe credentials
            simulated_id = f"cs_test_mock_{user_id}_{int(time.time())}"
            return {
                "checkout_url": f"{base_url}/?session_id={simulated_id}&user_id={user_id}&tier=pro",
                "session_id": simulated_id,
                "plan": plan,
                "mode": "simulated",
            }

        price_id = os.environ.get(f"STRIPE_PRICE_ID_{interval.upper()}")
        form_data: dict[str, Any] = {
            "mode": "subscription",
            "success_url": succ_url,
            "cancel_url": canc_url,
            "client_reference_id": user_id,
            "metadata[user_id]": user_id,
            "metadata[plan]": plan,
        }
        if email:
            form_data["customer_email"] = email

        if price_id:
            form_data["line_items[0][price]"] = price_id
            form_data["line_items[0][quantity]"] = "1"
        else:
            form_data["line_items[0][price_data][currency]"] = "usd"
            form_data["line_items[0][price_data][product_data][name]"] = prod_name
            form_data["line_items[0][price_data][unit_amount]"] = str(unit_amount)
            form_data["line_items[0][price_data][recurring][interval]"] = interval
            form_data["line_items[0][quantity]"] = "1"

        resp = _stripe_request("checkout/sessions", form_data, self.stripe_secret_key)
        return {
            "checkout_url": resp.get("url"),
            "session_id": resp.get("id"),
            "plan": plan,
            "mode": "live",
        }

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        base_url = os.environ.get("APP_URL", "https://propstein.vercel.app").rstrip("/")
        ret_url = return_url or f"{base_url}/"

        if not self.stripe_secret_key:
            return {"portal_url": f"{base_url}/?portal=demo&customer_id={customer_id}"}

        form_data = {
            "customer": customer_id,
            "return_url": ret_url,
        }
        resp = _stripe_request("billing_portal/sessions", form_data, self.stripe_secret_key)
        return {"portal_url": resp.get("url")}

    def process_webhook_event(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Idempotent event processor for Stripe webhooks.
        """
        event_type = event.get("type", "")
        data_obj = event.get("data", {}).get("object", {})

        now_iso = datetime.now(timezone.utc).isoformat()
        processed = False
        action = "ignored"

        if event_type == "checkout.session.completed":
            user_id = data_obj.get("client_reference_id") or data_obj.get("metadata", {}).get("user_id") or "anon"
            sub_id = data_obj.get("subscription") or data_obj.get("id")
            cust_id = data_obj.get("customer") or f"cus_{user_id}"
            plan = data_obj.get("metadata", {}).get("plan", "pro_monthly")

            self.truth.upsert_user_subscription({
                "subscription_id": sub_id,
                "user_id": user_id,
                "customer_id": cust_id,
                "provider": "stripe",
                "plan": plan,
                "status": "active",
                "current_period_end": now_iso,
                "created_at": now_iso,
                "updated_at": now_iso,
            })
            processed = True
            action = f"activated subscription {sub_id} for user {user_id}"

        elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
            sub_id = data_obj.get("id")
            cust_id = data_obj.get("customer") or ""
            status = data_obj.get("status", "active")
            period_end_ts = data_obj.get("current_period_end")
            period_end_iso = datetime.fromtimestamp(period_end_ts, timezone.utc).isoformat() if period_end_ts else now_iso

            existing = self.truth.get_subscription_by_customer_id(cust_id)
            user_id = existing.get("user_id", cust_id) if existing else cust_id
            plan = data_obj.get("metadata", {}).get("plan") or (existing.get("plan") if existing else "pro_monthly")

            self.truth.upsert_user_subscription({
                "subscription_id": sub_id,
                "user_id": user_id,
                "customer_id": cust_id,
                "provider": "stripe",
                "plan": plan,
                "status": status,
                "current_period_end": period_end_iso,
                "cancel_at_period_end": 1 if data_obj.get("cancel_at_period_end") else 0,
                "created_at": now_iso,
                "updated_at": now_iso,
            })
            processed = True
            action = f"updated subscription {sub_id} status={status}"

        elif event_type == "customer.subscription.deleted":
            sub_id = data_obj.get("id")
            cust_id = data_obj.get("customer") or ""
            existing = self.truth.get_subscription_by_customer_id(cust_id)
            if existing:
                existing["status"] = "canceled"
                existing["updated_at"] = now_iso
                self.truth.upsert_user_subscription(existing)
            processed = True
            action = f"canceled subscription {sub_id}"

        elif event_type == "invoice.payment_failed":
            cust_id = data_obj.get("customer") or ""
            existing = self.truth.get_subscription_by_customer_id(cust_id)
            if existing:
                existing["status"] = "past_due"
                existing["updated_at"] = now_iso
                self.truth.upsert_user_subscription(existing)
            processed = True
            action = f"marked invoice past_due for customer {cust_id}"

        return {
            "processed": processed,
            "event_type": event_type,
            "action": action,
        }

    def check_user_entitlement(
        self,
        *,
        user_id: str | None = None,
        bearer_token: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Check whether user has active PRO tier access.
        Priority:
          1. Master API key bypass (`PROPWIRE_API_KEY`)
          2. Explicit local development bypass (`PROPWIRE_ALLOW_DEV_AUTH_BYPASS == '1'`)
          3. Stripe subscription check in `TruthStore` (`user_subscriptions`)
          4. Whop membership check (if bearer_token or Whop key is present)
        """
        expected_key = os.environ.get("PROPSTEIN_API_KEY") or os.environ.get("PROPWIRE_API_KEY")
        if expected_key and api_key and hmac.compare_digest(api_key, expected_key):
            return {
                "is_pro": True,
                "tier": "pro",
                "provider": "api_key",
                "plan": "quant_api",
                "display_name": PLAN_DISPLAY_NAMES.get("quant_api", "Quant PRO"),
                "user_id": user_id or "quant_api_user",
            }

        dev_bypass = os.environ.get("PROPWIRE_ALLOW_DEV_AUTH_BYPASS") == "1"
        is_prod = os.environ.get("APP_ENV", "production").lower() == "production"
        if not is_prod and dev_bypass:
            return {
                "is_pro": True,
                "tier": "pro",
                "provider": "dev_bypass",
                "plan": "pro_monthly",
                "display_name": PLAN_DISPLAY_NAMES.get("pro_monthly", "Quant PRO"),
                "user_id": user_id or "dev_user",
            }

        # Check Stripe subscription table
        if user_id:
            sub = self.truth.get_user_subscription(user_id)
            if sub and sub.get("status") in ("active", "trialing"):
                plan_name = sub.get("plan", "pro_monthly")
                return {
                    "is_pro": True,
                    "tier": "pro",
                    "provider": sub.get("provider", "stripe"),
                    "plan": plan_name,
                    "display_name": PLAN_DISPLAY_NAMES.get(plan_name, "Quant PRO"),
                    "customer_id": sub.get("customer_id"),
                    "current_period_end": sub.get("current_period_end"),
                    "user_id": user_id,
                }

        # Check Whop if configured
        if self.whop_api_key and bearer_token:
            try:
                import requests
                r = requests.get(
                    "https://api.whop.com/api/v2/memberships",
                    headers={"Authorization": f"Bearer {self.whop_api_key}"},
                    params={"membership_id": bearer_token},
                    timeout=8,
                )
                if r.status_code == 200:
                    m = r.json()
                    if m.get("status") in ("active", "trialing", "completed"):
                        return {
                            "is_pro": True,
                            "tier": "pro",
                            "provider": "whop",
                            "plan": "pro_monthly",
                            "display_name": PLAN_DISPLAY_NAMES.get("pro_monthly", "Quant PRO"),
                            "user_id": user_id or bearer_token,
                        }
            except Exception as e:
                logger.warning("Whop check failed: %s", e)

        # Default free observer
        return {
            "is_pro": False,
            "tier": "free",
            "provider": None,
            "plan": "free_observer",
            "display_name": PLAN_DISPLAY_NAMES.get("free_observer", "Free Observer"),
            "user_id": user_id,
        }
