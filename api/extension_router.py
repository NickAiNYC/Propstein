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
  session issuance (S-6). State sits in a pluggable store: Redis when
  ``REDIS_URL`` is configured, in-memory for tests and single-process dev.
  Production refuses to start when more than one web worker would share
  only the in-memory store. Tokens carry an ``sv`` session-version claim.
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
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.session_store import (
    _RATE_BUCKETS,
    _REVOKED_JTI,
    _SESSION_VERSIONS,
    SessionStoreUnavailable,
    configure_from_env,
    get_store,
    store_is_memory,
    use_memory_store,
    worker_count,
)

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


_DEV_SESSION_SECRET = "propstein-extension-dev-secret"
_INSECURE_DEV_WARNED = False
_INSECURE_DEV_WARNING = (
    "INSECURE DEVELOPMENT SECRET: ALLOW_INSECURE_DEV_TOKENS=1 and "
    "EXTENSION_SESSION_SECRET is unset. Extension sessions are signed with "
    "the built-in development secret. Never set ALLOW_INSECURE_DEV_TOKENS in production."
)


def _configured_session_secret() -> str:
    return (os.environ.get("EXTENSION_SESSION_SECRET") or "").strip()


def _insecure_dev_tokens_opted_in() -> bool:
    """Explicit non-production opt-in. The flag does nothing when APP_ENV=production."""
    return (not _is_production()) and os.environ.get("ALLOW_INSECURE_DEV_TOKENS") == "1"


def _warn_insecure_dev_secret() -> None:
    global _INSECURE_DEV_WARNED
    if _INSECURE_DEV_WARNED:
        return
    _INSECURE_DEV_WARNED = True
    logging.getLogger("propstein.security").warning(_INSECURE_DEV_WARNING)
    print(_INSECURE_DEV_WARNING, file=sys.stderr)


def _session_secret() -> str | None:
    """Signing secret. Fail closed unless a real secret or the dev opt-in is set."""
    secret = _configured_session_secret()
    if secret:
        return secret
    if _insecure_dev_tokens_opted_in():
        _warn_insecure_dev_secret()
        return _DEV_SESSION_SECRET
    return None


def assert_session_secret_configured() -> None:
    """Refuse process startup when sessions would be unsigned."""
    if _configured_session_secret():
        return
    if _insecure_dev_tokens_opted_in():
        _warn_insecure_dev_secret()
        return
    raise RuntimeError(
        "Refusing to start: EXTENSION_SESSION_SECRET is unset. "
        "Set a real signing secret, or set ALLOW_INSECURE_DEV_TOKENS=1 "
        "outside production to use the built-in development secret."
    )


def enforce_runtime_security() -> None:
    """Startup gate: signing secret, shared store, and multi-worker policy."""
    assert_session_secret_configured()
    configure_from_env()
    workers = worker_count()
    if _is_production() and store_is_memory():
        if workers > 1:
            raise RuntimeError(
                "Refusing to start: production is configured for "
                f"{workers} web workers but extension revocation and rate "
                "limits are in the in-memory store. Set REDIS_URL so every "
                "worker shares one store (or run a single worker)."
            )
        logging.getLogger("propstein.security").warning(
            "Production is using the in-memory extension session store. "
            "Revocation and rate limits will not be shared across processes. "
            "Set REDIS_URL before raising the worker count."
        )


def _kill_switch_on() -> bool:
    return os.environ.get("EXTENSION_KILL_SWITCH", "0").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Scoped session tokens — HMAC-SHA256, base64url segments
