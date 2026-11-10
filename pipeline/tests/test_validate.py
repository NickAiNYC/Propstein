"""Validator contracts: NaN deep scan, thresholds, vocabulary, hash."""

from __future__ import annotations

import math

from pipeline.schemas import Coverage
from pipeline.tests.fixtures import minimal_prediction
from pipeline.validate import find_nan, validate_artifact


def _artifact_with(predictions):
    from pipeline.engine import build_run  # noqa: F401  (ensure importable)
    from pipeline.schemas import (
        CoverageMix,
        DeltaStats,
        ExecutionStage,
        ModelInfo,
        RunArtifact,
        RunMetrics,
    )

    return RunArtifact(
        run_date="2026-11-08",
        run_id="2026-11-08-1100Z",
        generated_at_utc="2026-11-08T11:00:00Z",
        pipeline_version="test",
        source="synthetic",
        odds_provider="p",
        stats_provider="p",
        seed=20261024,
        models=[
            ModelInfo(
                model_name="m",
                model_version="v1",
                sport="NFL",
                market="player_reception_yds",
                coverage=Coverage.CALIBRATED,
            )
        ],
        n_records_analyzed=100,
        predictions=predictions,
        metrics=RunMetrics(
            n_predictions=len(predictions),
            n_events=1,
            n_settled_scored=0,
            brier=None,
            hit_rate=None,
            calibration=[],
            median_band_pp=6.0,
            delta=DeltaStats(n_compared=0, n_new=len(predictions), n_dropped=0),
            coverage_mix=CoverageMix(calibrated=len(predictions), uncalibrated=0, none=0),
            exclusions=[],
        ),
        execution=[ExecutionStage(name="test", status="ok", duration_ms=1)],
        integrity_hash="0" * 64,
    )


def test_find_nan_deep():
    doc = {"a": 1.0, "b": {"c": [1, {"d": math.nan}]}, "e": math.inf}
    hits = find_nan(doc)
    assert len(hits) == 2
    assert "$.b.c[1].d" in hits


def test_find_nan_clean():
    assert find_nan({"a": 1.5, "b": "text", "c": [0.1, None]}) == []


def test_validation_fails_below_row_threshold():
    artifact = _artifact_with([minimal_prediction("A")])
    report = validate_artifact(artifact)
    assert not report.ok
    failed = {c["name"] for c in report.checks if not c["passed"]}
    assert "row_count_threshold" in failed
    assert "event_count_threshold" in failed


def test_validation_catches_tampered_hash():
    preds = [minimal_prediction(f"K{i}") for i in range(45)]
    artifact = _artifact_with(preds)
    report = validate_artifact(artifact)
    assert "integrity_hash" in {c["name"] for c in report.checks if not c["passed"]}


def test_validation_catches_bad_categorical():
    preds = [minimal_prediction(f"K{i}") for i in range(45)]
    # Tamper past Pydantic (disk-tamper path): raw string in the field slot.
    preds[0].__dict__["price_assessment"] = "LEAN OVER"
    artifact = _artifact_with(preds)
    report = validate_artifact(artifact)
    assert "categorical_vocabulary" in {c["name"] for c in report.checks if not c["passed"]}


def test_series_integrity_check():
    from pipeline.schemas import SeriesPoint

    preds = [minimal_prediction(f"K{i}") for i in range(45)]
    preds[0].series = [
        SeriesPoint(run_date="2026-11-08", p=0.5),
        SeriesPoint(run_date="2026-11-07", p=0.4),
    ]  # out of order and includes run_date itself
    artifact = _artifact_with(preds)
    report = validate_artifact(artifact)
    assert "series_integrity" in {c["name"] for c in report.checks if not c["passed"]}
