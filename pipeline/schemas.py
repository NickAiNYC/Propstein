"""PropStein pipeline — schema contracts (Pydantic v2).

Two layers:
  1. RAW   — the provider slate that enters the pipeline (validated before
             any inference runs; malformed feeds fail closed).
  2. ARTIFACT — the run artifact consumed by propstein.com (data/runs/*.json,
             latest_predictions.json, runs_index.json).

Every float rejects NaN/inf (allow_inf_nan=False) and every model carries
version, uncertainty, freshness, provenance, and coverage — charter rule 5.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRICT = ConfigDict(extra="forbid", allow_inf_nan=False)


# ---------------------------------------------------------------------------
# Enums (charter vocabulary — nothing outside these sets may be emitted)
# ---------------------------------------------------------------------------


class Selection(str, Enum):
    OVER = "over"
    UNDER = "under"


class Coverage(str, Enum):
    CALIBRATED = "calibrated"
    UNCALIBRATED = "uncalibrated"
    NONE = "none"
    UNAVAILABLE = "unavailable"


class PriceAssessment(str, Enum):
    """The nine allowed categorical outputs — nothing else (charter rule 1)."""

    PRICE_ABOVE_MARKET_HURDLE = "PRICE ABOVE MARKET HURDLE"
    PRICE_AT_MARKET_HURDLE = "PRICE AT MARKET HURDLE"
    PRICE_BELOW_MARKET_HURDLE = "PRICE BELOW MARKET HURDLE"
    INSUFFICIENT_MARKET_DATA = "INSUFFICIENT MARKET DATA"
    STALE_QUOTE = "STALE QUOTE"
    NO_MODEL_COVERAGE = "NO MODEL COVERAGE"
    UNVERIFIED_CONTEXT = "UNVERIFIED CONTEXT"
    MODEL_UNAVAILABLE = "MODEL UNAVAILABLE"
    SETTLED = "SETTLED"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class SettlementStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"
    VOID = "void"
    CANCELED = "canceled"
    PUSH = "push"
    DNP = "dnp"


# ---------------------------------------------------------------------------
# RAW layer — provider slate
# ---------------------------------------------------------------------------


class RawContextObservation(BaseModel):
    """One context input with its observed-at timestamp (Evidence DNA)."""

    model_config = STRICT

    key: str  # spread | total | weather | injury_status | player_form | opponent_unit
    label: str
    observed_at_utc: Optional[str] = None  # None => never observed
    value: Optional[str] = None
    source_id: str


class RawSlateEntry(BaseModel):
    """One player-prop board row as fetched from the feeds."""

    model_config = STRICT

    event_id: str
    event_label: str
    sport: str
    league: str
    commences_at_utc: str
    game_cluster_id: str
    player_id: str
    player_name: str
    market: str
    market_label: str
    line: float = Field(ge=0)
    over_american_odds: int
    under_american_odds: int
    quote_captured_at_utc: str
    quote_provider: str
    quote_licensed: bool
    pricing_cutoff_utc: str
    context: list[RawContextObservation]
    feature_inputs: dict[str, float] = Field(default_factory=dict)

    @field_validator("over_american_odds", "under_american_odds")
    @classmethod
    def _nonzero_odds(cls, v: int) -> int:
        if v == 0:
            raise ValueError("american odds must be non-zero")
        return v


class RawSlate(BaseModel):
    """Full provider slate for one run date."""

    model_config = STRICT

    run_date: str  # YYYY-MM-DD
    source: Literal["synthetic", "licensed"]
    odds_provider: str
    stats_provider: str
    n_records_analyzed: int = Field(ge=0)
    entries: list[RawSlateEntry] = Field(min_length=1)


# ---------------------------------------------------------------------------
# ARTIFACT layer — prediction records
# ---------------------------------------------------------------------------


class UncertaintyInterval(BaseModel):
    """95% model uncertainty band on the probability scale."""

    model_config = STRICT

    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "UncertaintyInterval":
        if self.lower > self.upper:
            raise ValueError("uncertainty lower bound exceeds upper bound")
        return self

    @property
    def width_pp(self) -> float:
        return (self.upper - self.lower) * 100.0


class FeatureContribution(BaseModel):
    """Additive feature attribution: contributions sum to (p - baseline) in pp."""

    model_config = STRICT

    name: str
    label: str
    value: float
    weight: float
    contribution_pp: float


class ProvenanceObservation(BaseModel):
    model_config = STRICT

    key: str
    label: str
    source_id: str
    observed_at_utc: Optional[str] = None
    value: Optional[str] = None


class MarketQuote(BaseModel):
    model_config = STRICT

    provider: str
    book: str
    over_american_odds: int
    under_american_odds: int
    captured_at_utc: str
    licensed: bool
    raw_ref: Optional[str] = None


class FreshnessBlock(BaseModel):
    model_config = STRICT

    captured_at_utc: str
    age_seconds: Optional[int] = None
    threshold_seconds: int
    state: Freshness


class ModelBlock(BaseModel):
    """Charter rule 5: no model number without version, uncertainty, freshness."""

    model_config = STRICT

    model_name: Optional[str] = None
    model_version: Optional[str] = None
    coverage: Coverage
    probability: Optional[float] = Field(default=None, ge=0, le=1)
    uncertainty: Optional[UncertaintyInterval] = None
    calibration_status: Literal["calibrated", "uncalibrated", "none"]
    limitations: list[str] = Field(default_factory=list)
    corpus_games: Optional[int] = None
    data_freshness_utc: Optional[str] = None
    features: list[FeatureContribution] = Field(default_factory=list)

    @model_validator(mode="after")
    def _numbers_only_when_calibrated(self) -> "ModelBlock":
        if self.coverage == Coverage.CALIBRATED:
            if self.probability is None or self.uncertainty is None:
                raise ValueError("calibrated coverage must carry probability and uncertainty")
            if not (self.uncertainty.lower <= self.probability <= self.uncertainty.upper):
                raise ValueError("probability must lie inside its uncertainty interval")
        else:
            if self.probability is not None or self.uncertainty is not None:
                raise ValueError("numbers are withheld unless coverage is calibrated")
        return self


class SeriesPoint(BaseModel):
    """One prior run's probability for the same board key (sparkline point)."""

    model_config = STRICT

    run_date: str  # YYYY-MM-DD
    p: Optional[float] = Field(default=None, ge=0, le=1)  # None when withheld


