"""AMEND-001 mapping, rejection reasons, idempotent import, and the gate count."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import pytest

from src.crypto_utils import canonical_json_sha256
from src.ledger.amend001 import (
    AMENDMENT_ID,
    DOCUMENT_PATH,
    EFFECTIVE_AT,
    _source_name,
    classify_journal_row,
    import_prospective_journals,
    nfl_confirmatory_count,
)
from src.ledger.language import find_forbidden
from src.ledger.store import import_signal_row

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = "snapshots/full_board_2026_w8_early_1300.jsonl"


def _row(**overrides):
    row = {
        "schema": "propstein.prospective_board.v1",
        "captured_at": "2026-11-02T17:00:00+00:00",
        "kickoff_at": "2026-11-02T18:00:00+00:00",
        "game_id": "2026_10_AAA_BBB",
        "player_id": "player-1",
        "player_name": "Ada",
        "market": "receptions",
        "model_version": "from-the-row",
        "provider_event_id": "PROV-9",
        "observations": [],
    }
    row.update(overrides)
    if "record_sha256" not in overrides:
        body = {key: value for key, value in row.items() if key != "record_sha256"}
        row["record_sha256"] = canonical_json_sha256(body)
    return row


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "full_board_unit.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_amendment_is_registered_and_prospective(admin_conn):
    digest = hashlib.sha256((ROOT / DOCUMENT_PATH).read_bytes()).hexdigest()
    with admin_conn.cursor() as cur:
        cur.execute("SELECT * FROM protocol_amendments WHERE amendment_id = %s", (AMENDMENT_ID,))
        amendment = cur.fetchone()
        cur.execute("SELECT family FROM rule_registry WHERE rule_id = %s", (AMENDMENT_ID,))
        rule = cur.fetchone()
        cur.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'prospective_signals'
              AND column_name IN ('provider_event_id', 'amendment_id')
            """
        )
        columns = {row["column_name"]: row["is_nullable"] for row in cur.fetchall()}
    assert amendment["sport"] == "NFL"
    assert amendment["prospective_only"] is True
    assert amendment["document_sha256"] == digest
    assert amendment["effective_at"] == EFFECTIVE_AT
    assert rule["family"] == "protocol"
    assert columns == {"provider_event_id": "YES", "amendment_id": "YES"}
    with pytest.raises(psycopg2.Error):
        with admin_conn.cursor() as cur:
            cur.execute("UPDATE protocol_amendments SET summary = 'rewritten'")
    admin_conn.rollback()


def test_mapping_uses_game_id_and_captured_kickoff():
    row = _row()
    decision = classify_journal_row(row, source_name="unit", locator="line:1")
    assert decision.kind == "import"
    mapped = decision.mapped
    assert mapped is not None
    assert mapped.event_id == "2026_10_AAA_BBB"
    assert mapped.game_id == mapped.event_id
    assert mapped.provider_event_id == "PROV-9"
    assert mapped.event_id != mapped.provider_event_id
    assert mapped.event_start_at == datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    assert mapped.captured_at == datetime(2026, 11, 2, 17, tzinfo=timezone.utc)
    assert mapped.amendment_id == AMENDMENT_ID
    assert mapped.source_record_sha256 == row["record_sha256"]
    assert "event_id" not in mapped.payload
    assert mapped.payload["game_id"] == "2026_10_AAA_BBB"


def test_absent_provider_id_stays_null():
    row = _row()
    del row["provider_event_id"]
    row.pop("record_sha256", None)
    row["record_sha256"] = canonical_json_sha256(row)
    # The hash above included a placeholder key. Recompute from the body only.
    body = {key: value for key, value in row.items() if key != "record_sha256"}
    row["record_sha256"] = canonical_json_sha256(body)
    decision = classify_journal_row(row, source_name="unit", locator="line:1")
    assert decision.kind == "import"
    assert decision.mapped is not None
    assert decision.mapped.provider_event_id is None


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row.pop("game_id"), "missing_game_id"),
        (lambda row: row.pop("kickoff_at"), "missing_kickoff_at"),
        (lambda row: row.__setitem__("kickoff_at", "2026-11-02T18:00:00"), "naive_timestamp"),
        (lambda row: row.__setitem__("captured_at", "2026-11-02T17:00:00"), "naive_timestamp"),
        (lambda row: row.__setitem__("captured_at", row["kickoff_at"]), "decision_at_or_after_kickoff"),
        (lambda row: row.__setitem__("captured_at", "2026-11-02T19:00:00+00:00"), "decision_at_or_after_kickoff"),
        (lambda row: row.__setitem__("record_sha256", "ab" * 32), "record_sha256_mismatch"),
        (lambda row: row.pop("record_sha256"), "missing_record_sha256"),
        (lambda row: row.__setitem__("schema", "paper.backtest.v0"), "schema_not_prospective_journal"),
    ],
)
def test_rejection_reasons(mutate, reason):
    row = _row()
    mutate(row)
    if reason != "record_sha256_mismatch" and reason != "missing_record_sha256" and "record_sha256" in row:
        body = {key: value for key, value in row.items() if key != "record_sha256"}
        row["record_sha256"] = canonical_json_sha256(body)
    decision = classify_journal_row(row, source_name="unit", locator="line:1")
    assert decision.kind == "reject"
    assert reason in decision.reasons
    assert decision.mapped is None


