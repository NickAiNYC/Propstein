"""Ledger API. Model numbers are resolved on the server. DATABASE_URL comes from the environment."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.ledger.language import find_forbidden
from src.ledger.slip_audit import Leg
from src.ledger.store import LedgerUnavailable, connect, create_research_reference, create_slip_audit, public_chain
from src.ledger.timeparse import TimestampRejected, parse_timestamp

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[1]


class ResearchReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pseudonym: str = Field(min_length=1, max_length=80)
    player_id: str = Field(min_length=1)
    market: str
    line: float
    selection: Literal["over", "under"]
    observed_at: str
    event_id: str = Field(min_length=1)
    event_start_at: str
    book: str | None = None
    quoted_american_odds: int | None = None


class SlipLegBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str
    event_id: str
    event_start_at: str
    market: str
    selection: Literal["over", "under"]
    line: float
    user_confirmed: bool
    team: str | None = None
    book: str | None = None
    research_reference_id: str | None = None
    ocr_confidence: float | None = None
    ocr_confirmed: bool | None = None


class SlipAuditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pseudonym: str = Field(min_length=1, max_length=80)
    legs: list[SlipLegBody] = Field(min_length=1, max_length=16)


def _database_url() -> str:
    dsn = (os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="ledger database is unavailable")
    return dsn


@contextmanager
def _connection():
    conn = connect(_database_url())
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _snapshot_dir() -> Path:
    raw = os.environ.get("PROPSTEIN_SNAPSHOT_DIR")
    return Path(raw) if raw else _ROOT / "snapshots"


def _guard(payload: dict) -> JSONResponse:
    if find_forbidden(json.dumps(payload)):
        raise HTTPException(status_code=500, detail="response failed the language check")
    return JSONResponse(payload)


def _failure(status: int, reason: str, detail: str) -> JSONResponse:
    payload = {
        "status": "unavailable" if status == 409 else "rejected",
        "reason": reason,
        "saved": False,
        "detail": detail,
    }
    if find_forbidden(json.dumps(payload)):
        raise HTTPException(status_code=500, detail="response failed the language check")
    return JSONResponse(payload, status_code=status)


def _pseudonym_ok(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in "._:-" for ch in value)


@router.post("/api/v1/research-references")
def post_research_reference(body: ResearchReferenceBody):
    if not _pseudonym_ok(body.pseudonym):
        return _failure(422, "PSEUDONYM_REJECTED", "pseudonym must be an opaque token")
    now = datetime.now(timezone.utc)
    try:
        observed_at = parse_timestamp(body.observed_at, now=now, allow_future=False)
        event_start_at = parse_timestamp(body.event_start_at, now=now, allow_future=True)
    except TimestampRejected as exc:
        return _failure(422, f"TIMESTAMP_{exc.reason.upper()}", "timestamp is missing, naive, or future-dated")
    try:
        with _connection() as conn:
            payload = create_research_reference(
                conn,
                pseudonym=body.pseudonym,
                player_id=body.player_id,
                market=body.market,
                line=body.line,
                selection=body.selection,
                observed_at=observed_at,
                event_id=body.event_id,
                event_start_at=event_start_at,
                book=body.book,
                quoted_american_odds=body.quoted_american_odds,
                snapshot_dir=_snapshot_dir(),
            )
    except LedgerUnavailable as exc:
        status = 409 if exc.reason == "NO_SERVER_SNAPSHOT" else 422
        return _failure(status, exc.reason, exc.detail)
    except HTTPException:
        raise
    except Exception:
        return _failure(503, "LEDGER_UNAVAILABLE", "the ledger could not save this reference")
    return _guard(payload)


@router.post("/api/v1/slip-audits")
def post_slip_audit(body: SlipAuditBody):
    if not _pseudonym_ok(body.pseudonym):
        return _failure(422, "PSEUDONYM_REJECTED", "pseudonym must be an opaque token")
    now = datetime.now(timezone.utc)
    legs: list[Leg] = []
    for leg in body.legs:
        try:
            event_start = parse_timestamp(leg.event_start_at, now=now, allow_future=True)
        except TimestampRejected as exc:
            return _failure(422, f"TIMESTAMP_{exc.reason.upper()}", "timestamp is missing, naive, or future-dated")
        if not leg.user_confirmed:
            return _failure(422, "UNCONFIRMED_LEG", "unconfirmed legs are rejected and are not analyzed")
        legs.append(Leg(
            player_id=leg.player_id,
            event_id=leg.event_id,
            event_start_at=event_start.isoformat(),
            market=leg.market,
            selection=leg.selection,
            line=leg.line,
            user_confirmed=True,
            team=leg.team,
            book=leg.book,
            research_reference_id=leg.research_reference_id,
            ocr_confidence=leg.ocr_confidence,
            ocr_confirmed=leg.ocr_confirmed,
        ))
    try:
        with _connection() as conn:
            payload = create_slip_audit(conn, pseudonym=body.pseudonym, legs=legs)
    except LedgerUnavailable as exc:
        status = 503 if exc.reason == "REGISTRY_HASH_MISMATCH" else 422
        return _failure(status, exc.reason, exc.detail)
    except HTTPException:
        raise
    except Exception:
        return _failure(503, "LEDGER_UNAVAILABLE", "the ledger could not save this audit")
    return _guard(payload)


@router.get("/api/v1/evidence-passports/{passport_id}/chain")
def get_chain(passport_id: str):
    try:
        with _connection() as conn:
            payload = public_chain(conn, passport_id)
    except HTTPException:
        raise
    except Exception:
        return _failure(503, "LEDGER_UNAVAILABLE", "the ledger could not be read")
    return _guard(payload)


@router.get("/api/v1/ledger/populations")
def get_populations():
    try:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM population_counts")
                row = cur.fetchone()
            payload = {key: int(row[key]) for key in row.keys()} if row else {}
    except HTTPException:
        raise
    except Exception:
        return _failure(503, "LEDGER_UNAVAILABLE", "population counts are unavailable")
    return _guard(payload)


@router.get("/api/v1/ledger/gates")
def get_gates():
    try:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT flag_name, passed FROM independent_gate_flags")
                rows = cur.fetchall()
    except HTTPException:
        raise
    except Exception:
        return _failure(503, "LEDGER_UNAVAILABLE", "gate flags are unavailable")
    flags = {row["flag_name"]: bool(row["passed"]) for row in rows}
    payload = {
        "model_validation_passed": flags.get("model_validation", False),
        "paid_tier_clv_passed": flags.get("paid_tier_clv", False),
    }
    return _guard(payload)
