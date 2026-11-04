"""Postgres writes for the ledger. Mutations of existing rows are not offered."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from src.ledger.close_match import LINE_CHANGED, CloseQuote, MatchResult, match_close
from src.ledger.context_gate import reference_context_status
from src.ledger.hashchain import event_integrity_hash, payload_canonical, utc_canonical
from src.ledger.historical_gaps import classify_import_row
from src.ledger.registry import RegistryMismatch, require_active_registration
from src.ledger.slip_audit import AuditResult, Leg, UnconfirmedLegRejected, audit_confirmed_legs
from src.ledger.snapshots import SnapshotStore, coverage_label


class LedgerUnavailable(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def connect(dsn: str):
    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)


def _append_event(cur, *, passport_id: str, event_type: str, payload: dict) -> str:
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(passport_id),))
    cur.execute(
        """
        SELECT seq, integrity_hash
        FROM ledger_events
        WHERE passport_id = %s
        ORDER BY seq DESC
        LIMIT 1
        """,
        (passport_id,),
    )
    prior = cur.fetchone()
    seq = 1 if prior is None else int(prior["seq"]) + 1
    prev_hash = None if prior is None else prior["integrity_hash"]
    created = datetime.now(timezone.utc)
    created_text = utc_canonical(created)
    canonical = payload_canonical(payload)
    digest = event_integrity_hash(
        passport_id=str(passport_id),
        seq=seq,
        event_type=event_type,
        payload_canonical_text=canonical,
        prev_hash=prev_hash,
        created_at_canonical=created_text,
    )
    cur.execute(
        """
        INSERT INTO ledger_events (
          passport_id, seq, event_type, payload_canonical, prev_hash,
          integrity_hash, created_at_canonical, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING integrity_hash
        """,
        (passport_id, seq, event_type, canonical, prev_hash, digest, created_text, created),
    )
    return cur.fetchone()["integrity_hash"]


def _user_id(cur, pseudonym: str) -> str:
    cur.execute(
        "INSERT INTO users (pseudonym) VALUES (%s) ON CONFLICT (pseudonym) DO NOTHING",
        (pseudonym,),
    )
    cur.execute("SELECT id FROM users WHERE pseudonym = %s", (pseudonym,))
    return str(cur.fetchone()["id"])


def latest_registration(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, release_id, artifact_sha256, artifact_canonical, registered_at
            FROM rule_registrations
            ORDER BY registered_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return dict(row) if row else None


def verify_passport_chain(conn, passport_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT seq, event_type, payload_canonical, prev_hash, integrity_hash,
                   created_at_canonical
            FROM ledger_events
            WHERE passport_id = %s
            ORDER BY seq
            """,
            (passport_id,),
        )
        rows = cur.fetchall()
    prev = None
    for row in rows:
        if int(row["seq"]) == 1 and row["prev_hash"] is not None:
            return False
        if row["prev_hash"] != prev:
            return False
        digest = event_integrity_hash(
            passport_id=str(passport_id),
            seq=int(row["seq"]),
            event_type=row["event_type"],
            payload_canonical_text=row["payload_canonical"],
            prev_hash=row["prev_hash"],
            created_at_canonical=row["created_at_canonical"],
        )
        if digest != row["integrity_hash"]:
            return False
        prev = row["integrity_hash"]
    return bool(rows)


