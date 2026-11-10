"""Test fixtures: minimal valid prediction records."""

from __future__ import annotations

from pipeline.schemas import (
    Coverage,
    Freshness,
    FreshnessBlock,
    HistoryBlock,
    MarketQuote,
    ModelBlock,
    PredictionRecord,
    UncertaintyInterval,
)


def minimal_prediction(board_key: str, probability: float = 0.55) -> PredictionRecord:
    return PredictionRecord(
        prediction_id=f"PRD-{board_key}",
        board_key=board_key,
        sport="NFL",
        league="NFL",
        event_id="E1",
        event_label="A @ B",
        game_cluster_id="E1",
        commences_at_utc="2026-11-08T17:00:00Z",
        player_id="P1",
        player_name="X. Y",
        market="player_reception_yds",
        market_label="Receiving Yards",
        selection="over",
        line=52.5,
        quote=MarketQuote(
            provider="synthetic",
            book="synthetic",
            over_american_odds=-110,
            under_american_odds=-110,
            captured_at_utc="2026-11-08T10:30:00Z",
            licensed=True,
        ),
        market_implied_probability=0.5238,
        market_fair_probability=0.5,
        model=ModelBlock(
            model_name="NFL Receiving Yards Model",
            model_version="REC-V4",
            coverage=Coverage.CALIBRATED,
            probability=probability,
            uncertainty=UncertaintyInterval(
                lower=max(0.01, probability - 0.03), upper=min(0.99, probability + 0.03)
            ),
            calibration_status="calibrated",
            limitations=["Fixture limitation."],
            corpus_games=428,
            data_freshness_utc="2026-11-08T11:00:00Z",
        ),
        model_minus_market_pp=round((probability - 0.5) * 100, 4),
        is_new_today=True,
        series=[],
        provenance=[],
        provenance_complete=True,
        history=HistoryBlock(),
        freshness=FreshnessBlock(
            captured_at_utc="2026-11-08T10:30:00Z",
            age_seconds=120,
            threshold_seconds=300,
            state=Freshness.FRESH,
        ),
        price_assessment="PRICE AT MARKET HURDLE",
        reason_code="MARKET_HURDLE_BAND",
        assessment_detail="Fixture detail.",
    )
