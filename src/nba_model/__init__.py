"""
nba_model — PropWire's independent NBA player-points model.

DESIGN CONTRACT (user-approved, v177 era):

  1. This is NOT the NFL model. The NFL NegBin-Gamma receiving stack
     (src/model.py) models receptions + receiving yards. NBA points are a
     different generative process (minutes-driven, no point mass at zero
     for rotation players, different tail). Nothing is imported from it.

  2. No external GitHub model is imported wholesale. The four evaluated
     repositories (see DECISIONS.md) contribute METHODOLOGY ONLY:
     date-based walk-forward validation, de-vig comparison, and gate
     discipline. No prediction, no serialized model, no scraped data.

  3. Interpretable v1 only:
        expected minutes  -> points-per-minute -> rolling 5/10/20 form
        -> pace & opponent adjustments -> injury/rotation adjustments
        -> predictive mean AND variance.
     Every projection row carries an `explain` dict so any number on the
     board can be traced to its components.

  4. Publishing is fail-closed and receipt-chained, reusing PropWire's
     existing trust primitives (src/crypto_utils.py, RFC-8785 canonical
     JSON + SHA-256). A board is emitted only when the freshness,
     calibration and independent-quote gates all pass; otherwise an
     explicit refusal with reasons is written instead.

Data source (Phase 0.5 gate, user-approved): balldontlie NBA API box
scores (ALL-STAR tier or higher). See data/providers.py.
"""

__all__ = ["MODEL_FAMILY", "__version__"]

MODEL_FAMILY = "nba-points"
__version__ = "1.0.0"
