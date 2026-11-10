"""PropStein pipeline — output sanity gate (Phase 4 build breaker).

A run that produces an empty board, NaN values, a collapsed row count, or a
board whose newest event is older than the freshness ceiling is INVALID and
must fail the build. The validator re-derives every invariant from the stored
artifact (never trusts the generator's in-memory state).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from pipeline import config
from pipeline.schemas import RunArtifact

MAX_NAN_SCAN_DEPTH = 12


@dataclass
class ValidationReport:
    ok: bool
    checks: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str) -> bool:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.ok = False
        return passed


def _categorical_value(v) -> str:
    """Enum or raw string (disk-tamper path) -> plain string."""
    return v.value if hasattr(v, "value") else str(v)


def find_nan(value: object, path: str = "$", depth: int = 0) -> list[str]:
    """Deep scan for NaN / Infinity anywhere in a JSON-compatible structure."""
    hits: list[str] = []
    if depth > MAX_NAN_SCAN_DEPTH:
        return hits
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            hits.append(path)
    elif isinstance(value, dict):
        for k, v in value.items():
            hits.extend(find_nan(v, f"{path}.{k}", depth + 1))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            hits.extend(find_nan(v, f"{path}[{i}]", depth + 1))
    elif isinstance(value, str):
        low = value.strip().lower()
        if low in ("nan", "infinity", "-infinity", "none", "null") and path.endswith((".probability", ".lower", ".upper", ".line")):
            hits.append(path)
    return hits


def validate_artifact(artifact: RunArtifact) -> ValidationReport:
    report = ValidationReport(ok=True)

    # 1. Non-empty board
    report.add(
        "predictions_non_empty",
        len(artifact.predictions) > 0,
        f"{len(artifact.predictions)} predictions",
    )

    # 2. Row count above threshold
    report.add(
        "row_count_threshold",
        len(artifact.predictions) >= config.MIN_PREDICTIONS,
        f"{len(artifact.predictions)} >= {config.MIN_PREDICTIONS}",
    )

    # 3. Distinct events above threshold
    n_events = len({p.event_id for p in artifact.predictions})
    report.add(
        "event_count_threshold",
        n_events >= config.MIN_EVENTS,
        f"{n_events} >= {config.MIN_EVENTS}",
    )

    # 4. No NaN / Inf anywhere in the serialized artifact
    doc = json.loads(artifact.model_dump_json())
    nan_hits = find_nan(doc)
    report.add("no_nan_values", not nan_hits, ", ".join(nan_hits[:5]) or "clean")

    # 5. Series integrity: dates strictly increasing, all prior to run_date
    series_ok = True
    series_detail = "clean"
    for p in artifact.predictions:
        dates = [s.run_date for s in p.series]
        if dates != sorted(dates) or any(d >= artifact.run_date for d in dates):
            series_ok = False
            series_detail = f"bad series on {p.board_key}"
            break
    report.add("series_integrity", series_ok, series_detail)

    # 6. Board horizon: at least one event commencing within the ceiling
    try:
        commencing = sorted(p.commences_at_utc for p in artifact.predictions)
        from datetime import datetime

        newest = datetime.strptime(commencing[-1], "%Y-%m-%dT%H:%M:%SZ")
        run_day = datetime.strptime(artifact.run_date, "%Y-%m-%d")
        age_hours = (newest - run_day).total_seconds() / 3600.0
        horizon_ok = age_hours <= (config.BOARD_HORIZON_DAYS + 1) * 24.0
        report.add(
            "board_horizon_fresh",
            horizon_ok,
            f"newest event {commencing[-1]} ({age_hours:.0f}h after run day)",
        )
    except (ValueError, IndexError):
        report.add("board_horizon_fresh", False, "unparsable commences timestamps")

    # 7. Categorical vocabulary: every assessment is one of the nine allowed
    from pipeline.schemas import PriceAssessment

    allowed = {a.value for a in PriceAssessment}
    bad_cats = [
        _categorical_value(p.price_assessment)
        for p in artifact.predictions
        if _categorical_value(p.price_assessment) not in allowed
    ]
    report.add("categorical_vocabulary", not bad_cats, ", ".join(sorted(set(bad_cats))[:3]) or "clean")

    # 8. Calibrated rows always carry numbers; uncalibrated rows never do
    numbers_ok = True
    for p in artifact.predictions:
        if p.model.coverage.value == "calibrated" and (p.model.probability is None or p.model.uncertainty is None):
            numbers_ok = False
            break
        if p.model.coverage.value != "calibrated" and p.model.probability is not None:
            numbers_ok = False
            break
    report.add("coverage_number_policy", numbers_ok, "clean" if numbers_ok else "mismatch")

    # 9. Integrity hash re-derivation
    from pipeline.runs import compute_integrity_hash

    report.add(
        "integrity_hash",
        compute_integrity_hash(artifact) == artifact.integrity_hash,
        "re-derived match" if compute_integrity_hash(artifact) == artifact.integrity_hash else "MISMATCH",
    )

    return report


def validate_latest_json(path=None) -> ValidationReport:
    """Validate the stored latest_predictions.json from disk (end state)."""
    from pipeline.runs import ArtifactCorruptError, load_run

    target = path or config.LATEST_PATH
    try:
        with open(target, encoding="utf-8") as fh:
            doc = json.load(fh)
        artifact = RunArtifact.model_validate(doc)
    except FileNotFoundError:
        report = ValidationReport(ok=False)
        report.add("artifact_readable", False, f"{target} missing")
        return report
    except (json.JSONDecodeError, ArtifactCorruptError, Exception) as exc:
        report = ValidationReport(ok=False)
        report.add("artifact_readable", False, f"{target}: {exc}")
        return report

    report = validate_artifact(artifact)
    report.add("artifact_readable", True, f"{target} parsed and schema-validated")
    return report


__all__ = ["ValidationReport", "find_nan", "validate_artifact", "validate_latest_json"]
