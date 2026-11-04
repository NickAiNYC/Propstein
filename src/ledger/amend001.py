"""AMEND-001 importer for prospective NFL journal rows.

event_id is the captured nflverse game_id. event_start_at is the captured
kickoff_at. provider_event_id is copied only when the source row has that
field. Rows before the effective instant, and the Week 7 37-row cohort, are
not imported. Nothing here updates or deletes an existing ledger row.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.crypto_utils import canonical_json_sha256
from src.ledger.store import _insert_gap, insert_amended_signal

AMENDMENT_ID = "AMEND-001"
EFFECTIVE_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)
JOURNAL_SCHEMA = "propstein.prospective_board.v1"
DOCUMENT_PATH = "docs/protocol_amendments/AMEND-001-nfl-event-key.md"

# These sources stay in the historical gap inventory. This importer does not
# read them into prospective_signals.
EXCLUDED_SOURCES = frozenset({
    "viewer/clv_report_2026_w7.json",
    "viewer/clv_audit_report.json",
    "public/clv_audit_report.json",
    "viewer/ufc_ledger.json",
    "snapshots/snapshots_2026_w1.jsonl",
    "snapshots/snapshots_2026_w7.jsonl",
    "snapshots/snapshots_2026_w8.jsonl",
})

_REASON_ORDER = (
    "schema_not_prospective_journal",
    "missing_game_id",
    "missing_kickoff_at",
    "missing_decision_timestamp",
    "naive_timestamp",
    "decision_at_or_after_kickoff",
    "missing_record_sha256",
    "record_sha256_mismatch",
    "unreadable_row",
)

_GATE_SQL_RE = re.compile(r"export const GATE_COUNT_SQL = `([^`]+)`", re.S)
_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MappedSignal:
    event_id: str
    event_start_at: datetime
    provider_event_id: str | None
    amendment_id: str
    source_name: str
    source_record_sha256: str
    game_id: str
    player_id: str | None
    market: str | None
    model_version: str | None
    payload: dict
    captured_at: datetime


@dataclass(frozen=True)
class RowDecision:
    kind: str
    reasons: tuple[str, ...]
    mapped: MappedSignal | None


def gate_count_sql() -> str:
    """The confirmatory count query shipped in the terminal data layer."""
    source = (_ROOT / "terminal" / "lib" / "data" / "research-board.ts").read_text(encoding="utf-8")
    match = _GATE_SQL_RE.search(source)
    if match is None:
        raise RuntimeError("terminal gate count SQL is missing")
    sql = match.group(1).strip()
    if "population_committed_forecasts" not in sql or AMENDMENT_ID not in sql:
        raise RuntimeError("terminal gate count SQL does not read the prospective full board")
    return sql


def nfl_confirmatory_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(gate_count_sql())
        return int(cur.fetchone()["n"])


def discover_journals(root: Path) -> list[Path]:
    directory = root / "snapshots"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("full_board_*.jsonl"))


def _source_name(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_timestamp(value: object) -> tuple[str, datetime | None]:
    if not isinstance(value, str) or not value.strip():
        return "missing", None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return "unparseable", None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return "naive", None
    return "ok", parsed.astimezone(timezone.utc)


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def classify_journal_row(row: dict, *, source_name: str, locator: str) -> RowDecision:
    """Map one journal row, or refuse it. Does not invent missing fields."""
    del locator
    captured_status, captured_at = _parse_timestamp(row.get("captured_at"))
    if captured_status == "ok" and captured_at is not None and captured_at < EFFECTIVE_AT:
        return RowDecision("exclude", ("before_effective_date",), None)

    reasons: list[str] = []
    if row.get("schema") != JOURNAL_SCHEMA:
        reasons.append("schema_not_prospective_journal")

    game_id = _optional_text(row.get("game_id"))
    if game_id is None:
        reasons.append("missing_game_id")

    kickoff_status, kickoff_at = _parse_timestamp(row.get("kickoff_at"))
    if kickoff_status in ("missing", "unparseable"):
        reasons.append("missing_kickoff_at")
    if captured_status in ("missing", "unparseable"):
        reasons.append("missing_decision_timestamp")
    if "naive" in (captured_status, kickoff_status):
        reasons.append("naive_timestamp")
    if (
        captured_status == "ok"
        and kickoff_status == "ok"
        and captured_at is not None
        and kickoff_at is not None
        and captured_at >= kickoff_at
    ):
        reasons.append("decision_at_or_after_kickoff")

    digest = row.get("record_sha256")
    body = {key: value for key, value in row.items() if key != "record_sha256"}
    if not isinstance(digest, str) or not digest.strip():
        reasons.append("missing_record_sha256")
    elif digest != canonical_json_sha256(body):
        reasons.append("record_sha256_mismatch")

    ordered = tuple(reason for reason in _REASON_ORDER if reason in reasons)
    if ordered or game_id is None or captured_at is None or kickoff_at is None:
        return RowDecision("reject", ordered, None)

    provider = _optional_text(row.get("provider_event_id"))
    mapped = MappedSignal(
        event_id=game_id,
        event_start_at=kickoff_at,
        provider_event_id=provider,
        amendment_id=AMENDMENT_ID,
        source_name=source_name,
        source_record_sha256=str(digest),
        game_id=game_id,
        player_id=_optional_text(row.get("player_id")),
        market=_optional_text(row.get("market")),
        model_version=_optional_text(row.get("model_version")),
        payload=row,
        captured_at=captured_at,
    )
    return RowDecision("import", (), mapped)


def _empty_report() -> dict:
    return {
        "imported": 0,
        "already_imported": 0,
        "rejected_rows": 0,
        "rejected_by_reason": {},
        "excluded_before_effective_date": 0,
        "excluded_historical_cohort_files": 0,
        "nfl_confirmatory_count": 0,
    }


def import_prospective_journals(conn, root: Path, *, sources: list[Path] | None = None) -> dict:
    """Append eligible journal rows. A second call inserts nothing new."""
    report = _empty_report()
    reasons: Counter[str] = Counter()
    paths = discover_journals(root) if sources is None else list(sources)
    for path in paths:
        source_name = _source_name(path, root)
        if source_name in EXCLUDED_SOURCES or path.name in {item.rsplit("/", 1)[-1] for item in EXCLUDED_SOURCES}:
            report["excluded_historical_cohort_files"] += 1
            continue
        if not path.is_file():
            continue
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            locator = f"line:{index}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                reasons["unreadable_row"] += 1
                report["rejected_rows"] += 1
                continue
            if not isinstance(row, dict):
                reasons["unreadable_row"] += 1
                report["rejected_rows"] += 1
                continue
            decision = classify_journal_row(row, source_name=source_name, locator=locator)
            if decision.kind == "exclude":
                report["excluded_before_effective_date"] += 1
                continue
            if decision.kind != "import" or decision.mapped is None:
                report["rejected_rows"] += 1
                for reason in decision.reasons:
                    reasons[reason] += 1
                _insert_gap(
                    conn,
                    row=row,
                    source_name=source_name,
                    locator=locator,
                    cohort="prospective_full_board",
                    missing=list(decision.reasons),
                )
                continue
            mapped = decision.mapped
            status = insert_amended_signal(
                conn,
                event_id=mapped.event_id,
                event_start_at=mapped.event_start_at,
                provider_event_id=mapped.provider_event_id,
                amendment_id=mapped.amendment_id,
                source_name=mapped.source_name,
                source_record_sha256=mapped.source_record_sha256,
                game_id=mapped.game_id,
                player_id=mapped.player_id,
                market=mapped.market,
                model_version=mapped.model_version,
                payload=mapped.payload,
                captured_at=mapped.captured_at,
            )
            report[status] += 1
    report["rejected_by_reason"] = {key: reasons[key] for key in _REASON_ORDER if reasons[key]}
    report["nfl_confirmatory_count"] = nfl_confirmatory_count(conn)
    return report
