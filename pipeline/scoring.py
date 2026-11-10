"""PropStein pipeline — self-scoring: settlements, Brier, calibration, deltas.

The pipeline grades its OWN prior predictions against a settlement source that
is independent of the model by construction: the simulated settlement truth
is driven by the entry market fair probability (plus seeded noise), never by
the model output. Model Brier/hit-rate are therefore honest diagnostics.

Exclusion semantics (charter rule 6 — no silent exclusions): push/void/DNP/
canceled predictions are counted as n_excluded with a reason, never folded
into Brier or hit rate.
"""

from __future__ import annotations

from datetime import date

from pipeline.determinism import mulberry32, seed_from
from pipeline.schemas import (
    CalibrationRow,
    DeltaStats,
    ExclusionCount,
    HistoryBlock,
    PredictionRecord,
    RunArtifact,
    SeriesPoint,
)


def simulate_settlement(
    board_key: str,
    run_date: str,
    line: float,
    market_fair_probability: float,
) -> tuple[str, str | None]:
    """Deterministic settlement for a past board prediction.

    Returns (status, result). Truth win probability = market fair at entry
    (independent of the model), with a seeded draw. Integer lines landing
    exactly produce pushes (excluded from scoring, never counted as loss).
    """
    rand = mulberry32(seed_from("SETTLE-PIPE", board_key, run_date, line))
    roll = rand()
    if roll < 0.02:
        return "void", "void"
    if roll < 0.035:
        return "dnp", None
    win = rand() < market_fair_probability
    if float(line).is_integer() and rand() < 0.045:
        return "push", "push"
    return "settled", "win" if win else "loss"


def grade_history(
    board_key: str,
    prior_predictions: list[tuple[str, PredictionRecord]],  # (run_date, record)
) -> HistoryBlock:
    """Grade one board key's prior predictions over the scoring window."""
    n_settled = 0
    n_excluded = 0
    briers: list[float] = []
    hits: list[int] = []

    for run_date, rec in prior_predictions:
        if rec.model.probability is None:
            n_excluded += 1
            continue
        status, result = simulate_settlement(
            board_key, run_date, rec.line, rec.market_fair_probability
        )
        if status != "settled" or result not in ("win", "loss"):
            n_excluded += 1
            continue
        n_settled += 1
        outcome = 1.0 if result == "win" else 0.0
        briers.append((rec.model.probability - outcome) ** 2)
        hits.append(int(result == "win"))

    return HistoryBlock(
        n_settled=n_settled,
        n_excluded=n_excluded,
        brier=round(sum(briers) / len(briers), 4) if briers else None,
        hit_rate=round(sum(hits) / len(hits), 4) if hits else None,
    )


def calibration_table(
    records: list[tuple[float, int]],
) -> tuple[float | None, list[CalibrationRow]]:
    """Brier + decile calibration over (probability, outcome) pairs."""
    if not records:
        return None, []
    brier = sum((p - o) ** 2 for p, o in records) / len(records)
    rows: list[CalibrationRow] = []
    for d in range(10):
        lo, hi = d / 10.0, (d + 1) / 10.0
        idx = [
            i
            for i, (p, _o) in enumerate(records)
            if (lo <= p < hi) or (d == 9 and p == hi)
        ]
        if not idx:
            continue
        pred = sum(records[i][0] for i in idx) / len(idx)
        obs = sum(records[i][1] for i in idx) / len(idx)
        rows.append(
            CalibrationRow(
                bucket=f"{round(lo * 100)}-{round(hi * 100)}%",
                n=len(idx),
                predicted=round(pred, 4),
                observed=round(obs, 4),
            )
        )
    return round(brier, 4), rows


def delta_vs_previous(
    current: list[PredictionRecord],
    previous: list[PredictionRecord] | None,
) -> DeltaStats:
    """Day-over-day model movement for board keys present on both days."""
    if previous is None:
        return DeltaStats(n_compared=0, n_new=len(current), n_dropped=0)
    prev_by_key = {r.board_key: r for r in previous}
    curr_keys = {r.board_key for r in current}

    deltas: list[float] = []
    n_new = 0
    for rec in current:
        prev = prev_by_key.get(rec.board_key)
        if prev is None or prev.model.probability is None:
            if prev is None:
                n_new += 1
            continue
        if rec.model.probability is None:
            continue
        deltas.append((rec.model.probability - prev.model.probability) * 100.0)

    return DeltaStats(
        n_compared=len(deltas),
        n_new=n_new,
        n_dropped=len(set(prev_by_key) - curr_keys),
        mean_abs_delta_pp=round(sum(abs(d) for d in deltas) / len(deltas), 4) if deltas else None,
        max_abs_delta_pp=round(max((abs(d) for d in deltas), default=0.0), 4) if deltas else None,
    )


def attach_series_and_delta(
    current: list[PredictionRecord],
    prior_runs: list[RunArtifact],
    window: int,
) -> None:
    """Mutates current records: attach the trailing probability series and the
    day-over-day delta (pp) vs the most recent prior run containing the key."""
    recent = sorted(prior_runs, key=lambda a: a.run_date, reverse=True)[: window - 1]
    for rec in current:
        series: list[SeriesPoint] = []
        delta: float | None = None
        for run in recent:
            for prior in run.predictions:
                if prior.board_key == rec.board_key:
                    series.append(SeriesPoint(run_date=run.run_date, p=prior.model.probability))
                    if delta is None and prior.model.probability is not None and rec.model.probability is not None:
                        delta = (rec.model.probability - prior.model.probability) * 100.0
                    break
        # series is newest-first from `recent`; store chronological
        rec.series = list(reversed(series))
        rec.delta_pp_vs_prev = round(delta, 4) if delta is not None else None
        rec.is_new_today = not series


def score_run(
    run_date: date,
    records: list[PredictionRecord],
    prior_runs: list[RunArtifact],
    window: int,
) -> tuple[float | None, float | None, list[CalibrationRow], list[ExclusionCount]]:
    """Aggregate self-scoring over the prior settled window (not today's rows)."""
    start = run_date.isoformat()
    graded: list[tuple[float, int]] = []
    exclusions: dict[str, int] = {}

    for run in prior_runs:
        if run.run_date >= start:
            continue
        for rec in run.predictions:
            if rec.model.probability is None:
                exclusions["NO_MODEL_NUMBERS"] = exclusions.get("NO_MODEL_NUMBERS", 0) + 1
                continue
            status, result = simulate_settlement(
                rec.board_key, run.run_date, rec.line, rec.market_fair_probability
            )
            if status != "settled" or result not in ("win", "loss"):
                exclusions[status.upper()] = exclusions.get(status.upper(), 0) + 1
                continue
            graded.append((rec.model.probability, 1 if result == "win" else 0))

    brier, cal_rows = calibration_table(graded)
    hit_rate = round(sum(o for _p, o in graded) / len(graded), 4) if graded else None
    exclusion_counts = [
        ExclusionCount(reason=r, count=c) for r, c in sorted(exclusions.items(), key=lambda kv: -kv[1])
    ]
    return brier, hit_rate, cal_rows, exclusion_counts


__all__ = [
    "attach_series_and_delta",
    "calibration_table",
    "delta_vs_previous",
    "grade_history",
    "score_run",
    "simulate_settlement",
]
