"""PropStein pipeline — feature engineering.

MARKET_FEATURES declares the per-market feature vector: name, label, range,
and the model weight (units of the stat per unit feature). The synthetic feed
generates feature values from these specs; licensed feeds supply them in the
slate document. Inference consumes them additively:

    mu_hat = line + sum_i weight_i * (x_i - ref_i)

so each feature's contribution to the projected mean is separable, auditable,
and reproducible — the "raw factors driving today's prediction" in the
drill-down drawer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    lo: float
    hi: float
    weight: float  # stat units per unit feature
    ref: float  # neutral reference value (contribution = weight * (x - ref))


@dataclass(frozen=True)
class MarketSpec:
    market: str
    stat_unit: str  # "yds" | "pts" | "rec" | "made"
    sigma: float  # residual std of the stat around mu_hat (per model version)
    features: tuple[FeatureSpec, ...]


_F = FeatureSpec

MARKET_FEATURES: dict[str, tuple[FeatureSpec, ...]] = {
    "player_reception_yds": (
        _F("target_share", "Target share", 0.14, 0.32, 210.0, 0.23),
        _F("air_yards_avg", "Average air yards per target", 6.0, 12.5, 3.4, 9.25),
        _F("opponent_cb_rating", "Opponent CB coverage rating", 55.0, 92.0, 0.55, 73.5),
        _F("pace_index", "Game pace index", 0.88, 1.14, 28.0, 1.01),
        _F("usage_trend", "3-game usage trend", -0.25, 0.25, 30.0, 0.0),
    ),
    "player_rushing_yds": (
        _F("carry_share", "Carry share", 0.35, 0.78, 118.0, 0.56),
        _F("ypc_season", "Season yards per carry", 3.2, 5.6, 16.5, 4.4),
        _F("def_box_rating", "Defensive box rating", 48.0, 88.0, 0.62, 68.0),
        _F("game_script_proj", "Projected game script", -1.0, 1.0, 12.0, 0.0),
        _F("pace_index", "Game pace index", 0.88, 1.14, 14.0, 1.01),
    ),
    "player_passing_yds": (
        _F("dropback_share", "Dropback share", 0.48, 0.72, 540.0, 0.60),
        _F("aoty_avg", "Average air yards per attempt", 6.2, 9.8, 22.0, 8.0),
        _F("pocket_time", "Average pocket time (s)", 2.2, 2.9, 46.0, 2.55),
        _F("opponent_pass_d", "Opponent pass defense rating", 52.0, 90.0, 1.9, 71.0),
    ),
    "player_points": (
        _F("usage_rate", "Usage rate", 0.16, 0.34, 52.0, 0.25),
        _F("minutes_proj", "Projected minutes", 24.0, 38.0, 1.05, 31.0),
        _F("pace_index", "Game pace index", 0.92, 1.12, 16.0, 1.02),
        _F("ft_rate", "Free-throw rate", 0.12, 0.34, 9.0, 0.23),
        _F("back_to_back", "Back-to-back flag (0/1)", 0.0, 1.0, -2.5, 0.0),
    ),
    "player_threes": (
        _F("three_pa_rate", "3-point attempt rate", 0.28, 0.58, 7.6, 0.43),
        _F("three_pct_season", "Season 3-point %", 0.31, 0.42, 12.0, 0.365),
        _F("minutes_proj", "Projected minutes", 22.0, 38.0, 0.11, 30.0),
        _F("opponent_3p_d", "Opponent 3-point defense", 0.32, 0.40, 14.0, 0.36),
    ),
}


def feature_specs(market: str) -> tuple[FeatureSpec, ...]:
    return MARKET_FEATURES.get(market, ())


def projected_mean(market: str, line: float, feature_inputs: dict[str, float]) -> float:
    """Additive feature model: mu_hat = line + sum weight*(x - ref)."""
    mu = line
    for spec in feature_specs(market):
        x = feature_inputs.get(spec.name)
        if x is None:
            continue  # missing features contribute zero (fail-open at the mean, uncertainty widens)
        x = min(spec.hi, max(spec.lo, x))
        mu += spec.weight * (x - spec.ref)
    return mu


def feature_contributions(
    market: str,
    line: float,
    feature_inputs: dict[str, float],
) -> list[dict[str, float]]:
    """Per-feature contribution to the projected mean, in stat units."""
    out: list[dict[str, float]] = []
    for spec in feature_specs(market):
        x = feature_inputs.get(spec.name)
        if x is None:
            continue
        x = min(spec.hi, max(spec.lo, x))
        out.append(
            {
                "name": spec.name,
                "label": spec.label,
                "value": x,
                "weight": spec.weight,
                "contribution": spec.weight * (x - spec.ref),
            }
        )
    return out
