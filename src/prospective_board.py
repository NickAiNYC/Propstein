"""Prospective full-board capture and conservative closing-price audit.

This is a research journal. A snapshot's ``verified`` label is not an
independent source receipt, and no row from this module is an executable pick.
Capture runs before kickoff and writes a new file exclusively; grading never
changes that file. Historical snapshots cannot be promoted by backdating a CLI
clock because the CLI always uses the actual UTC time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.crypto_utils import canonical_json_sha256


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp needs a UTC offset: {value}")
    return parsed.astimezone(timezone.utc)


def _legacy_snapshot_hash(row: dict[str, Any]) -> str:
    payload = {key: value for key, value in row.items() if key != "content_hash"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_new_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def classify_coverage_failure_reason(
    rows: list[dict[str, Any]],
    kickoffs: dict[str, datetime],
    now: datetime,
) -> tuple[str, str, dict[str, Any]]:
    """Distinguishes prospective capture failure causes for targeted alerting/retry policy:
    - ADAPTER_FAILURE: Zero quotes captured near kickoff (adapter down or broken feed)
    - PRE_POST: Early capture window where sportsbooks have not posted lines yet (>3h to kickoff)
    - PARTIAL_SLATE: Non-zero quotes from some books/games, but below required threshold
    """
    quoted = sum(1 for r in rows if r["decision"] != "PASS_NO_QUOTE")
    books = set()
    games_with_quotes = set()
    for r in rows:
        for obs in r.get("observations", []):
            if obs.get("book"):
                books.add(obs["book"])
                games_with_quotes.add(r["game_id"])

    min_mins_to_kickoff = min(
        [(kickoffs[r["game_id"]] - now).total_seconds() / 60.0 for r in rows if r["game_id"] in kickoffs],
        default=0.0,
    )

    meta = {
        "games_with_quotes": sorted(games_with_quotes),
        "active_books": sorted(books),
        "min_minutes_to_kickoff": round(min_mins_to_kickoff, 1),
    }

    if quoted == 0:
        if min_mins_to_kickoff > 180:
            return (
                "PRE_POST",
                f"Markets legitimately not posted yet ({min_mins_to_kickoff:.0f} mins to kickoff). Retry scheduled closer to kickoff.",
                meta,
            )
        else:
            return (
                "ADAPTER_FAILURE",
                f"Zero quotes captured within {min_mins_to_kickoff:.0f} mins of kickoff. Odds ingestion adapter failed or feed down.",
                meta,
            )
    else:
        return (
            "PARTIAL_SLATE",
            f"Partial quotes received from {len(books)} books across {len(games_with_quotes)} games, but total coverage is below threshold.",
            meta,
        )


def capture_board(
    snapshots_path: Path,
    kickoffs_path: Path,
    journal_path: Path,
    *,
    captured_at: datetime | None = None,
    game_id: str | None = None,
    min_coverage_rate: float | None = None,
    alert_dir: Path | None = None,
    require_active_quotes: bool = False,
) -> dict[str, Any]:
    """Lock every upcoming frozen player/market and all observed book quotes.

    ``kickoffs_path`` is an explicit game-id to offset-aware ISO kickoff map.
    The viewer's timezone-free ``gametime`` is deliberately not inferred.
    In-process ``captured_at`` injection exists for deterministic tests only.
    ``min_coverage_rate`` enforces a fail-closed threshold before committing a journal.
    ``require_active_quotes`` enforces roster INNER JOIN active_quotes, excluding unquoted pass candidates.
    """
    now = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if journal_path.exists():
        raise FileExistsError(f"journal already exists: {journal_path}")
    kickoffs_raw = json.loads(kickoffs_path.read_text(encoding="utf-8"))
    if not isinstance(kickoffs_raw, dict):
        raise ValueError("kickoffs must be a game_id to ISO timestamp object")
    kickoffs = {game_id: _utc(value) for game_id, value in kickoffs_raw.items()}

    snapshots = _read_jsonl(snapshots_path)
    if game_id is not None:
        snapshots = [snap for snap in snapshots if snap.get("game_id") == game_id]
        kickoffs = {key: value for key, value in kickoffs.items() if key == game_id}
    if not snapshots:
        raise ValueError("snapshot log is empty")
    for snap in snapshots:
        if snap.get("content_hash") != _legacy_snapshot_hash(snap):
            raise ValueError(f"invalid frozen snapshot hash: {snap.get('snapshot_id')}")
        if snap.get("game_id") not in kickoffs:
            raise ValueError(f"missing explicit kickoff for {snap.get('game_id')}")

    universe: dict[tuple[str, str, str], dict[str, Any]] = {}
    quote_history: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for snap in sorted(snapshots, key=lambda row: _utc(row["created_at"])):
        game_id = str(snap["game_id"])
        created = _utc(snap["created_at"])
        if created > now or created >= kickoffs[game_id]:
            continue
        key = (game_id, str(snap["player_id"]), str(snap["market"]))
        if snap.get("snapshot_type") == "pre_kickoff":
            universe[key] = snap
        quote = snap.get("quote") or {}
        if quote.get("line") is not None and quote.get("book"):
            quote_history[key][str(quote["book"])] = snap

    if not universe:
        raise ValueError("no frozen pre-kickoff candidate universe")
    missing_games = set(kickoffs) - {key[0] for key in universe}
    if missing_games:
        raise ValueError(f"scheduled games missing frozen candidate universe: {sorted(missing_games)}")
    rows: list[dict[str, Any]] = []
    skipped_games: set[str] = set()
    for key, base in sorted(universe.items()):
        game_id, player_id, market = key
        kickoff = kickoffs[game_id]
        if now >= kickoff:
            skipped_games.add(game_id)
            continue
        observations: list[dict[str, Any]] = []
        for book, snap in sorted(quote_history[key].items()):
            quote = snap["quote"]
            evaluation = quote.get("evaluation") or {}
            source_time = quote.get("observed_at")
            try:
                source_time_valid = bool(source_time) and _utc(source_time) <= now and _utc(source_time) < kickoff
            except (TypeError, ValueError):
                source_time_valid = False
            observations.append({
                "book": book,
                "line": quote["line"],
                "over_odds": quote.get("over_odds"),
                "under_odds": quote.get("under_odds"),
                "observed_at": quote.get("observed_at"),
                "snapshot_id": snap["snapshot_id"],
                "snapshot_hash": snap["content_hash"],
                "source_quote_id": quote.get("quote_id"),
                "source_status_claim": quote.get("status"),
                "source_time_status": "BEFORE_CAPTURE_AND_KICKOFF" if source_time_valid else "MISSING_INVALID_OR_FUTURE",
                "claimed_qualified": bool(evaluation.get("is_qualified")),
                "claimed_side": evaluation.get("best_side"),
                "receipt_status": "NO_INDEPENDENT_SOURCE_RECEIPT",
            })
        if require_active_quotes and not observations:
            continue
        payload = {
            "schema": "propstein.prospective_board.v1",
            "slate": base["slate"],
            "captured_at": now.isoformat(),
            "kickoff_at": kickoff.isoformat(),
            "game_id": game_id,
            "player_id": player_id,
            "player_name": base.get("player_name"),
            "market": market,
            "model_snapshot_id": base["snapshot_id"],
            "model_snapshot_hash": base["content_hash"],
            "model_version": (base.get("model") or {}).get("version"),
            "decision": "OBSERVED_RESEARCH_ONLY" if observations else "PASS_NO_QUOTE",
            "observations": observations,
        }
        payload["record_sha256"] = canonical_json_sha256(payload)
        rows.append(payload)
    if not rows:
        if require_active_quotes:
            reason_code, reason_detail, reason_meta = classify_coverage_failure_reason([], kickoffs, now)
            raise ValueError(
                f"Quote-gated capture rejected [{reason_code}]: {reason_detail} "
                f"Zero active quotes found across candidate roster universe."
            )
        raise ValueError("every game has kicked off; prospective capture refused")

    quoted_candidates = sum(1 for row in rows if row["decision"] != "PASS_NO_QUOTE")
    coverage_rate = quoted_candidates / len(rows) if rows else 0.0
    if min_coverage_rate is not None and coverage_rate < min_coverage_rate:
        reason_code, reason_detail, reason_meta = classify_coverage_failure_reason(rows, kickoffs, now)
        target_dir = alert_dir or (Path(__file__).resolve().parent.parent / "data" / "pipeline_alerts")
        target_dir.mkdir(parents=True, exist_ok=True)
        date_str = now.strftime("%Y%m%d_%H%M%S")
        alert_file = target_dir / f"{date_str}_low_coverage.json"
        alert_payload = {
            "timestamp": now.isoformat(),
            "candidate_count": len(rows),
            "quoted_candidate_count": quoted_candidates,
            "coverage_rate": round(coverage_rate, 4),
            "required_rate": min_coverage_rate,
            "status": "REJECTED_LOW_COVERAGE",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "metadata": reason_meta,
            "journal": str(journal_path),
            "reason": (
                f"Active quote coverage {coverage_rate:.1%} is below minimum required threshold "
                f"{min_coverage_rate:.1%} ({quoted_candidates}/{len(rows)} quoted). Reason: {reason_code} - {reason_detail}"
            ),
        }
        alert_file.write_text(json.dumps(alert_payload, indent=2), encoding="utf-8")
        raise ValueError(
            f"Journal rejected [{reason_code}]: {reason_detail} "
            f"Quote coverage {coverage_rate:.1%} < minimum required {min_coverage_rate:.1%}. "
            f"Alert written to {alert_file}"
        )

    _write_new_jsonl(journal_path, rows)
    return {
        "journal": str(journal_path),
        "captured_at": now.isoformat(),
        "candidate_count": len(rows),
        "pass_no_quote_count": sum(row["decision"] == "PASS_NO_QUOTE" for row in rows),
        "observed_quote_count": sum(len(row["observations"]) for row in rows),
        "skipped_already_started_games": sorted(skipped_games),
        "coverage": "PARTIAL_SLATE" if skipped_games else "FULL_UPCOMING_SLATE",
        "receipt_verification": "NOT_AVAILABLE",
    }


_CLOSE_HASH_FIELDS = (
    "event_id", "player_id", "book", "market", "closing_line",
    "closing_over_odds", "closing_under_odds", "closing_fair_line",
    "provider_event_id", "provider_update_ts", "raw_provider_payload_sha256",
)


def _valid_close(close: dict[str, Any], kickoff: datetime, captured_at: datetime) -> bool:
    try:
        if any(close.get(field) is None for field in _CLOSE_HASH_FIELDS):
            return False
        float(close["closing_line"])
        if any(abs(int(close[field])) < 100 for field in ("closing_over_odds", "closing_under_odds")):
            return False
        if close.get("closing_snapshot_sha256") != canonical_json_sha256({
            "schema": "propwire.closing_snapshot.v1",
            **{field: close[field] for field in _CLOSE_HASH_FIELDS},
        }):
            return False
        provider_ts = datetime.fromtimestamp(int(close["provider_update_ts"]) / 1000, timezone.utc)
        # A close must be newer than the locked decision and within 90 seconds
        # of kickoff. A T-5-minute lock is not a closing benchmark by itself.
        age_seconds = (kickoff - provider_ts).total_seconds()
        return captured_at <= provider_ts and 0 < age_seconds <= 90
    except (ValueError, TypeError, OverflowError):
        return False


def verify_journal(journal_path: Path) -> list[dict[str, Any]]:
    """Check local record integrity and pre-kickoff timing on every candidate."""
    rows = _read_jsonl(journal_path)
    if not rows:
        raise ValueError("journal is empty")
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        digest = row.get("record_sha256")
        if digest != canonical_json_sha256({k: v for k, v in row.items() if k != "record_sha256"}):
            raise ValueError(f"journal record hash mismatch: {row.get('player_id')}")
        if _utc(row["captured_at"]) >= _utc(row["kickoff_at"]):
            raise ValueError("journal contains a post-kickoff decision")
        key = (row["game_id"], row["player_id"], row["market"])
        if key in seen:
            raise ValueError(f"duplicate candidate in journal: {key}")
        seen.add(key)
    return rows


def grade_board(journal_path: Path, closes_path: Path) -> dict[str, Any]:
    """Audit exact-match close coverage; never promote a claimed quote to CLV.

    Even a hash-valid close is only an internally recorded close. Until an
    independent entry receipt exists, numeric CLV and beat-close are withheld.
    """
    rows = verify_journal(journal_path)
    closes = json.loads(closes_path.read_text(encoding="utf-8"))
    if not isinstance(closes, list):
        raise ValueError("closes must be a JSON array")
    close_index: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for close in closes:
        key = tuple(str(close.get(field, "")) for field in ("event_id", "player_id", "book", "market"))
        close_index[key].append(close)

    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        if not row["observations"]:
            counts["PASS_NO_QUOTE"] += 1
            results.append({"game_id": row["game_id"], "player_id": row["player_id"],
                            "market": row["market"], "status": "PASS_NO_QUOTE"})
        for obs in row["observations"]:
            key = (row["game_id"], row["player_id"], obs["book"], row["market"])
            matches = close_index.get(key, [])
            valid = [close for close in matches if _valid_close(
                close, _utc(row["kickoff_at"]), _utc(row["captured_at"]))]
            if len(valid) != 1:
                status = "MISSING_CLOSE" if not matches else "UNVERIFIED_OR_AMBIGUOUS_CLOSE"
            elif float(valid[0]["closing_line"]) != float(obs["line"]):
                status = "LINE_CHANGED_NO_EXACT_PRICE_COMPARISON"
            else:
                status = "UNVERIFIED_ENTRY_RECEIPT"
            counts[status] += 1
            results.append({"game_id": row["game_id"], "player_id": row["player_id"],
                            "market": row["market"], "book": obs["book"], "status": status,
                            "entry_snapshot_hash": obs["snapshot_hash"],
                            "close_snapshot_hash": valid[0]["closing_snapshot_sha256"] if len(valid) == 1 else None})
    return {
        "schema": "propstein.prospective_board_audit.v1",
        "candidate_count": len(rows),
        "quote_observation_count": sum(len(row["observations"]) for row in rows),
        "status_counts": dict(sorted(counts.items())),
        "verified_clv_sample_size": 0,
        "beat_close_rate": None,
        "average_clv": None,
        "promotion_status": "BLOCKED_NO_INDEPENDENT_ENTRY_RECEIPTS",
        "rows": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prospective full-board research journal")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--snapshots", type=Path, required=True)
    capture.add_argument("--kickoffs", type=Path, required=True)
    capture.add_argument("--journal", type=Path, required=True)
    capture.add_argument("--game-id", help="Capture only one scheduled game")
    grade = sub.add_parser("audit-closes")
    grade.add_argument("--journal", type=Path, required=True)
    grade.add_argument("--closes", type=Path, required=True)
    grade.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-journal")
    verify.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        result = capture_board(args.snapshots, args.kickoffs, args.journal, game_id=args.game_id)
    elif args.command == "audit-closes":
        result = grade_board(args.journal, args.closes)
        if args.output.exists():
            raise FileExistsError(f"audit already exists: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    else:
        result = {"journal": str(args.journal), "candidate_count": len(verify_journal(args.journal))}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