def test_rows_before_effective_date_are_not_imported(app_conn, tmp_path):
    row = _row(captured_at="2026-10-31T23:00:00+00:00", kickoff_at="2026-11-01T18:00:00+00:00")
    path = _write(tmp_path, [row])
    source_name = _source_name(path, ROOT)
    before_gaps = _gap_count(app_conn, source_name)
    report = import_prospective_journals(app_conn, ROOT, sources=[path])
    assert report["imported"] == 0
    assert report["excluded_before_effective_date"] == 1
    assert report["rejected_rows"] == 0
    assert _gap_count(app_conn, source_name) == before_gaps
    assert _signal_count(app_conn, source_name) == 0


def test_historical_cohort_file_is_not_imported(app_conn):
    path = ROOT / "viewer" / "clv_report_2026_w7.json"
    before_gaps = _gap_count(app_conn, "viewer/clv_report_2026_w7.json")
    before_signals = _signal_count(app_conn, "viewer/clv_report_2026_w7.json")
    report = import_prospective_journals(app_conn, ROOT, sources=[path])
    assert report["imported"] == 0
    assert report["excluded_historical_cohort_files"] == 1
    assert _gap_count(app_conn, "viewer/clv_report_2026_w7.json") == before_gaps
    assert _signal_count(app_conn, "viewer/clv_report_2026_w7.json") == before_signals
    snapshot = ROOT / "snapshots" / "snapshots_2026_w7.jsonl"
    snap_report = import_prospective_journals(app_conn, ROOT, sources=[snapshot])
    assert snap_report["imported"] == 0
    assert snap_report["excluded_historical_cohort_files"] == 1
    assert _signal_count(app_conn, "snapshots/snapshots_2026_w7.jsonl") == 0


def test_rejected_row_is_gap_tabled_without_event_columns(app_conn, tmp_path):
    row = _row()
    row.pop("game_id")
    body = {key: value for key, value in row.items() if key != "record_sha256"}
    row["record_sha256"] = canonical_json_sha256(body)
    path = _write(tmp_path, [row])
    source_name = _source_name(path, ROOT)
    report = import_prospective_journals(app_conn, ROOT, sources=[path])
    assert report["imported"] == 0
    assert report["rejected_by_reason"]["missing_game_id"] == 1
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, event_start_at, missing_fields
            FROM historical_evidence_gaps
            WHERE source_name = %s
            """,
            (source_name,),
        )
        stored = cur.fetchone()
    assert stored["event_id"] is None
    assert stored["event_start_at"] is None
    assert "missing_game_id" in stored["missing_fields"]
    assert _signal_count(app_conn, source_name) == 0


def test_import_is_idempotent_and_append_only(app_conn, tmp_path):
    row = _row(game_id="2026_10_CCC_DDD", player_id="player-idem")
    path = _write(tmp_path, [row])
    first = import_prospective_journals(app_conn, ROOT, sources=[path])
    assert first["imported"] == 1
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, event_start_at, provider_event_id, amendment_id,
                   source_name, source_record_sha256, game_id
            FROM prospective_signals
            WHERE source_record_sha256 = %s
            """,
            (row["record_sha256"],),
        )
        stored = cur.fetchone()
    assert stored["event_id"] == "2026_10_CCC_DDD"
    assert stored["game_id"] == stored["event_id"]
    assert stored["provider_event_id"] == "PROV-9"
    assert stored["event_id"] != stored["provider_event_id"]
    assert stored["amendment_id"] == AMENDMENT_ID
    assert stored["source_name"] == _source_name(path, ROOT)
    assert stored["source_record_sha256"] == row["record_sha256"]
    assert stored["event_start_at"] == datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    second = import_prospective_journals(app_conn, ROOT, sources=[path])
    assert second["imported"] == 0
    assert second["already_imported"] == 1
    assert _signal_count(app_conn, _source_name(path, ROOT)) == 1
    with pytest.raises(psycopg2.Error):
        with app_conn.cursor() as cur:
            cur.execute(
                "UPDATE prospective_signals SET event_id = provider_event_id WHERE source_record_sha256 = %s",
                (row["record_sha256"],),
            )
    app_conn.rollback()
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT event_id FROM prospective_signals WHERE source_record_sha256 = %s",
            (row["record_sha256"],),
        )
        assert cur.fetchone()["event_id"] == "2026_10_CCC_DDD"