class CalibrationRow(BaseModel):
    model_config = STRICT

    bucket: str
    n: int = Field(ge=1)
    predicted: float = Field(ge=0, le=1)
    observed: float = Field(ge=0, le=1)


class HistoryBlock(BaseModel):
    """Self-scoring history for this board key over the scoring window."""

    model_config = STRICT

    n_settled: int = Field(default=0, ge=0)
    n_excluded: int = Field(default=0, ge=0)
    brier: Optional[float] = None
    hit_rate: Optional[float] = None


class PredictionRecord(BaseModel):
    model_config = STRICT

    prediction_id: str
    board_key: str
    sport: str
    league: str
    event_id: str
    event_label: str
    game_cluster_id: str
    commences_at_utc: str
    player_id: str
    player_name: str
    market: str
    market_label: str
    selection: Selection
    line: float = Field(ge=0)
    quote: MarketQuote
    market_implied_probability: float = Field(ge=0, le=1)
    market_fair_probability: float = Field(ge=0, le=1)
    model: ModelBlock
    model_minus_market_pp: Optional[float] = None  # diagnostic only
    delta_pp_vs_prev: Optional[float] = None
    is_new_today: bool = False
    series: list[SeriesPoint] = Field(default_factory=list)
    provenance: list[ProvenanceObservation] = Field(default_factory=list)
    provenance_complete: bool = True
    unverified_reason: Optional[str] = None
    history: HistoryBlock = Field(default_factory=HistoryBlock)
    freshness: FreshnessBlock
    price_assessment: PriceAssessment
    reason_code: str
    assessment_detail: str

    @model_validator(mode="after")
    def _spread_only_when_numbers(self) -> "PredictionRecord":
        if self.model.probability is None and self.model_minus_market_pp is not None:
            raise ValueError("diagnostic spread requires a model probability")
        return self


# ---------------------------------------------------------------------------
# ARTIFACT layer — run metadata
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    model_config = STRICT

    model_name: str
    model_version: str
    sport: str
    market: str
    coverage: Coverage
    corpus_games: Optional[int] = None
    limitations: list[str] = Field(default_factory=list)


class ExclusionCount(BaseModel):
    model_config = STRICT

    reason: str
    count: int = Field(ge=1)


class DeltaStats(BaseModel):
    model_config = STRICT

    n_compared: int = Field(ge=0)
    n_new: int = Field(ge=0)
    n_dropped: int = Field(ge=0)
    mean_abs_delta_pp: Optional[float] = None
    max_abs_delta_pp: Optional[float] = None


class CoverageMix(BaseModel):
    model_config = STRICT

    calibrated: int = Field(ge=0)
    uncalibrated: int = Field(ge=0)
    none: int = Field(ge=0)


class RunMetrics(BaseModel):
    model_config = STRICT

    n_predictions: int = Field(ge=0)
    n_events: int = Field(ge=0)
    n_settled_scored: int = Field(ge=0)
    brier: Optional[float] = None
    hit_rate: Optional[float] = None
    calibration: list[CalibrationRow] = Field(default_factory=list)
    median_band_pp: Optional[float] = None
    delta: DeltaStats
    coverage_mix: CoverageMix
    exclusions: list[ExclusionCount] = Field(default_factory=list)


class ExecutionStage(BaseModel):
    model_config = STRICT

    name: str
    status: Literal["ok", "failed", "skipped"]
    duration_ms: int = Field(ge=0)
    detail: Optional[str] = None


class RunArtifact(BaseModel):
    model_config = STRICT

    schema_version: int = 1
    run_date: str  # YYYY-MM-DD
    run_id: str  # run_date + scheduled time
    generated_at_utc: str
    pipeline_version: str
    source: Literal["synthetic", "licensed"]
    odds_provider: str
    stats_provider: str
    seed: int
    models: list[ModelInfo]
    n_records_analyzed: int = Field(ge=0)
    predictions: list[PredictionRecord] = Field(min_length=1)
    metrics: RunMetrics
    execution: list[ExecutionStage]
    integrity_hash: str = Field(min_length=64, max_length=64)


class IndexEntry(BaseModel):
    model_config = STRICT

    run_date: str
    run_id: str
    prediction_count: int = Field(ge=1)
    n_records_analyzed: int = Field(ge=0)
    integrity_hash: str
    duration_ms: int = Field(ge=0)
    source: Literal["synthetic", "licensed"]
    pipeline_version: str
    generated_at_utc: str


class RunsIndex(BaseModel):
    model_config = STRICT

    schema_version: int = 1
    updated_at_utc: str
    latest_run_date: Optional[str] = None
    health: Literal["healthy", "degraded", "down"]
    health_reason: str
    runs: list[IndexEntry] = Field(default_factory=list)
