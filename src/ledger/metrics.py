"""Price metrics in probability percentage points, per selected outcome.

intended_clv and placement_clv are the only CLV figures. model_vs_close is a
diagnostic and is never labeled CLV. A line change is unmatched, so no price
comparison is computed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.ledger.close_match import CloseQuote, MatchResult, match_close

# Differences of probabilities on the 0-1 scale, reported in percentage points.
_PP = 100.0


def _devig_selected(over_odds: int, under_odds: int, selection: str) -> float:
    from src.model import devig_two_way

    over_prob, under_prob = devig_two_way(float(over_odds), float(under_odds))
    if selection == "over":
        return float(over_prob)
    if selection == "under":
        return float(under_prob)
    raise ValueError("selection must be over or under")


def intended_clv_pp(close_devig_prob: float, intended_entry_implied_prob: float) -> float:
    """close_devig_prob minus the intended entry's devigged probability, in percentage points."""
    return (close_devig_prob - intended_entry_implied_prob) * _PP


def placement_clv_pp(close_devig_prob: float, achieved_entry_implied_prob: float) -> float:
    """close_devig_prob minus the achieved entry's devigged probability, in percentage points."""
    return (close_devig_prob - achieved_entry_implied_prob) * _PP


def execution_slippage_pp(achieved_implied: float, intended_implied: float) -> float:
    """Achieved minus intended, in percentage points. Positive means a worse price."""
    return (achieved_implied - intended_implied) * _PP


def model_vs_close_pp(model_prob: float, close_devig_prob: float) -> float:
    """Diagnostic only. Not CLV."""
    return (model_prob - close_devig_prob) * _PP


@dataclass(frozen=True)
class PriceMetrics:
    intended_clv: float | None
    placement_clv: float | None
    execution_slippage: float | None
    model_vs_close: float | None
    committed_match: MatchResult | None
    placement_match: MatchResult | None
    unit: str = "probability_percentage_points"

    def as_dict(self) -> dict:
        return {
            "unit": self.unit,
            "intended_clv": self.intended_clv,
            "placement_clv": self.placement_clv,
            "execution_slippage": self.execution_slippage,
            "model_vs_close": self.model_vs_close,
            "committed_close_reason": None if self.committed_match is None else self.committed_match.reason_code,
            "placement_close_reason": None if self.placement_match is None else self.placement_match.reason_code,
        }


def _implied(quote: CloseQuote) -> float | None:
    if quote.over_american_odds is None or quote.under_american_odds is None:
        return None
    return _devig_selected(quote.over_american_odds, quote.under_american_odds, quote.selection)


def evaluate_prices(
    *,
    intended: CloseQuote | None,
    placement: CloseQuote | None,
    committed_close: CloseQuote | None,
    placement_close: CloseQuote | None,
    model_probability: float | None,
) -> PriceMetrics:
    """CLV is computed only for a matched close. Unplaced observations have no placement_clv."""
    committed_match = None
    placement_match = None
    intended_clv = None
    placement_clv = None
    slippage = None
    diagnostic = None

    intended_prob = _implied(intended) if intended is not None else None
    achieved_prob = _implied(placement) if placement is not None else None

    if intended is not None and placement is not None and intended_prob is not None and achieved_prob is not None:
        slippage = execution_slippage_pp(achieved_prob, intended_prob)

    if intended is not None and committed_close is not None:
        committed_match = match_close(intended, committed_close)
        if committed_match.matched and intended_prob is not None:
            close_prob = _implied(committed_close)
            if close_prob is not None:
                intended_clv = intended_clv_pp(close_prob, intended_prob)
                if model_probability is not None:
                    diagnostic = model_vs_close_pp(model_probability, close_prob)
    elif committed_close is None and intended is not None:
        committed_match = MatchResult(False, "MISSING_CLOSE")

    if placement is None:
        placement_clv = None
        if placement_close is not None:
            placement_match = MatchResult(False, "UNPLACED")
    elif placement_close is None:
        placement_match = MatchResult(False, "MISSING_CLOSE")
    else:
        placement_match = match_close(placement, placement_close)
        if placement_match.matched and achieved_prob is not None:
            close_prob = _implied(placement_close)
            if close_prob is not None:
                placement_clv = placement_clv_pp(close_prob, achieved_prob)

    return PriceMetrics(
        intended_clv=intended_clv,
        placement_clv=placement_clv,
        execution_slippage=slippage,
        model_vs_close=diagnostic,
        committed_match=committed_match,
        placement_match=placement_match,
    )