def test_generic_importer_still_does_not_reconstruct(app_conn):
    row = _row(player_id="generic-gap")
    assert import_signal_row(
        app_conn,
        row=row,
        cohort="prospective_full_board",
        source_name="generic-still-gaps",
        locator="line:1",
    ) == "gap"


def test_real_journal_counts_and_gate_view(app_conn):
    source = ROOT / JOURNAL
    first = import_prospective_journals(app_conn, ROOT, sources=[source])
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)::int AS n,
                   count(*) FILTER (WHERE event_id = game_id)::int AS clustered_on_game,
                   count(*) FILTER (WHERE provider_event_id IS NULL)::int AS provider_null,
                   count(*) FILTER (WHERE amendment_id = 'AMEND-001')::int AS amended,
                   bool_and(event_start_at = '2026-11-01T18:00:00+00:00') AS kickoff
            FROM population_committed_forecasts
            WHERE source_name = %s
            """,
            (JOURNAL,),
        )
        stored = cur.fetchone()
        cur.execute("SELECT count(*)::int AS n FROM population_nfl_confirmatory WHERE source_name = %s", (JOURNAL,))
        view_count = cur.fetchone()["n"]
    assert stored["n"] == 472
    assert stored["clustered_on_game"] == 472
    assert stored["provider_null"] == 472
    assert stored["amended"] == 472
    assert stored["kickoff"] is True
    assert view_count == 472
    assert first["imported"] + first["already_imported"] == 472
    assert first["rejected_rows"] == 0
    assert first["rejected_by_reason"] == {}
    assert first["excluded_before_effective_date"] == 0
    second = import_prospective_journals(app_conn, ROOT, sources=[source])
    assert second["imported"] == 0
    assert second["already_imported"] == 472
    assert nfl_confirmatory_count(app_conn) >= 472
    assert second["nfl_confirmatory_count"] == nfl_confirmatory_count(app_conn)


def test_gate_counter_sql_reads_the_view(app_conn, tmp_path):
    before = nfl_confirmatory_count(app_conn)
    row = _row(game_id="2026_10_EEE_FFF", player_id="gate-player")
    report = import_prospective_journals(app_conn, ROOT, sources=[_write(tmp_path, [row])])
    assert report["imported"] == 1
    assert report["nfl_confirmatory_count"] == before + 1
    assert nfl_confirmatory_count(app_conn) == before + 1
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)::int AS n
            FROM population_committed_forecasts
            WHERE amendment_id = 'AMEND-001' AND source_name = 'source-that-does-not-exist'
            """
        )
        assert cur.fetchone()["n"] == 0


def test_terminal_language_and_gate_sql_shape():
    roots = [
        ROOT / "terminal" / "lib" / "data" / "research-board.ts",
        ROOT / "terminal" / "app" / "research",
        ROOT / "terminal" / "components" / "research",
    ]
    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))
        for path in paths:
            hits = find_forbidden(path.read_text(encoding="utf-8"))
            if hits:
                offenders.append(f"{path}:{hits}")
            text = path.read_text(encoding="utf-8")
            assert "negbin-gamma-v3.2" not in text
            assert "__mock" not in text
    assert offenders == []
    sql = (ROOT / "terminal" / "lib" / "data" / "research-board.ts").read_text(encoding="utf-8")
    assert "population_committed_forecasts" in sql
    assert "AMEND-001" in sql
    assert "model_probability" not in sql
    assert "model_vs_close" not in sql


def _gap_count(conn, source_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*)::int AS n FROM historical_evidence_gaps WHERE source_name = %s",
            (source_name,),
        )
        return int(cur.fetchone()["n"])


def _signal_count(conn, source_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*)::int AS n FROM prospective_signals WHERE source_name = %s",
            (source_name,),
        )
        return int(cur.fetchone()["n"])
