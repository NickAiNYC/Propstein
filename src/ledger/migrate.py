"""Apply the ledger migration and register the current pre-registration artifact."""

from __future__ import annotations

import re
from pathlib import Path

import psycopg2

from src.ledger.gates import read_independent_gates
from src.ledger.registry import RELEASE_ID, artifact_bytes, artifact_sha256

_MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
MIGRATIONS = (
    ("001_ledger_foundation", _MIGRATIONS / "001_ledger_foundation.sql"),
    ("002_amend001_nfl_event_key", _MIGRATIONS / "002_amend001_nfl_event_key.sql"),
)


def split_sql(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    dollar: str | None = None
    index = 0
    while index < len(script):
        if dollar is not None:
            if script.startswith(dollar, index):
                buf.append(dollar)
                index += len(dollar)
                dollar = None
                continue
            buf.append(script[index])
            index += 1
            continue
        marker = re.match(r"\$[A-Za-z0-9_]*\$", script[index:])
        if script[index] == "$" and marker:
            dollar = marker.group(0)
            buf.append(dollar)
            index += len(dollar)
            continue
        if script[index] == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            index += 1
            continue
        buf.append(script[index])
        index += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _applied(conn) -> set[str]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            return {row[0] for row in cur.fetchall()}
    except psycopg2.Error:
        conn.rollback()
        return set()


def apply_migrations(conn, *, root: Path) -> None:
    applied = _applied(conn)
    for version, path in MIGRATIONS:
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            for statement in split_sql(script):
                cur.execute(statement)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (version,),
            )
        conn.commit()
        applied.add(version)
    ensure_registration(conn)
    seed_gate_flags(conn, root)
    conn.commit()


def ensure_registration(conn) -> str:
    """Insert the committed artifact once. registered_at is the database clock."""
    digest = artifact_sha256()
    text = artifact_bytes().decode("utf-8")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM rule_registrations WHERE artifact_sha256 = %s",
            (digest,),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        cur.execute("SELECT count(*) FROM rule_registrations")
        existing = cur.fetchone()[0]
        if existing:
            raise RuntimeError(
                "active registry does not match the committed artifact; "
                "a new registration row must be inserted explicitly"
            )
        cur.execute(
            """
            INSERT INTO rule_registrations (release_id, artifact_sha256, artifact_canonical)
            VALUES (%s, %s, %s)
            RETURNING id, registered_at
            """,
            (RELEASE_ID, digest, text),
        )
        inserted = cur.fetchone()
        return str(inserted[0])


def seed_gate_flags(conn, root: Path) -> None:
    flags = read_independent_gates(root)
    with conn.cursor() as cur:
        for name, payload in flags.items():
            cur.execute(
                "SELECT 1 FROM gate_flag_events WHERE flag_name = %s",
                (name,),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO gate_flag_events (flag_name, passed, basis)
                VALUES (%s, %s, %s)
                """,
                (name, payload["passed"], payload["basis"]),
            )
