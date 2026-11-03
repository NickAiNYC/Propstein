"""
PropStein Live Sniper — Extension API (additive router, v1)
===========================================================
Scope: ``/api/v1/extension/*`` (session lifecycle, health / kill switch) and
``/api/v1/markets/*`` (entitlement-gated model intelligence for the browser
companion).

Security design — implements the mitigations from docs/LIVE_SNIPER_AUDIT.md
(S-1, S-3, S-6):

* Entitlement is verified **server-side** (Whop membership) before any
  session is issued; the client-visible artifact is a **short-lived scoped
  token** (15 min default) with ``exp`` / ``iat`` / ``jti`` claims signed
  with HMAC-SHA256 — never the raw long-lived membership id (S-3).
* Every market-intelligence route requires the scoped token; verification
  fails CLOSED (401/503) on any error. There is no client-side paywall
  (S-1): unauthenticated callers receive nothing but the public health
  document.
* ``jti`` revocation list + per-principal sliding-window rate limit on
  session issuance (S-6). Revocation state is process-local — production
  multi-worker deployments must move it to Redis (documented limitation).
* ``EXTENSION_KILL_SWITCH=1`` disables the extension surface immediately:
  health reports the switch and all session/market routes return 503.

Honesty design — audit §3.3.1:

* Drive-level reception markets have **no live data source and no
  calibration corpus** today. The API therefore returns ``NO_COVERAGE`` for
  every real-book source. The only covered surface is the synthetic
  ``demobook`` fixture, whose parameters mirror
  ``extensions/packages/detection/src/adapters/demo-model.ts`` verbatim and
  are labeled ``uncalibrated`` — they are demo values, never presented as
  model confidence.

CORS note (audit S-5): the packaged ``chrome-extension://<id>`` origin must
be appended to ``ALLOWED_ORIGINS`` at deploy time by the operator. That is
an intentional operator action, not something this branch silently changes.

This module is deliberately self-contained (stdlib + FastAPI only) so the
router can be tested without the heavier ``api.main`` import graph, and the
production include stays a two-line additive change.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

MIN_EXTENSION_VERSION = "0.1.0"
SESSION_TOKEN_TYPE = "pste-ext-v1"
DEFAULT_SESSION_TTL_SECONDS = 15 * 60
MAX_SESSION_TTL_SECONDS = 60 * 60
SESSION_RATE_LIMIT = 10          # issuance requests ...
SESSION_RATE_WINDOW_SECONDS = 60  # ... per rolling window per principal
WHOP_ALLOWED_STATUSES = ("active", "trialing", "completed")

# ---------------------------------------------------------------------------
# Dev/test affordances (mirrors api/main.py verify_entitlement semantics)
# ---------------------------------------------------------------------------


def _is_production() -> bool:
    return os.environ.get("APP_ENV", "production").lower() == "production"


def _dev_bypass_enabled() -> bool:
    return not _is_production() and os.environ.get("PROPWIRE_ALLOW_DEV_AUTH_BYPASS") == "1"


def _session_secret() -> str | None:
    """Signing secret. Fail closed in production when unset."""
    secret = os.environ.get("EXTENSION_SESSION_SECRET")
    if secret:
        return secret
    if _is_production():
        return None
    # Deterministic non-production default: local dev and the test suite can
    # exercise the full token flow without secrets; never valid in production.
    return "propstein-extension-dev-secret"


def _kill_switch_on() -> bool:
    return os.environ.get("EXTENSION_KILL_SWITCH", "0").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Scoped session tokens — HMAC-SHA256, base64url segments
# ---------------------------------------------------------------------------

_REVOKED_JTI: dict[str, float] = {}  # jti -> expiration epoch (lazy-cleaned)
_RATE_BUCKETS: dict[str, list[float]] = {}  # principal -> issuance timestamps


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def issue_session_token(principal: str, ttl_seconds: int) -> tuple[str, dict]:
    secret = _session_secret()
    if secret is None:
        raise HTTPException(503, "session signing is unavailable")
    now = int(time.time())
    header = {"alg": "HS256", "typ": SESSION_TOKEN_TYPE}
    payload = {
        "sub": principal,
        "plan": "pro",
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": secrets.token_hex(16),
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}", payload


def verify_session_token(token: str) -> dict:
    """Verify signature, expiry, and revocation. Raises 401 on ANY problem."""
    secret = _session_secret()
    if secret is None:
        raise HTTPException(503, "session signing is unavailable")
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "malformed session token")
    h, p, sig = parts
    expected = _b64url(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "session token signature mismatch")
    try:
        header = json.loads(_b64url_decode(h))
        payload = json.loads(_b64url_decode(p))
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(401, "session token payload is not valid JSON")
    if header.get("typ") != SESSION_TOKEN_TYPE or header.get("alg") != "HS256":
        raise HTTPException(401, "unexpected session token type/algorithm")
    if payload.get("plan") != "pro":
        raise HTTPException(403, "session token is not entitled for Live Sniper")
    now = int(time.time())
    if int(payload.get("exp", 0)) <= now:
        raise HTTPException(401, "session token expired — sign in again")
    jti = str(payload.get("jti", ""))
    revoked_until = _REVOKED_JTI.get(jti)
    if revoked_until is not None and revoked_until > now:
        raise HTTPException(401, "session token has been revoked")
    return payload


def require_scoped_session(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: a valid, unrevoked scoped session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing scoped session token")
    if _kill_switch_on():
        raise HTTPException(503, "extension surface disabled by kill switch")
    return verify_session_token(authorization.split(" ", 1)[1])


def _principal_of(membership: dict) -> str:
    for key in ("id", "membership_id", "user_id"):
        value = membership.get(key)
        if isinstance(value, str) and value:
            return value
    return "whop-member"


def _check_rate_limit(principal: str) -> None:
    now = time.time()
    window = [t for t in _RATE_BUCKETS.get(principal, []) if now - t < SESSION_RATE_WINDOW_SECONDS]
    if len(window) >= SESSION_RATE_LIMIT:
        raise HTTPException(429, "too many session issuance requests — slow down")
    window.append(now)
    _RATE_BUCKETS[principal] = window


def _verify_membership(authorization: str | None) -> dict:
    """Server-side Whop entitlement check (fail closed). Self-contained copy
    of api/main.py verify_entitlement semantics so this router stays testable
    in isolation; behavior is intentionally identical."""
    key = os.environ.get("WHOP_API_KEY")
    if not key:
        if _dev_bypass_enabled():
            return {"status": "active", "id": "dev-bypass", "note": "explicit local-development bypass"}
        raise HTTPException(503, "entitlement verification is unavailable")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    import requests

    response = requests.get(
        "https://api.whop.com/api/v2/memberships",
        headers={"Authorization": f"Bearer {key}"},
        params={"membership_id": token},
        timeout=10,
    )
    if response.status_code != 200:
        raise HTTPException(401, "could not verify membership")
    membership = response.json()
    if membership.get("status") not in WHOP_ALLOWED_STATUSES:
        raise HTTPException(403, "membership not active")
    return membership


# ---------------------------------------------------------------------------
# Synthetic demobook model coverage (mirrors the extension demo parameters)
# ---------------------------------------------------------------------------

DRIVE_REC_MODEL_VERSION = "DRIVE-REC-V1"
DEMO_EVENT_ID = "2026_09_NE_KC"
DEMO_LEAGUE = "NFL"

# (playerId, playerName, team, q, N, s, uncertaintyBand) — SYNTHETIC ONLY.
# Mirrors extensions/packages/detection/src/adapters/demo-model.ts exactly.
SYNTHETIC_DEMO_PARAMS: list[tuple[str, str, str, float, int, float, float]] = [
    ("nfl_travis_kelce", "Travis Kelce", "KC", 0.1841, 8, 0.72, 0.04),
    ("nfl_rashee_rice", "Rashee Rice", "KC", 0.2276, 8, 0.72, 0.04),
    ("nfl_hunter_henry", "Hunter Henry", "NE", 0.105, 8, 0.72, 0.04),
    ("nfl_juwan_johnson", "Juwan Johnson", "NE", 0.091, 8, 0.72, 0.04),
]

SYNTHETIC_SOURCE = "demobook"
REAL_SOURCES = ("draftkings", "fanduel", "polymarket", "bovada", "espnbet", "betmgm", "caesars", "betrivers", "pinnacle", "circa", "fanatics", "bet365")


def drive_survival_adjusted(q: float, n: int, s: float) -> float:
    """DRIVE-REC-V1 closed form: P = q * (1 - (s(1-q))^N) / (1 - s(1-q)).

    Port of extensions/packages/core/src/drive-reception-model.ts
    driveSurvivalAdjusted — identical numerics.
    """
    r = s * (1.0 - q)
    if r == 1.0:
        return min(1.0, q * n)
    return (q * (1.0 - r ** n)) / (1.0 - r)


def _demo_roster() -> list[dict]:
    return [
        {
            "playerId": player_id,
            "playerName": name,
            "team": team,
            "eventId": DEMO_EVENT_ID,
            "league": DEMO_LEAGUE,
        }
        for player_id, name, team, _q, _n, _s, _band in SYNTHETIC_DEMO_PARAMS
    ]


def _no_coverage(reasons: list[str]) -> dict:
    return {"model": None, "status": "NO_COVERAGE", "reasons": reasons}


# ---------------------------------------------------------------------------
# Routes — health / kill switch
# ---------------------------------------------------------------------------


@router.get("/api/v1/extension/health")
def extension_health() -> dict:
    """Public health + kill-switch document. The extension polls this before
    operating; a switched-on kill switch is reported, never hidden."""
    killed = _kill_switch_on()
    return {
        "ok": not killed,
        "service": "propstein-extension-api",
        "apiVersion": "v1",
        "killSwitch": killed,
        "minExtensionVersion": MIN_EXTENSION_VERSION,
        "sessionTtlSeconds": DEFAULT_SESSION_TTL_SECONDS,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Routes — session lifecycle
# ---------------------------------------------------------------------------


@router.post("/api/v1/extension/session")
def extension_session(authorization: str | None = Header(default=None)) -> dict:
    """Exchange a PropStein membership credential for a short-lived scoped
    session token. Entitlement is verified server-side FIRST (Whop); the
    response token is the only credential the extension may use afterwards."""
    if _kill_switch_on():
        raise HTTPException(503, "extension surface disabled by kill switch")
    membership = _verify_membership(authorization)
    principal = _principal_of(membership)
    _check_rate_limit(principal)

    try:
        ttl = int(os.environ.get("EXTENSION_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
    except ValueError:
        ttl = DEFAULT_SESSION_TTL_SECONDS
    ttl = max(60, min(MAX_SESSION_TTL_SECONDS, ttl))

    token, payload = issue_session_token(principal, ttl)
    now = datetime.now(timezone.utc)
    return {
        "tier": "pro",
        "provider": "whop",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        "ttl_seconds": ttl,
        "token_type": SESSION_TOKEN_TYPE,
        "token": token,
        "principal": principal,
        "note": "scoped token — send as Authorization: Bearer <token> to /api/v1/markets/*",
    }


@router.post("/api/v1/extension/session/revoke")
def extension_session_revoke(session: dict = Depends(require_scoped_session)) -> dict:
    """Revoke the presented session token by jti (client-initiated sign-out).
    The revocation is honored until the token's own expiration passes."""
    jti = str(session.get("jti", ""))
    exp = int(session.get("exp", 0))
    _REVOKED_JTI[jti] = float(exp)
    # Lazy cleanup of expired revocation entries.
    now = time.time()
    for key, until in list(_REVOKED_JTI.items()):
        if until <= now:
            _REVOKED_JTI.pop(key, None)
    return {"revoked": True, "jti": jti, "untilEpoch": exp}