def create_research_reference(
    conn,
    *,
    pseudonym: str,
    player_id: str,
    market: str,
    line: float,
    selection: str,
    observed_at: datetime,
    event_id: str,
    event_start_at: datetime,
    book: str | None,
    quoted_american_odds: int | None,
    snapshot_dir,
    context_status_fn=None,
) -> dict:
    if context_status_fn is None:
        from src.ledger.context_gate import reference_context_status as context_status_fn
    if not str(event_id).strip():
        raise LedgerUnavailable("MISSING_EVENT_ID", "event_id is required and cannot be added later")
    store = SnapshotStore(snapshot_dir)
    snapshot = store.resolve(
        player_id=player_id,
        market=market,
        line=line,
        selection=selection,
        observed_at=observed_at,
    )
    if snapshot is None:
        raise LedgerUnavailable(
            "NO_SERVER_SNAPSHOT",
            "No server snapshot exists for this player and market at the stated time.",
        )
    context_status = context_status_fn(snapshot.game_id, observed_at)
    coverage = coverage_label()
    with conn.cursor() as cur:
        user_id = _user_id(cur, pseudonym)
        cur.execute(
            """
            INSERT INTO evidence_passports (user_id, cohort, subject_type, context_status)
            VALUES (%s, 'user_research', 'research_reference', %s)
            RETURNING id
            """,
            (user_id, context_status),
        )
        passport_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO research_references (
              passport_id, user_id, event_id, event_start_at, player_id, player_name,
              team, opponent, game_id, market, selection, line, book, quoted_american_odds,
              observed_at, snapshot_id, model_version, model_coverage, model_probability,
              uncertainty_low, uncertainty_high, input_snapshot_hash, fair_line,
              projected_volume, context_status
            )
            VALUES (
              %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s,
              NULL, NULL, %s, %s,
              %s, %s
            )
            RETURNING id
            """,
            (
                passport_id, user_id, event_id.strip(), event_start_at, snapshot.player_id,
                snapshot.player_name, snapshot.team, snapshot.opponent, snapshot.game_id,
                snapshot.canonical_market, selection, Decimal(str(line)), book,
                quoted_american_odds, observed_at, snapshot.snapshot_id, snapshot.model_version,
                coverage, snapshot.model_probability, snapshot.content_hash, snapshot.fair_line,
                snapshot.projected_volume, context_status,
            ),
        )
        reference_id = str(cur.fetchone()["id"])
        _append_event(cur, passport_id=passport_id, event_type="passport_opened", payload={
            "cohort": "user_research",
            "context_status": context_status,
            "event_id": event_id.strip(),
            "subject_type": "research_reference",
        })
        integrity = _append_event(cur, passport_id=passport_id, event_type="research_reference_recorded", payload={
            "event_id": event_id.strip(),
            "event_start_at": utc_canonical(event_start_at),
            "input_snapshot_hash": snapshot.content_hash,
            "market": snapshot.canonical_market,
            "model_coverage": coverage,
            "model_version": snapshot.model_version,
            "research_reference_id": reference_id,
        })
    conn.commit()
    return {
        "status": "saved",
        "saved": True,
        "passport_id": passport_id,
        "research_reference_id": reference_id,
        "event_id": event_id.strip(),
        "event_start_at": utc_canonical(event_start_at),
        "model_version": snapshot.model_version,
        "model_coverage": coverage,
        "context_status": context_status,
        "input_snapshot_hash": snapshot.content_hash,
        "fair_line": snapshot.fair_line,
        "projected_volume": snapshot.projected_volume,
        "uncertainty_interval": None,
        "integrity_hash": integrity,
    }


def create_slip_audit(conn, *, pseudonym: str, legs: list[Leg]) -> dict:
    registration = latest_registration(conn)
    try:
        require_active_registration(registration)
    except RegistryMismatch as exc:
        raise LedgerUnavailable("REGISTRY_HASH_MISMATCH", str(exc)) from exc

    def exists(reference_id: str) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM research_references r
                JOIN users u ON u.id = r.user_id
                WHERE r.id = %s AND u.pseudonym = %s
                """,
                (reference_id, pseudonym),
            )
            return cur.fetchone() is not None

    try:
        result: AuditResult = audit_confirmed_legs(legs, registration, reference_exists=exists)
    except UnconfirmedLegRejected as exc:
        raise LedgerUnavailable("UNCONFIRMED_LEG", str(exc)) from exc
    with conn.cursor() as cur:
        user_id = _user_id(cur, pseudonym)
        cur.execute(
            """
            INSERT INTO evidence_passports (user_id, cohort, subject_type, context_status)
            VALUES (%s, 'user_slip', 'slip_audit', 'NOT_APPLICABLE')
            RETURNING id
            """,
            (user_id,),
        )
        passport_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO slip_audits (passport_id, user_id, registration_id, disclaimer)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (passport_id, user_id, registration["id"], result.disclaimer),
        )
        audit_id = str(cur.fetchone()["id"])
        for index, leg in enumerate(legs):
            cur.execute(
                """
                INSERT INTO slip_legs (
                  slip_audit_id, leg_index, event_id, event_start_at, player_id, team,
                  market, selection, line, book, user_confirmed, research_reference_id,
                  ocr_confidence, ocr_confirmed
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                """,
                (
                    audit_id, index, leg.event_id, leg.event_start_at, leg.player_id, leg.team,
                    leg.market, leg.selection, Decimal(str(leg.line)), leg.book,
                    leg.research_reference_id, leg.ocr_confidence, leg.ocr_confirmed,
                ),
            )
        for finding in result.findings:
            cur.execute(
                """
                INSERT INTO audit_findings (slip_audit_id, rule_id, leg_indexes, detail, disclaimer)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (audit_id, finding.rule_id, list(finding.leg_indexes), finding.detail, finding.disclaimer),
            )
        _append_event(cur, passport_id=passport_id, event_type="passport_opened", payload={
            "cohort": "user_slip",
            "registration_id": registration["id"],
            "subject_type": "slip_audit",
        })
        integrity = _append_event(cur, passport_id=passport_id, event_type="slip_audit_recorded", payload={
            "disclaimer": result.disclaimer,
            "finding_rule_ids": [finding.rule_id for finding in result.findings],
            "slip_audit_id": audit_id,
        })
    conn.commit()
    return {
        "status": "saved",
        "saved": True,
        "passport_id": passport_id,
        "slip_audit_id": audit_id,
        "registration_id": registration["id"],
        "disclaimer": result.disclaimer,
        "integrity_hash": integrity,
        "findings": [
            {
                "rule_id": finding.rule_id,
                "legs": list(finding.leg_indexes),
                "detail": finding.detail,
                "disclaimer": finding.disclaimer,
            }
            for finding in result.findings
        ],
    }


def import_signal_row(conn, *, row: dict, cohort: str, source_name: str, locator: str) -> str:
    if cohort not in ("prospective_full_board", "historical_backtest"):
        raise LedgerUnavailable("COHORT_REJECTED", "user records are not signal imports")
    gap = classify_import_row(row, source_name=source_name, locator=locator)
    schema_gap = cohort == "prospective_full_board" and row.get("schema") != "propstein.prospective_board.v1"
    if gap is not None or schema_gap:
        missing = list(gap.missing_fields if gap is not None else ())
        if schema_gap and "prospective_schema" not in missing:
            missing.append("prospective_schema")
        _insert_gap(conn, row=row, source_name=source_name, locator=locator, cohort=cohort, missing=missing)
        return "gap"
    event_id = str(row["event_id"]).strip()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_passports (cohort, subject_type, context_status)
            VALUES (%s, 'prospective_signal', 'NOT_APPLICABLE')
            RETURNING id
            """,
            (cohort,),
        )
        passport_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO prospective_signals (
              passport_id, cohort, event_id, event_start_at, source_name,
              source_record_sha256, game_id, player_id, market, model_version,
              payload_canonical, captured_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_record_sha256) DO NOTHING
            RETURNING id
            """,
            (
                passport_id, cohort, event_id, row["event_start_at"], source_name,
                row["record_sha256"], row.get("game_id"), row.get("player_id"), row.get("market"),
                row.get("model_version"), payload_canonical(row), row.get("captured_at"),
            ),
        )
        inserted = cur.fetchone()
        if inserted is None:
            conn.rollback()
            return "duplicate"
        _append_event(cur, passport_id=passport_id, event_type="passport_opened", payload={
            "cohort": cohort,
            "event_id": event_id,
            "subject_type": "prospective_signal",
        })
        _append_event(cur, passport_id=passport_id, event_type="signal_recorded", payload={
            "event_id": event_id,
            "event_start_at": row["event_start_at"],
            "signal_id": str(inserted["id"]),
            "source_record_sha256": row["record_sha256"],
        })
    conn.commit()
    return "signal"


def _insert_gap(conn, *, row: dict, source_name: str, locator: str, cohort: str, missing: list[str]) -> None:
    digest = row.get("record_sha256") if isinstance(row.get("record_sha256"), str) else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO historical_evidence_gaps (
              source_name, source_locator, source_cohort, missing_fields,
              payload_canonical, source_integrity_hash, event_id, event_start_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL)
            ON CONFLICT (source_name, source_locator) DO NOTHING
            """,
            (source_name, locator, cohort, missing, payload_canonical(row), digest),
        )
    conn.commit()


