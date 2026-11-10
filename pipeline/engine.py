"""PropStein pipeline — run engine.

Builds the RunArtifact from a raw slate plus prior run history:

  slate -> per-row categorical assessment (charter evaluation order,
           board semantics) -> series/delta attach -> self-scoring ->
  integrity hash -> RunArtifact

Board categorical order (mirrors the preregistered Hurdle Router order,
adapted to board rows which have no user-entered price):
  1. UNVERIFIED CONTEXT — required context (spread/total/weather for outdoor)
                          missing or observed after the pricing cutoff.
  2. STALE QUOTE        — quote snapshot age beyond the freshness threshold.
  3. NO MODEL COVERAGE  — no calibrated model for the sport+market. Market
                          numbers still displayed; model panel states the gap.
  4. MARKET HURDLE BAND — calibrated model vs the break-even hurdle of the
                          quoted price, ±0.25 pp band (descriptive diagnostic;
                          never an actionable-signal claim).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone

from pipeline import config
from pipeline.determinism import seed_from
from pipeline.features import feature_specs
from pipeline.models import MODEL_REGISTRY, ModelEntry, assess
from pipeline.odds import break_even_probability, devig_two_way
from pipeline.runs import compute_integrity_hash
from pipeline.schemas import (
    Coverage,
    Freshness,
    FreshnessBlock,
    ModelInfo,
    PredictionRecord,
    ProvenanceObservation,
    RawSlate,
    RawSlateEntry,
    RunArtifact,
    RunMetrics,
    CoverageMix,
)
from pipeline.scoring import (
    attach_series_and_delta,
    delta_vs_previous,
    grade_history,
    score_run,
)

HURDLE_BAND_PP = 0.25

# Required context inputs by sport (parity with types.ts).
REQUIRED_CONTEXT: dict[str, set[str]] = {
    "NFL": {"spread", "total", "weather"},
    "NBA": {"spread", "total"},
    "UFC": set(),
}


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _assess_row(
    entry: RawSlateEntry,
    run_now: datetime,
) -> PredictionRecord:
    board_key = f"{entry.sport}|{entry.event_id}|{entry.player_id}|{entry.market}"
    prediction_id = f"PRD-{seed_from(board_key, entry.line, entry.quote_captured_at_utc):012X}"

    market_fair_over, market_fair_under = devig_two_way(entry.over_american_odds, entry.under_american_odds)
    market_fair = market_fair_over  # board convention: OVER-side fair probability
    break_even = break_even_probability(entry.over_american_odds)

    quote_dt = _parse_ts(entry.quote_captured_at_utc)
    cutoff_dt = _parse_ts(entry.pricing_cutoff_utc)
    if quote_dt is None:
        freshness = FreshnessBlock(captured_at_utc=entry.quote_captured_at_utc, threshold_seconds=config.MARKET_COMPARISON_SECONDS, state=Freshness.UNKNOWN, age_seconds=None)
        age_seconds: int | None = None
    else:
        age = max(0, int((run_now - quote_dt).total_seconds()))
        age_seconds = age
        freshness = FreshnessBlock(
            captured_at_utc=entry.quote_captured_at_utc,
            threshold_seconds=config.MARKET_COMPARISON_SECONDS,
            state=Freshness.STALE if age > config.MARKET_COMPARISON_SECONDS else Freshness.FRESH,
            age_seconds=age,
        )

    data_freshness = run_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    model_block = assess(
        entry.sport,
        entry.market,
        "over",
        entry.line,
        entry.feature_inputs,
        board_key,
        data_freshness,
    )

    provenance = [
        ProvenanceObservation(key=c.key, label=c.label, source_id=c.source_id, observed_at_utc=c.observed_at_utc, value=c.value)
        for c in entry.context
    ]

    # --- charter evaluation order ------------------------------------------
    assessment: str
    reason_code: str
    detail: str
    provenance_complete = True
    unverified_reason: str | None = None

    required = REQUIRED_CONTEXT.get(entry.sport, set())
    missing = [
        c.key
        for c in entry.context
        if c.key in required and c.observed_at_utc is None
    ]
    required_keys_present = {c.key for c in entry.context}
    never_observed = [k for k in required if k not in required_keys_present]
    late: list[str] = []
    if cutoff_dt is not None:
        for c in entry.context:
            if c.key in required and c.observed_at_utc is not None:
                obs = _parse_ts(c.observed_at_utc)
                if obs is None or obs > cutoff_dt:
                    late.append(c.key)

    if missing or never_observed or late:
        assessment = "UNVERIFIED CONTEXT"
        reason_code = "PROVENANCE_INCOMPLETE"
        parts = []
        if missing or never_observed:
            parts.append(f"missing observed-at for: {', '.join(sorted(set(missing) | set(never_observed)))}")
        if late:
            parts.append(f"observed after pricing cutoff: {', '.join(sorted(late))}")
        unverified_reason = "; ".join(parts)
        provenance_complete = False
        detail = (
            f"Context inputs are not verified as known before the pricing cutoff ({unverified_reason}). "
            "The assessment fails closed."
        )
    elif freshness.state != Freshness.FRESH:
        assessment = "STALE QUOTE"
        reason_code = "COMPARISON_STALE"
        detail = (
            "Quote snapshot timestamp is missing or beyond the freshness threshold. "
            "The quote is retained but not used for the hurdle comparison."
            if freshness.state == Freshness.UNKNOWN
            else f"Quote snapshot is {age_seconds} seconds old (threshold {config.MARKET_COMPARISON_SECONDS} seconds). The quote is retained but not used."
        )
    elif model_block.coverage == Coverage.UNAVAILABLE:
        assessment = "MODEL UNAVAILABLE"
        reason_code = "MODEL_SERVICE_UNAVAILABLE"
        detail = "The model registry lists this market, but the model surface is unavailable. The assessment fails closed."
    elif model_block.coverage != Coverage.CALIBRATED:
        assessment = "NO MODEL COVERAGE"
        reason_code = "NO_CALIBRATED_MODEL"
        detail = (
            "No calibrated model coverage exists for this market. Market numbers are shown; "
            "the model panel states the coverage gap. This is not an instruction to take or decline the price."
            if model_block.coverage == Coverage.NONE
            else "Coverage exists but calibration is pending, so model numbers are withheld. This is not an instruction to take or decline the price."
        )
    else:
        # Hurdle semantics: the quote's break-even probability is the hurdle.
        # Model probability ABOVE the hurdle means the quoted price clears the
        # model's requirement (descriptive diagnostic only).
        delta = (model_block.probability - break_even) * 100.0 if model_block.probability is not None else None
        if delta is None:  # pragma: no cover — schema enforces numbers when calibrated
            raise AssertionError("calibrated model without probability")
        if delta > HURDLE_BAND_PP:
            assessment = "PRICE ABOVE MARKET HURDLE"
        elif delta < -HURDLE_BAND_PP:
            assessment = "PRICE BELOW MARKET HURDLE"
        else:
            assessment = "PRICE AT MARKET HURDLE"
        reason_code = "MARKET_HURDLE_BAND"
        direction = "above" if delta > 0 else "below" if delta < 0 else "within the band of"
        detail = (
            f"Model probability is {abs(delta):.1f} percentage points {direction} the break-even hurdle. "
            "Descriptive diagnostic of model vs market — not a betting recommendation."
        )

    model_minus_market = (
        round((model_block.probability - market_fair) * 100.0, 4)
        if model_block.probability is not None
        else None
    )

    return PredictionRecord(
        prediction_id=prediction_id,
        board_key=board_key,
        sport=entry.sport,
        league=entry.league,
        event_id=entry.event_id,
        event_label=entry.event_label,
        game_cluster_id=entry.game_cluster_id,
        commences_at_utc=entry.commences_at_utc,
        player_id=entry.player_id,
        player_name=entry.player_name,
        market=entry.market,
        market_label=entry.market_label,
        selection="over",
        line=entry.line,
        quote={
            "provider": entry.quote_provider,
            "book": entry.quote_provider,
            "over_american_odds": entry.over_american_odds,
            "under_american_odds": entry.under_american_odds,
            "captured_at_utc": entry.quote_captured_at_utc,
            "licensed": entry.quote_licensed,
            "raw_ref": None,
        },
        market_implied_probability=round(break_even, 4),
        market_fair_probability=round(market_fair, 4),
        model=model_block,
        model_minus_market_pp=model_minus_market,
        provenance=provenance,
        provenance_complete=provenance_complete,
        unverified_reason=unverified_reason,
        freshness=freshness,
        price_assessment=assessment,
        reason_code=reason_code,
        assessment_detail=detail,
    )


def build_run(
    slate: RawSlate,
    prior_runs: list,
) -> RunArtifact:
    """Assemble the full run artifact from a validated slate and priors."""
    from pipeline.schemas import DeltaStats, ExecutionStage  # local import to avoid cycles in typing

    t0 = time.monotonic()
    run_now = datetime.strptime(slate.run_date + "T11:00:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    run_id = f"{slate.run_date}-1100Z"

    records = [_assess_row(entry, run_now) for entry in slate.entries]
    t_rows = time.monotonic()

    attach_series_and_delta(records, prior_runs, config.SERIES_WINDOW)
    t_series = time.monotonic()

    for rec in records:
        priors_for_key = [
            (run.run_date, r)
            for run in prior_runs
            for r in run.predictions
            if r.board_key == rec.board_key
        ]
        if priors_for_key:
            rec.history = grade_history(rec.board_key, priors_for_key)
    t_history = time.monotonic()

    # "Previous" = the most recent prior run (load_prior_runs returns newest-first).
    previous = max(prior_runs, key=lambda r: r.run_date).predictions if prior_runs else None
    delta_stats = delta_vs_previous(records, previous)

    brier, hit_rate, cal_rows, exclusions = score_run(
        date.fromisoformat(slate.run_date), records, prior_runs, config.SCORING_WINDOW_RUNS
    )
    t_score = time.monotonic()

    mix = CoverageMix(
        calibrated=sum(1 for r in records if r.model.coverage == Coverage.CALIBRATED),
        uncalibrated=sum(1 for r in records if r.model.coverage == Coverage.UNCALIBRATED),
        none=sum(1 for r in records if r.model.coverage in (Coverage.NONE, Coverage.UNAVAILABLE)),
    )

    bands = [
        (r.model.uncertainty.upper - r.model.uncertainty.lower) * 100.0
        for r in records
        if r.model.uncertainty is not None
    ]
    median_band = sorted(bands)[len(bands) // 2] if bands else None

    events = {r.event_id for r in records}

    models_info = [
        ModelInfo(
            model_name=m.model_name,
            model_version=m.model_version,
            sport=m.sport,
            market=m.market,
            coverage=m.coverage,
            corpus_games=m.corpus_games,
            limitations=list(m.limitations),
        )
        for m in MODEL_REGISTRY
    ]

    artifact = RunArtifact(
        run_date=slate.run_date,
        run_id=run_id,
        generated_at_utc=run_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        pipeline_version=config.PIPELINE_VERSION,
        source=slate.source,
        odds_provider=slate.odds_provider,
        stats_provider=slate.stats_provider,
        seed=config.MASTER_SEED,
        models=models_info,
        n_records_analyzed=slate.n_records_analyzed,
        predictions=records,
        metrics=RunMetrics(
            n_predictions=len(records),
            n_events=len(events),
            n_settled_scored=sum(1 for r in records if r.history.n_settled > 0),
            brier=brier,
            hit_rate=hit_rate,
            calibration=cal_rows,
            median_band_pp=round(median_band, 4) if median_band is not None else None,
            delta=delta_stats,
            coverage_mix=mix,
            exclusions=exclusions,
        ),
        execution=[
            ExecutionStage(name="fetch_slate", status="ok", duration_ms=int((t_rows - t0) * 1000)),
            ExecutionStage(name="assess_rows", status="ok", duration_ms=int((t_series - t_rows) * 1000)),
            ExecutionStage(name="series_delta", status="ok", duration_ms=int((t_history - t_series) * 1000)),
            ExecutionStage(name="history_grading", status="ok", duration_ms=int((t_score - t_history) * 1000)),
            ExecutionStage(name="self_scoring", status="ok", duration_ms=int((time.monotonic() - t_score) * 1000)),
        ],
        integrity_hash="0" * 64,  # placeholder; replaced below
    )
    artifact.integrity_hash = compute_integrity_hash(artifact)
    return artifact


__all__ = ["build_run"]