# ---------------------------------------------------------------------------
# Routes — model intelligence (scoped-token gated, fail closed)
# ---------------------------------------------------------------------------


@router.get("/api/v1/markets/model-coverage")
def markets_model_coverage(session: dict = Depends(require_scoped_session)) -> dict:
    """Roster the extension's matcher resolves players against. Only the
    synthetic demobook surface is covered today; real books return an empty
    roster because no licensed drive-level feed exists yet (audit §3.3.1)."""
    return {
        "roster": _demo_roster(),
        "coverage": [
            {
                "source": SYNTHETIC_SOURCE,
                "marketType": "drive_reception_1plus",
                "available": True,
                "modelVersion": DRIVE_REC_MODEL_VERSION,
                "confidence": "uncalibrated",
                "provenance": "SYNTHETIC_DEMO_PARAMETERS",
            }
        ],
        "limitations": [
            "drive-level reception markets on real books have NO MODEL COVERAGE until a possession-level feed and calibration corpus exist",
        ],
        "principal": session.get("sub"),
        "issuedAt": datetime.now(timezone.utc).isoformat(),
    }


class EvaluateRequest(BaseModel):
    source: str = Field(..., description="observed market source (adapter id)")
    eventId: str | None = None
    playerId: str | None = None
    playerName: str | None = None
    marketType: str = Field(..., description="normalized market type code")
    selection: str | None = None
    americanOdds: float | None = None
    line: float | None = None
    driveId: str | None = None


