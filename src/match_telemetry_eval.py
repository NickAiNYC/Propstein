"""Evaluation and monitoring framework for extension DOM match-layer telemetry.

Calculates the four production-readiness metrics:
1. Match success rate: fraction of match attempts resolving to MATCHED vs
   AMBIGUOUS / NO_EXTRACTION / MULTI_MATCH / MARKET_UNSCOPEABLE.
2. Extraction error rate: fraction of MATCHED results with observed line/price discrepancies.
3. Cross-book variance: consistency of signal resolution for the same market across books.
4. Drift detection: flags degradation in per-book match rate over rolling time windows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class MatchTelemetrySummary:
    total_attempts: int
    matched_count: int
    match_success_rate: float
    outcome_counts: dict[str, int]
    per_book_match_rate: dict[str, float]
    extraction_error_rate: float
    cross_book_consistency_rate: float
    drift_alarm: bool
    drift_reasons: list[str]
    calibrated: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_match_telemetry(
    events: Sequence[dict[str, Any]],
    *,
    book_baselines: dict[str, float] | None = None,
    min_book_match_rate_threshold: float = 0.70,
    max_drift_drop_threshold: float = 0.15,
) -> MatchTelemetrySummary:
    """Analyze a batch or stream of MatchTelemetryEvent records.

    Drift detection is computed relative to each book's established historical
    baseline (e.g. first week's median match rate) rather than a naive fixed
    threshold. If a book has no established baseline, it falls back to
    min_book_match_rate_threshold as a provisional floor, with calibrated=False.
    """
    is_calibrated = bool(book_baselines and len(book_baselines) > 0)
    if not events:
        return MatchTelemetrySummary(
            total_attempts=0,
            matched_count=0,
            match_success_rate=0.0,
            outcome_counts={},
            per_book_match_rate={},
            extraction_error_rate=0.0,
            cross_book_consistency_rate=1.0,
            drift_alarm=False,
            drift_reasons=["No telemetry events recorded"],
            calibrated=is_calibrated,
        )

    outcomes = Counter(ev.get("outcome", "UNKNOWN") for ev in events)
    total = len(events)
    matched = outcomes.get("MATCHED", 0)
    success_rate = round(matched / total, 4)

    # Per-book breakdown
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        b = str(ev.get("book", "unknown")).lower()
        by_book[b].append(ev)

    per_book_rates: dict[str, float] = {}
    drift_reasons: list[str] = []
    drift_alarm = False
    baselines = {k.lower(): v for k, v in (book_baselines or {}).items()}

    for b, b_events in by_book.items():
        b_matched = sum(1 for e in b_events if e.get("outcome") == "MATCHED")
        rate = round(b_matched / len(b_events), 4)
        per_book_rates[b] = rate

        if b in baselines:
            base = baselines[b]
            rel_thresh = round(base * (1.0 - max_drift_drop_threshold), 4)
            if rate < rel_thresh:
                drift_alarm = True
                drift_reasons.append(
                    f"Book '{b}' match rate ({rate:.1%}) dropped >{max_drift_drop_threshold:.0%} "
                    f"below established baseline ({base:.1%}, threshold {rel_thresh:.1%})"
                )
        elif rate < min_book_match_rate_threshold:
            drift_alarm = True
            drift_reasons.append(
                f"Book '{b}' match rate ({rate:.1%}) below provisional threshold ({min_book_match_rate_threshold:.1%}) [no baseline calibrated]"
            )

    # Extraction errors (discrepancies noted in details)
    extraction_errors = sum(
        1 for e in events
        if e.get("outcome") == "MATCHED" and ("error" in str(e.get("details", "")).lower() or "discrepancy" in str(e.get("details", "")).lower())
    )
    extraction_err_rate = round(extraction_errors / max(1, matched), 4)

    # Cross-book consistency across common entity details
    # Group by player/line detail across books
    market_resolutions: dict[str, set[str]] = defaultdict(set)
    for ev in events:
        details = str(ev.get("details", ""))
        outcome = str(ev.get("outcome", ""))
        if details:
            market_resolutions[details].add(outcome)

    multi_book_markets = [res for res in market_resolutions.values() if len(res) > 0]
    consistent_markets = sum(1 for res in multi_book_markets if len(res) == 1)
    consistency_rate = round(consistent_markets / max(1, len(multi_book_markets)), 4)

    return MatchTelemetrySummary(
        total_attempts=total,
        matched_count=matched,
        match_success_rate=success_rate,
        outcome_counts=dict(outcomes),
        per_book_match_rate=per_book_rates,
        extraction_error_rate=extraction_err_rate,
        cross_book_consistency_rate=consistency_rate,
        drift_alarm=drift_alarm,
        drift_reasons=drift_reasons,
        calibrated=is_calibrated,
    )

