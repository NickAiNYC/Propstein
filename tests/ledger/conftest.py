"""Session-scoped Postgres for the ledger tests. No SQLite fallback."""

from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "ledger_foundation_test"


def _with_database(dsn: str, database: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _local_admin_dsn() -> str:
    for candidate in (
        "postgresql://postgres@localhost:5432/postgres",
        f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/postgres",
    ):
        try:
            conn = psycopg2.connect(candidate, connect_timeout=1)
            conn.close()
            return candidate
        except Exception:
            pass
    password = secrets.token_hex(16)
    subprocess.check_call(
        [
            "sudo", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
            "-c", f"ALTER USER postgres WITH PASSWORD '{password}'",
        ],
        stdout=subprocess.DEVNULL,
    )
    return f"postgresql://postgres:{quote_plus(password)}@127.0.0.1:5432/postgres"


@pytest.fixture(scope="session")
def ledger_db():
    from src.ledger.migrate import apply_migrations

    admin = os.environ.get("LEDGER_ADMIN_URL") or _local_admin_dsn()
    maintenance = psycopg2.connect(admin)
    maintenance.autocommit = True
    with maintenance.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if cur.fetchone():
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (DB_NAME,),
            )
            cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(DB_NAME)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
    maintenance.close()

    admin_dsn = _with_database(admin, DB_NAME)
    admin_conn = psycopg2.connect(admin_dsn)
    apply_migrations(admin_conn, root=ROOT)
    app_password = secrets.token_hex(16)
    with admin_conn.cursor() as cur:
        cur.execute(
            sql.SQL("ALTER ROLE propstein_app PASSWORD {}").format(sql.Literal(app_password))
        )
    admin_conn.commit()
    admin_conn.close()
    app_dsn = f"postgresql://propstein_app:{quote_plus(app_password)}@127.0.0.1:5432/{DB_NAME}"
    return {"admin": admin_dsn, "app": app_dsn, "root": ROOT}


@pytest.fixture(autouse=True)
def _app_database_url(ledger_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", ledger_db["app"])
    monkeypatch.setenv("PROPSTEIN_SNAPSHOT_DIR", str(ROOT / "snapshots"))


@pytest.fixture
def admin_conn(ledger_db):
    conn = psycopg2.connect(ledger_db["admin"], cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def app_conn(ledger_db):
    conn = psycopg2.connect(ledger_db["app"], cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