@router.post("/api/v1/markets/evaluate")
def markets_evaluate(payload: EvaluateRequest, session: dict = Depends(require_scoped_session)) -> dict:
    """Evaluate an OBSERVED market against DRIVE-REC-V1.

    Honest coverage policy:
      - source == "demobook"  → synthetic demo parameters (uncalibrated)
      - any real book source  → NO_COVERAGE (no licensed drive-level data)
      - drive-scoped market without a drive binding → NO_COVERAGE
    """
    source = (payload.source or "").strip().lower()
    if source != SYNTHETIC_SOURCE:
        return _no_coverage(
            [
                f"source '{payload.source}' has no drive-level model coverage — "
                "a licensed possession-level feed and calibration corpus are prerequisites (audit §3.3.1)",
            ]
        )
    if payload.marketType != "drive_reception_1plus":
        return _no_coverage(
            [f"market type '{payload.marketType}' is outside DRIVE-REC-V1 coverage"]
        )
    if not payload.driveId:
        return _no_coverage(["drive-scoped market without a live drive binding"])

    row = next(
        (
            r
            for r in SYNTHETIC_DEMO_PARAMS
            if (payload.playerId and r[0] == payload.playerId)
            or (payload.playerName and r[1].lower() == payload.playerName.strip().lower())
        ),
        None,
    )
    if row is None:
        return _no_coverage(
            [f"player '{payload.playerId or payload.playerName}' is not on the synthetic demobook roster"]
        )
    _player_id, _name, _team, q, n, s, band = row
    probability = drive_survival_adjusted(q, n, s)
    lo = drive_survival_adjusted(max(0.0001, q - band), n, s)
    hi = drive_survival_adjusted(min(0.9999, q + band), n, s)
    return {
        "model": {
            "probability": probability,
            "modelVersion": DRIVE_REC_MODEL_VERSION,
            "confidence": "uncalibrated",
            "probabilityInterval": [lo, hi],
            "provenance": "SYNTHETIC_DEMO_PARAMETERS",
        },
        "principal": session.get("sub"),
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
    }
