"""Schema contracts: NaN rejection, coverage/number policy, ordering."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pipeline.schemas import (
    Coverage,
    ModelBlock,
    PredictionRecord,
    RawSlate,
    RunArtifact,
    UncertaintyInterval,
)


def test_uncertainty_interval_ordering_enforced():
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=0.6, upper=0.4)


def test_uncertainty_bounds_range():
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=-0.1, upper=0.5)
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=0.1, upper=1.5)


def test_model_block_calibrated_requires_numbers():
    with pytest.raises(ValidationError):
        ModelBlock(coverage=Coverage.CALIBRATED, calibration_status="calibrated")


def test_model_block_calibrated_probability_inside_interval():
    with pytest.raises(ValidationError):
        ModelBlock(
            coverage=Coverage.CALIBRATED,
            calibration_status="calibrated",
            probability=0.8,
            uncertainty=UncertaintyInterval(lower=0.5, upper=0.6),
        )


def test_model_block_uncalibrated_withholds_numbers():
    with pytest.raises(ValidationError):
        ModelBlock(
            coverage=Coverage.UNCALIBRATED,
            calibration_status="uncalibrated",
            probability=0.55,
        )


def test_nan_rejected_everywhere():
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=math.nan, upper=0.5)
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=0.1, upper=math.inf)


def test_raw_slate_requires_entries():
    with pytest.raises(ValidationError):
        RawSlate(
            run_date="2026-11-10",
            source="synthetic",
            odds_provider="p",
            stats_provider="p",
            n_records_analyzed=0,
            entries=[],
        )


def test_raw_slate_rejects_zero_odds():
    from pipeline.schemas import RawSlateEntry, RawContextObservation

    def entry(over: int) -> RawSlateEntry:
        return RawSlateEntry(
            event_id="E1",
            event_label="A @ B",
            sport="NFL",
            league="NFL",
            commences_at_utc="2026-11-10T17:00:00Z",
            game_cluster_id="E1",
            player_id="P1",
            player_name="X. Y",
            market="player_reception_yds",
            market_label="Receiving Yards",
            line=52.5,
            over_american_odds=over,
            under_american_odds=-110,
            quote_captured_at_utc="2026-11-10T10:30:00Z",
            quote_provider="p",
            quote_licensed=True,
            pricing_cutoff_utc="2026-11-10T10:31:00Z",
            context=[RawContextObservation(key="spread", label="s", source_id="p", observed_at_utc=None)],
        )

    with pytest.raises(ValidationError):
        RawSlate(
            run_date="2026-11-10",
            source="synthetic",
            odds_provider="p",
            stats_provider="p",
            n_records_analyzed=1,
            entries=[entry(0)],
        )


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        UncertaintyInterval(lower=0.1, upper=0.2, bogus=1)
