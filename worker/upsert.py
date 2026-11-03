"""Propstein 2.0 — atomic chunked upsert core (psycopg3, Postgres/Supabase).

Fail-closed: no DATABASE_URL -> exit 2. Upstream fetch error -> exit 3.
DB write error -> exit 5. Success -> exit 0.

Every ingest script funnels through upsert_rows(): chunked
INSERT ... ON CONFLICT DO UPDATE with parameter binding — row-level
locks only, never LOCK TABLE.
"""

import os
import sys

import psycopg

CHUNK = 200

EXIT_OK = 0
EXIT_NO_DB = 2
EXIT_UPSTREAM = 3
EXIT_DB = 5


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("FATAL: DATABASE_URL is not set (fail-closed)", file=sys.stderr)
        sys.exit(EXIT_NO_DB)
    # Supabase pgbouncer-safe: no prepared statement cache pooling issues
    # with psycopg3 pipeline; keep it simple and explicit.
    return psycopg.connect(url, autocommit=False)


def upsert_rows(cur, table: str, rows: list[dict], pk_cols: list[str],
                update_cols: list[str] | None = None, chunk: int = CHUNK) -> int:
    """Chunked INSERT ... ON CONFLICT (pk) DO UPDATE. Returns row count."""
    if not rows:
        return 0
    all_cols = list(rows[0].keys())
    update_cols = update_cols or [c for c in all_cols if c not in pk_cols]
    written = 0
    for start in range(0, len(rows), chunk):
        batch = rows[start:start + chunk]
        col_sql = ", ".join(all_cols)
        ph = ", ".join(["%s"] * len(all_cols))
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        conflict = ", ".join(pk_cols)
        sql = (
            f"INSERT INTO {table} ({col_sql}) VALUES ({ph}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {sets}"
        )
        cur.executemany(sql, [tuple(r[c] for c in all_cols) for r in batch])
        written += len(batch)
    return written


def jsonb(v):
    """psycopg3 needs explicit Json wrapper for jsonb columns."""
    from psycopg.types.json import Json
    return None if v is None else Json(v)


def finish(conn, ok: bool):
    if ok:
        conn.commit()
    else:
        conn.rollback()
    conn.close()
