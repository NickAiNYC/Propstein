"""Publish gates — fail-closed, reason-explicit.

Three gates, all must pass before a board exists:
  1. FRESHNESS    box scores recent enough, quotes fresh enough
  2. CALIBRATION  enough walk-forward records, slope inside band, Brier no
                  worse than the naive baseline (market delta is reported
                  on the receipt, never gated — visibility beats silence)
  3. INDEPENDENT QUOTES  per play: >= 2 distinct books on the exact
                  market+line inside the freshness window

A failed gate produces a REFUSAL artifact (never an empty-but-ranked board).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .. import config
from ..data.timeutils import parse_iso_utc


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class GateReport:
    gate: str
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def fail_reasons(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "all_passed": self.all_passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _naive_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """Normalize any timestamp (aware or naive) to naive UTC for arithmetic."""
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC").tz_localize(None)
    return ts


# ── 1. freshness ────────────────────────────────────────────────────────────

def evaluate_freshness_gate(
    dataset_meta: dict,
    odds_quotes: list[dict] | None,
    availability_as_of: str | None = None,
    now: pd.Timestamp | None = None,
) -> GateReport:
    report = GateReport(gate="freshness")
    now = _naive_utc(now or pd.Timestamp.utcnow().tz_localize(None))

    max_date = dataset_meta.get("max_game_date")
    if not max_date:
        report.checks.append(GateCheck("boxscore_recency", False, "dataset has no played games"))
        return report
    data_boundary = pd.Timestamp(
        f"{max_date}T23:59:00-05:00"
    ).tz_convert("UTC").tz_localize(None)
    age_hours = (now - data_boundary).total_seconds() / 3600.0
    report.checks.append(GateCheck(
        "boxscore_recency",
        age_hours <= config.BOXSCORE_MAX_AGE_HOURS,
        f"latest data {max_date} ET-end, {age_hours:.1f}h old "
        f"(limit {config.BOXSCORE_MAX_AGE_HOURS:.0f}h)",
    ))

    quotes = odds_quotes or []
    if not quotes:
        report.checks.append(GateCheck(
            "quote_recency", False, "no quotes supplied — independent-quote gate cannot pass",
        ))
        return report
    latest = max(str(q.get("observed_at", "")) for q in quotes)
    obs_dt = parse_iso_utc(latest)
    if obs_dt is None:
        report.checks.append(GateCheck("quote_recency", False, f"unparseable observed_at: {latest!r}"))
        return report
    age_seconds = (now - _naive_utc(pd.Timestamp(obs_dt))).total_seconds()
    report.checks.append(GateCheck(
        "quote_recency",
        0 <= age_seconds <= config.ODDS_MAX_AGE_SECONDS,
        f"latest quote {latest} ({age_seconds/60:.1f} min old, limit "
        f"{config.ODDS_MAX_AGE_SECONDS/60:.0f} min)",
    ))

    if availability_as_of:
        avail_dt = parse_iso_utc(availability_as_of)
        if avail_dt is not None:
            avail_age_h = (now - _naive_utc(pd.Timestamp(avail_dt))).total_seconds() / 3600.0
            report.checks.append(GateCheck(
                "availability_recency",
                0 <= avail_age_h <= config.AVAILABILITY_MAX_AGE_HOURS,
                f"availability feed {avail_age_h:.1f}h old "
                f"(limit {config.AVAILABILITY_MAX_AGE_HOURS:.0f}h)",
            ))
    return report


# ── 2. calibration ──────────────────────────────────────────────────────────

def evaluate_calibration_gate(summary: dict) -> GateReport:
    report = GateReport(gate="calibration")
    n = summary.get("n", 0)
    report.checks.append(GateCheck(
        "min_predictions",
        n >= config.MIN_PREDICTIONS,
        f"n={n} scored predictions (need {config.MIN_PREDICTIONS})",
    ))

    slope = summary.get("calibration_slope")
    slope_ok = slope is not None and config.SLOPE_MIN <= slope <= config.SLOPE_MAX
    report.checks.append(GateCheck(
        "reliability_slope",
        slope_ok,
        f"slope={slope} (band [{config.SLOPE_MIN}, {config.SLOPE_MAX}])"
        if slope is not None else "slope undefined — predictions degenerate or n too small",
    ))

    b_model, b_naive = summary.get("brier_model"), summary.get("brier_naive")
    brier_ok = (
        b_model is not None and b_naive is not None
        and b_model <= b_naive + config.BRIER_VS_NAIVE_MARGIN
    )
    report.checks.append(GateCheck(
        "brier_vs_naive",
        brier_ok,
        f"model Brier {b_model} vs naive {b_naive}"
        if b_model is not None and b_naive is not None else "Brier scores unavailable",
    ))

    if summary.get("brier_vs_market") is not None:
        delta = summary["brier_vs_market"]
        report.checks.append(GateCheck(
            "brier_vs_market_REPORTED",
            True,
            f"model minus market Brier = {delta:+.5f} "
            f"({'model ahead' if delta < 0 else 'market ahead — visible, not gated'})",
        ))
    return report


# ── 3. independent quotes (per play) ────────────────────────────────────────

def evaluate_play_quote_gate(consensus: dict, now: pd.Timestamp | None = None) -> GateReport:
    report = GateReport(gate="independent_quotes")
    n_books = consensus.get("n_books", 0)
    report.checks.append(GateCheck(
        "distinct_books",
        n_books >= config.MIN_INDEPENDENT_BOOKS,
        f"{n_books} distinct books on this exact line (need "
        f"{config.MIN_INDEPENDENT_BOOKS})",
    ))
    n_src = consensus.get("distinct_sources", 0)
    report.checks.append(GateCheck(
        "distinct_sources_REPORTED",
        True,
        f"{n_src} distinct source strings behind {n_books} books "
        "(informational only — BOOKS are the independence unit; a single "
        "licensed odds feed legitimately serves many books)",
    ))
    obs = consensus.get("latest_observed_at")
    obs_dt = parse_iso_utc(obs)
    if obs_dt is None:
        report.checks.append(GateCheck("quote_freshness", False, f"unparseable observed_at: {obs!r}"))
    else:
        now = _naive_utc(now or pd.Timestamp.utcnow().tz_localize(None))
        age = (now - _naive_utc(pd.Timestamp(obs_dt))).total_seconds()
        report.checks.append(GateCheck(
            "quote_freshness",
            0 <= age <= config.ODDS_MAX_AGE_SECONDS,
            f"latest quote {age/60:.1f} min old (limit {config.ODDS_MAX_AGE_SECONDS/60:.0f} min)",
        ))
    return report