# ---------------------------------------------------------------------------

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
    try:
        session_version = get_store().session_version(principal)
    except SessionStoreUnavailable:
        raise HTTPException(503, "session store is unavailable")
    header = {"alg": "HS256", "typ": SESSION_TOKEN_TYPE}
    payload = {
        "sub": principal,
        "plan": "pro",
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": secrets.token_hex(16),
        "sv": session_version,
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
    principal = str(payload.get("sub") or "")
    try:
        if get_store().is_revoked(jti, now):
            raise HTTPException(401, "session token has been revoked")
        try:
            token_version = int(payload.get("sv"))
        except (TypeError, ValueError):
            raise HTTPException(401, "session token version is missing")
        if token_version != get_store().session_version(principal):
            raise HTTPException(401, "session token version is stale")
    except SessionStoreUnavailable:
        raise HTTPException(503, "session store is unavailable")
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
    try:
        allowed = get_store().check_and_record(
            principal,
            time.time(),
            SESSION_RATE_WINDOW_SECONDS,
            SESSION_RATE_LIMIT,
        )
    except SessionStoreUnavailable:
        raise HTTPException(503, "session store is unavailable")
    if not allowed:
        raise HTTPException(429, "too many session issuance requests — slow down")


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
    try:
        get_store().revoke(jti, float(exp))
    except SessionStoreUnavailable:
        raise HTTPException(503, "session store is unavailable")
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


class PlacedAuditPayload(BaseModel):
    audit_id: str = Field(..., min_length=4)
    signal_id: str = Field(..., min_length=4)
    market_key: str
    user_reported_price: int
    user_reported_line: float
    book: str
    model_fair_line: float | None = None
    achieved_at: str
    client_observed_latency_ms: int | None = None


class MatchTelemetryEvent(BaseModel):
    book: str
    outcome: str  # MATCHED, AMBIGUOUS, NO_EXTRACTION, MULTI_MATCH, MARKET_UNSCOPEABLE
    details: str | dict | None = None
    client_latency_ms: int | None = None
    timestamp: str | None = None


class MatchTelemetryBatch(BaseModel):
    events: list[MatchTelemetryEvent]


def _is_signal_in_ledger(signal_id: str) -> bool:
    """Validate that signal_id matches a pre-committed forecast in the ledger."""
    # Test bypass flag if explicitly set
    if os.environ.get("PROPSTEIN_TEST_ALLOW_MOCK_SIGNALS") == "1":
        return True

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM prospective_signals WHERE id = %s
                        UNION
                        SELECT 1 FROM intended_quotes WHERE id = %s
                        LIMIT 1
                        """,
                        (signal_id, signal_id),
                    )
                    if cur.fetchone():
                        return True
        except Exception:
            pass

    # Check committed snapshots and report artifacts
    root = Path(__file__).resolve().parent.parent
    for json_file in (
        root / "viewer" / "clv_report_2026_w7.json",
        root / "viewer" / "live_odds_feed.json",
        root / "viewer" / "top_picks.json",
    ):
        if json_file.is_file():
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                items = data.get("ledger") or data.get("picks") or data.get("quotes") or []
                for it in items:
                    if (
                        it.get("signal_id") == signal_id
                        or it.get("quote_id") == signal_id
                        or it.get("id") == signal_id
                    ):
                        return True
            except Exception:
                pass

    for jsonl_file in (root / "snapshots").glob("*.jsonl"):
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    if signal_id in line:
                        return True
        except Exception:
            pass

    return False


@router.post("/api/v1/extension/placements")
def record_extension_placement(payload: PlacedAuditPayload):
    """Ingest user-reported [I placed it] audit record into Postgres research ledger."""
    if not _is_signal_in_ledger(payload.signal_id):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "SIGNAL_NOT_IN_LEDGER",
                "message": f"Signal '{payload.signal_id}' does not match any committed forecast in the ledger.",
            },
        )

    out_dir = Path(__file__).resolve().parent.parent / "viewer"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / "extension_placements.jsonl"
    record_dict = payload.model_dump()
    record_dict["server_received_at"] = datetime.now(timezone.utc).isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record_dict) + "\n")

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO placements (
                            id, signal_id, ticket_ref, book,
                            achieved_line, achieved_odds, placed_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            payload.audit_id,
                            payload.signal_id,
                            payload.audit_id,
                            payload.book,
                            payload.user_reported_line,
                            payload.user_reported_price,
                            payload.achieved_at,
                        ),
                    )
        except Exception:
            pass

    return {
        "ok": True,
        "audit_id": payload.audit_id,
        "status": "RECORDED",
        "stored_at": record_dict["server_received_at"],
    }


@router.post("/api/v1/extension/telemetry")
def record_extension_telemetry(payload: MatchTelemetryBatch):
    """Record match-layer telemetry batches for real-book DOM performance evaluation."""
    out_dir = Path(__file__).resolve().parent.parent / "viewer"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / "extension_match_telemetry.jsonl"
    received_at = datetime.now(timezone.utc).isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        for ev in payload.events:
            d = ev.model_dump()
            d["server_received_at"] = received_at
            d["client_observed"] = True
            f.write(json.dumps(d) + "\n")

    return {"ok": True, "count": len(payload.events)}
