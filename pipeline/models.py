"""PropStein pipeline — versioned model registry and deterministic inference.

Models here are fixed, seeded functions of (market, line, features, event key,
model version) — NOT LLMs, and no LLM ever feeds them (charter rule 9: the
LLM boundary is OCR data extraction only).

Coverage policy (fail closed, mirroring src/lib/domain/model-registry.ts):
  - "calibrated"   -> probability + uncertainty interval are emitted.
  - "uncalibrated" -> coverage exists but calibration is pending; NO numbers.
  - "none"         -> no coverage at all (NO MODEL COVERAGE in the UI).
  - "unavailable"  -> registry lists the market but the surface is revoked.

Every calibrated output carries: version, probability, 95% uncertainty
interval, limitations, corpus size, data freshness, and per-feature
contributions (charter rule 5 — no naked confidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.determinism import gauss, mulberry32, normal_cdf, normal_pdf, seed_from
from pipeline.features import feature_contributions, feature_specs, projected_mean
from pipeline.schemas import (
    Coverage,
    FeatureContribution,
    ModelBlock,
    UncertaintyInterval,
)


@dataclass(frozen=True)
class ModelEntry:
    model_name: str
    model_version: str
    sport: str
    market: str
    coverage: Coverage
    sigma: float  # residual std of the stat
    se_probability: float  # epistemic SE on the probability scale
    corpus_games: int | None
    data_freshness_utc: str | None
    limitations: tuple[str, ...] = field(default=())


MODEL_REGISTRY: tuple[ModelEntry, ...] = (
    ModelEntry(
        model_name="NFL Receiving Yards Model",
        model_version="REC-V4",
        sport="NFL",
        market="player_reception_yds",
        coverage=Coverage.CALIBRATED,
        sigma=12.4,
        se_probability=0.015,
        corpus_games=428,
        data_freshness_utc=None,  # set at run time (data freshness = run date)
        limitations=(
            "Calibrated on 2024-2026 NFL regular-season games only; playoff contexts are out of corpus.",
            "Does not ingest in-game possession state; assessments are pregame only.",
            "Uncertainty interval reflects line/feature noise only, not injury-scratch risk.",
            "Uncalibrated for games with confirmed precipitation at kickoff.",
        ),
    ),
    ModelEntry(
        model_name="NFL Rushing Yards Model",
        model_version="RUSH-V3",
        sport="NFL",
        market="player_rushing_yds",
        coverage=Coverage.CALIBRATED,
        sigma=14.8,
        se_probability=0.017,
        corpus_games=351,
        data_freshness_utc=None,
        limitations=(
            "Calibrated on 2024-2026 NFL regular-season games only.",
            "Game-script sensitivity is approximated linearly; large spreads widen true uncertainty.",
            "Committee backfields beyond a two-way split are out of corpus.",
        ),
    ),
    ModelEntry(
        model_name="NFL Passing Yards Model",
        model_version="PASS-V2",
        sport="NFL",
        market="player_passing_yds",
        coverage=Coverage.UNCALIBRATED,
        sigma=26.0,
        se_probability=0.020,
        corpus_games=96,
        data_freshness_utc=None,
        limitations=(
            "Calibration corpus below preregistered minimum; probabilities are withheld.",
            "Coverage exists for research continuity only.",
        ),
    ),
    ModelEntry(
        model_name="NBA Points Model",
        model_version="PTS-V5",
        sport="NBA",
        market="player_points",
        coverage=Coverage.CALIBRATED,
        sigma=6.8,
        se_probability=0.014,
        corpus_games=517,
        data_freshness_utc=None,
        limitations=(
            "Calibrated on 2024-2026 NBA regular-season games only.",
            "Blowout garbage-time scenarios are out of corpus; the interval understates tail risk.",
            "Back-to-back fatigue effect is modeled as a single linear flag.",
        ),
    ),
    ModelEntry(
        model_name="NBA Three-Pointers Made Model",
        model_version="THR-V2",
        sport="NBA",
        market="player_threes",
        coverage=Coverage.CALIBRATED,
        sigma=1.65,
        se_probability=0.019,
        corpus_games=389,
        data_freshness_utc=None,
        limitations=(
            "Calibrated on 2024-2026 NBA regular-season games only.",
            "Low-count markets are inherently high-variance; the interval reflects only input noise.",
            "Opponent 3-point defense persistence is weaker than the feature weight implies.",
        ),
    ),
)

_REGISTRY_INDEX: dict[tuple[str, str], ModelEntry] = {
    (m.sport, m.market): m for m in MODEL_REGISTRY
}


def lookup_model(sport: str, market: str) -> ModelEntry | None:
    return _REGISTRY_INDEX.get((sport, market))


def active_model_versions() -> list[str]:
    return sorted({m.model_version for m in MODEL_REGISTRY if m.coverage == Coverage.CALIBRATED})


def assess(
    sport: str,
    market: str,
    selection: str,
    line: float,
    feature_inputs: dict[str, float],
    event_key: str,
    data_freshness_utc: str,
) -> ModelBlock:
    """Deterministic model assessment for one board row (OVER side convention)."""
    entry = lookup_model(sport, market)

    if entry is None:
        return ModelBlock(
            coverage=Coverage.NONE,
            calibration_status="none",
            limitations=["No model exists for this sport and market."],
        )

    if entry.coverage != Coverage.CALIBRATED:
        return ModelBlock(
            model_name=entry.model_name,
            model_version=entry.model_version,
            coverage=Coverage.UNCALIBRATED,
            calibration_status="uncalibrated",
            limitations=list(entry.limitations),
            corpus_games=entry.corpus_games,
            data_freshness_utc=data_freshness_utc,
        )

    # Deterministic pseudo-signal: a seeded per-(model, event) adjustment to
    # the projected mean. Fixed function of stable keys — reproducible.
    rand = mulberry32(seed_from(entry.model_version, event_key))
    signal_yards = gauss(rand) * entry.sigma * 0.18

    mu_hat = projected_mean(market, line, feature_inputs) + signal_yards
    z = (mu_hat - line) / entry.sigma
    p_over = normal_cdf(z)
    p = p_over if selection == "over" else 1.0 - p_over

    lower = max(0.01, p - 1.96 * entry.se_probability)
    upper = min(0.99, p + 1.96 * entry.se_probability)
    # Guard: probability must lie inside its interval (schema invariant).
    if not (lower <= p <= upper):
        mid = (lower + upper) / 2.0
        lower, upper = min(lower, p), max(upper, p)
        if not (lower <= mid <= upper):  # pragma: no cover — defensive
            lower, upper = 0.01, 0.99

    contributions = [
        FeatureContribution(
            name=c["name"],
            label=c["label"],
            value=c["value"],
            weight=c["weight"],
            contribution_pp=_contribution_pp(z, entry.sigma, c["contribution"]),
        )
        for c in feature_contributions(market, line, feature_inputs)
    ]

    return ModelBlock(
        model_name=entry.model_name,
        model_version=entry.model_version,
        coverage=Coverage.CALIBRATED,
        probability=round(p, 4),
        uncertainty=UncertaintyInterval(lower=round(lower, 4), upper=round(upper, 4)),
        calibration_status="calibrated",
        limitations=list(entry.limitations),
        corpus_games=entry.corpus_games,
        data_freshness_utc=data_freshness_utc,
        features=contributions,
    )


def _contribution_pp(z: float, sigma: float, stat_contribution: float) -> float:
    """Marginal probability contribution (pp) of one feature's stat shift.

    p_with  = Phi(z);  p_without = Phi(z - contribution/sigma)
    contribution_pp = (p_with - p_without) * 100
    """
    if stat_contribution == 0.0:
        return 0.0
    p_with = normal_cdf(z)
    p_without = normal_cdf(z - stat_contribution / sigma)
    return round((p_with - p_without) * 100.0, 3)


def model_sigma(sport: str, market: str) -> float | None:
    entry = lookup_model(sport, market)
    return entry.sigma if entry else None


__all__ = [
    "MODEL_REGISTRY",
    "ModelEntry",
    "active_model_versions",
    "assess",
    "lookup_model",
    "model_sigma",
    "normal_pdf",
]
