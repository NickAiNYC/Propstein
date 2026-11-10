"""Engine + runs contracts: determinism, idempotency, fail-closed fixtures."""

from __future__ import annotations

import json
from datetime import date

import pytest

from pipeline import config
from pipeline.engine import build_run
from pipeline.providers.synthetic import SyntheticBoardFeed
from pipeline.runs import (
    RunConflictError,
    compute_integrity_hash,
    load_run,
    run_path,
    write_run,
)
from pipeline.schemas import Coverage
from pipeline.validate import validate_artifact


@pytest.fixture(scope="module")
def slate():
    # Friday run: horizon Fri/Sat/Sun includes the Saturday UFC card.
    return SyntheticBoardFeed().fetch_slate(date(2026, 11, 6))


@pytest.fixture(scope="module")
def artifact(slate):
    return build_run(slate, [])


def test_slate_has_three_sports_and_fail_closed_fixtures(slate):
    sports = {e.sport for e in slate.entries}
    assert sports == {"NFL", "NBA", "UFC"}
    # stale quote fixtures (captured 13h before the 10:55 run moment)
    assert any(_is_stale(e) for e in slate.entries)
    # unverified context fixtures (NFL weather missing or late spread)
    assert any(_missing_weather(e) for e in slate.entries)
    assert any(_late_spread(e) for e in slate.entries)