def add_intended_quote(conn, *, signal_id: str, quote: CloseQuote, book: str | None, quoted_at: datetime) -> str:
    if quote.over_american_odds is None or quote.under_american_odds is None or not quote.settlement_rules:
        raise LedgerUnavailable("INCOMPLETE_QUOTE", "an intended quote needs both prices and settlement rules")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, event_start_at FROM prospective_signals WHERE id = %s
            """,
            (signal_id,),
        )
        signal = cur.fetchone()
        if signal is None or signal["event_id"] != quote.event_id:
            raise LedgerUnavailable("EVENT_MISMATCH", "intended quote event_id must match the signal")
        cur.execute(
            """
            INSERT INTO intended_quotes (
              signal_id, event_id, event_start_at, market, selection, line,
              settlement_rules, over_american_odds, under_american_odds, book, quoted_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                signal_id, quote.event_id, signal["event_start_at"], quote.market, quote.selection,
                Decimal(str(quote.line)), quote.settlement_rules, quote.over_american_odds,
                quote.under_american_odds, book, quoted_at,
            ),
        )
        quote_id = str(cur.fetchone()["id"])
    conn.commit()
    return quote_id


def add_placement(conn, *, signal_id: str, ticket_ref: str, quote: CloseQuote, book: str | None, placed_at: datetime) -> str:
    if not str(ticket_ref).strip():
        raise LedgerUnavailable("MISSING_TICKET", "a placement requires a real ticket reference")
    if quote.over_american_odds is None or quote.under_american_odds is None or not quote.settlement_rules:
        raise LedgerUnavailable("INCOMPLETE_QUOTE", "a placement needs both prices and settlement rules")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_start_at, passport_id FROM prospective_signals WHERE id = %s",
            (signal_id,),
        )
        signal = cur.fetchone()
        if signal is None or signal["event_id"] != quote.event_id:
            raise LedgerUnavailable("EVENT_MISMATCH", "placement event_id must match the signal")
        cur.execute(
            """
            INSERT INTO placements (
              signal_id, event_id, event_start_at, ticket_ref, market, selection,
              achieved_line, settlement_rules, over_american_odds, under_american_odds,
              book, placed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                signal_id, quote.event_id, signal["event_start_at"], ticket_ref.strip(),
                quote.market, quote.selection, Decimal(str(quote.line)), quote.settlement_rules,
                quote.over_american_odds, quote.under_american_odds, book, placed_at,
            ),
        )
        placement_id = str(cur.fetchone()["id"])
        _append_event(cur, passport_id=str(signal["passport_id"]), event_type="placement_recorded", payload={
            "event_id": quote.event_id,
            "placement_id": placement_id,
            "ticket_ref": ticket_ref.strip(),
        })
    conn.commit()
    return placement_id


def _quote_from_row(row: dict, *, line_key: str) -> CloseQuote:
    return CloseQuote(
        event_id=row["event_id"],
        market=row["market"],
        selection=row["selection"],
        line=float(row[line_key]),
        settlement_rules=row["settlement_rules"],
        over_american_odds=row["over_american_odds"],
        under_american_odds=row["under_american_odds"],
    )


def record_closing_reference(
    conn,
    *,
    signal_id: str | None,
    placement_id: str | None,
    observed: CloseQuote,
    source_id: str,
    observed_at: datetime,
) -> dict:
    """Insert a matched close only when identity fields agree. A line change is UNMATCHED."""
    if not source_id.strip():
        raise LedgerUnavailable("MISSING_SOURCE", "a closing reference requires source_id")
    with conn.cursor() as cur:
        expected_signal = None
        expected_placement = None
        if signal_id is not None:
            cur.execute("SELECT * FROM intended_quotes WHERE signal_id = %s", (signal_id,))
            quote_row = cur.fetchone()
            if quote_row is None:
                result = MatchResult(False, "MISSING_CLOSE")
            else:
                expected_signal = _quote_from_row(quote_row, line_key="line")
                result = match_close(expected_signal, observed)
            signal_result = result
        else:
            signal_result = None
        if placement_id is not None:
            cur.execute("SELECT * FROM placements WHERE id = %s", (placement_id,))
            placement_row = cur.fetchone()
            if placement_row is None:
                raise LedgerUnavailable("MISSING_PLACEMENT", "placement was not found")
            expected_placement = _quote_from_row(placement_row, line_key="achieved_line")
            placement_result = match_close(expected_placement, observed)
        else:
            placement_result = None
        reasons = [item.reason_code for item in (signal_result, placement_result) if item is not None and not item.matched]
        matched = not reasons and (signal_result is not None or placement_result is not None)
        if signal_result is not None and placement_result is not None:
            matched = signal_result.matched and placement_result.matched
        reason = None if matched else (reasons[0] if reasons else LINE_CHANGED)
        if observed.over_american_odds is None or observed.under_american_odds is None:
            if matched:
                matched = False
                reason = "INCOMPLETE_PRICE"
        cur.execute(
            """
            INSERT INTO closing_references (
              signal_id, placement_id, event_id, event_start_at, source_id, market,
              selection, line, settlement_rules, over_american_odds, under_american_odds,
              observed_at, match_status, reason_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, match_status, reason_code
            """,
            (
                signal_id, placement_id, observed.event_id,
                _event_start(cur, signal_id, placement_id),
                source_id.strip(), observed.market, observed.selection, Decimal(str(observed.line)),
                observed.settlement_rules, observed.over_american_odds, observed.under_american_odds,
                observed_at, "MATCHED" if matched else "UNMATCHED", None if matched else reason,
            ),
        )
        saved = cur.fetchone()
    conn.commit()
    return {
        "id": str(saved["id"]),
        "match_status": saved["match_status"],
        "reason_code": saved["reason_code"],
    }


def _event_start(cur, signal_id: str | None, placement_id: str | None):
    if signal_id is not None:
        cur.execute("SELECT event_start_at FROM prospective_signals WHERE id = %s", (signal_id,))
    else:
        cur.execute(
            """
            SELECT s.event_start_at
            FROM placements p
            JOIN prospective_signals s ON s.id = p.signal_id
            WHERE p.id = %s
            """,
            (placement_id,),
        )
    row = cur.fetchone()
    if row is None:
        raise LedgerUnavailable("MISSING_EVENT", "event_start_at is not on the ledger record")
    return row["event_start_at"]


def population_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM population_counts")
        row = cur.fetchone()
    return {key: int(row[key]) for key in row.keys()}


def public_chain(conn, passport_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT seq, event_type, prev_hash, integrity_hash
            FROM ledger_events
            WHERE passport_id = %s
            ORDER BY seq
            """,
            (passport_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]
    return {
        "passport_id": passport_id,
        "valid": verify_passport_chain(conn, passport_id),
        "events": rows,
    }


def count_rows(conn, table: str) -> int:
    if table not in {"attestations", "research_references", "prospective_signals", "historical_evidence_gaps", "placements"}:
        raise ValueError("unsupported count")
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return int(cur.fetchone()["n"])