def _is_stale(e) -> bool:
    # stale fixtures are captured 13h before the 10:59 run moment of the
    # slate's run date (i.e. 21:59 on the prior day)
    from datetime import datetime

    captured = datetime.strptime(e.quote_captured_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    run_moment = datetime.strptime(f"{RUN_DATE}T10:59:00Z", "%Y-%m-%dT%H:%M:%SZ")
    return (run_moment - captured).total_seconds() > 300


RUN_DATE = "2026-11-06"  # matches the module slate fixture


def _missing_weather(e) -> bool:
    return e.sport == "NFL" and any(c.key == "weather" and c.observed_at_utc is None for c in e.context)


def _late_spread(e) -> bool:
    return any(
        c.key == "spread" and c.observed_at_utc is not None and c.observed_at_utc > e.pricing_cutoff_utc
        for c in e.context
    )


def test_every_categorical_is_from_allowed_set(artifact):
    allowed = {
        "PRICE ABOVE MARKET HURDLE",
        "PRICE AT MARKET HURDLE",
        "PRICE BELOW MARKET HURDLE",
        "INSUFFICIENT MARKET DATA",
        "STALE QUOTE",
        "NO MODEL COVERAGE",
        "UNVERIFIED CONTEXT",
        "MODEL UNAVAILABLE",
        "SETTLED",
    }
    for p in artifact.predictions:
        assert p.price_assessment.value in allowed


def test_fail_closed_fixtures_surface_in_assessments(artifact):
    cats = {p.price_assessment.value for p in artifact.predictions}
    assert "STALE QUOTE" in cats
    assert "UNVERIFIED CONTEXT" in cats
    assert "NO MODEL COVERAGE" in cats  # UFC rows
    assert "PRICE AT MARKET HURDLE" in cats or "PRICE ABOVE MARKET HURDLE" in cats or "PRICE BELOW MARKET HURDLE" in cats


def test_stale_rows_have_no_hurdle_numbers(artifact):
    for p in artifact.predictions:
        if p.price_assessment.value == "STALE QUOTE":
            assert p.reason_code == "COMPARISON_STALE"
            # market numbers retained for the record
            assert p.market_fair_probability > 0


def test_uncalibrated_market_withholds_numbers(artifact):
    passing = [p for p in artifact.predictions if p.market == "player_passing_yds"]
    assert passing
    for p in passing:
        assert p.model.coverage == Coverage.UNCALIBRATED
        assert p.model.probability is None
        assert p.model.uncertainty is None
        # Only rows that clear provenance and freshness reach the coverage
        # categorical; stale/unverified rows fail closed earlier (order rule).
        if p.price_assessment.value not in ("STALE QUOTE", "UNVERIFIED CONTEXT"):
            assert p.price_assessment.value == "NO MODEL COVERAGE"
    assert any(p.price_assessment.value == "NO MODEL COVERAGE" for p in passing)


def test_calibrated_rows_carry_full_charter_block(artifact):
    calibrated = [p for p in artifact.predictions if p.model.coverage == Coverage.CALIBRATED]
    assert len(calibrated) > 30
    for p in calibrated:
        assert p.model.model_version
        assert p.model.probability is not None
        assert p.model.uncertainty is not None
        assert p.model.limitations
        assert p.model.corpus_games
        assert p.model.data_freshness_utc
        assert p.model.features  # raw factors present
        assert p.model_minus_market_pp is not None
        assert p.freshness.age_seconds is not None


def test_determinism_two_builds_identical(slate):
    a1 = build_run(slate, [])
    a2 = build_run(slate, [])
    # Content must be byte-identical; execution durations are environment-
    # dependent by design (excluded from the integrity hash too).
    assert a1.model_dump(exclude={"execution"}) == a2.model_dump(exclude={"execution"})
    assert a1.integrity_hash == a2.integrity_hash


def test_integrity_hash_excludes_execution_only(slate):
    a1 = build_run(slate, [])
    a2 = build_run(slate, [])
    # mutate a duration (environment-dependent) — hash must stay equal
    a2.execution[0].duration_ms += 123
    assert compute_integrity_hash(a1) == compute_integrity_hash(a2)
    # mutate content — hash must change
    a2.predictions[0].model.limitations = ["x"]
    assert compute_integrity_hash(a1) != compute_integrity_hash(a2)


def test_validate_artifact_passes(artifact):
    report = validate_artifact(artifact)
    assert report.ok, [c for c in report.checks if not c["passed"]]


def test_write_run_idempotent_and_conflict(tmp_path, monkeypatch, artifact):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    assert write_run(artifact) == "written"
    assert write_run(artifact) == "unchanged"  # byte-identical rebuild

    tampered = artifact.model_copy(deep=True)
    tampered.predictions[0].model.limitations = ["tampered"]
    with pytest.raises(RunConflictError):
        write_run(tampered)

    loaded = load_run(artifact.run_date)
    assert loaded is not None
    assert loaded.integrity_hash == artifact.integrity_hash


def test_load_run_detects_corruption(tmp_path, monkeypatch, artifact):
    from pipeline.runs import ArtifactCorruptError

    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    write_run(artifact)
    path = tmp_path / f"{artifact.run_date}.json"
    doc = json.loads(path.read_text())
    doc["predictions"][0]["line"] = 99.0  # tamper after write
    path.write_text(json.dumps(doc))
    with pytest.raises(ArtifactCorruptError):
        load_run(artifact.run_date)


def test_hurdle_directionality(artifact):
    """Model P above the break-even hurdle => ABOVE; below => BELOW."""
    for p in artifact.predictions:
        if p.price_assessment.value == "PRICE ABOVE MARKET HURDLE":
            assert p.model.probability is not None
            assert p.model.probability > p.market_implied_probability + 0.0025
        elif p.price_assessment.value == "PRICE BELOW MARKET HURDLE":
            assert p.model.probability is not None
            assert p.model.probability < p.market_implied_probability - 0.0025
        elif p.price_assessment.value == "PRICE AT MARKET HURDLE":
            assert p.model.probability is not None
            assert abs(p.model.probability - p.market_implied_probability) <= 0.0025


def test_prior_runs_feed_series_and_delta():
    feed = SyntheticBoardFeed()
    day1 = date(2026, 11, 5)  # Thursday
    day2 = date(2026, 11, 6)  # Friday
    a1 = build_run(feed.fetch_slate(day1), [])
    a2 = build_run(feed.fetch_slate(day2), [a1])

    with_series = [p for p in a2.predictions if p.series]
    assert with_series, "shared board keys across consecutive days must produce series"
    for p in with_series:
        dates = [s.run_date for s in p.series]
        assert dates == sorted(dates)
        assert all(d < a2.run_date for d in dates)
        assert p.is_new_today is False

    new_today = [p for p in a2.predictions if p.is_new_today]
    assert new_today  # Saturday-only UFC rows are new on the Friday board

    compared = [p for p in a2.predictions if p.delta_pp_vs_prev is not None]
    assert compared
    delta = a2.metrics.delta
    assert delta.n_compared == len(compared)
    assert delta.mean_abs_delta_pp is not None


def test_self_scoring_populates_brier_after_priors():
    feed = SyntheticBoardFeed()
    runs = []
    for d in range(3, 7):
        day = date(2026, 11, d)
        runs.append(build_run(feed.fetch_slate(day), list(runs)))
    latest = runs[-1]
    assert latest.metrics.brier is not None
    assert 0.0 <= latest.metrics.brier <= 1.0
    assert latest.metrics.hit_rate is not None
    assert latest.metrics.calibration  # decile table present
    assert latest.metrics.exclusions  # push/void/dnp counted with reasons
