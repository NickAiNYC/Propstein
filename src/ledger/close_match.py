"""Close matching. A line change is unmatched and is never a price-only comparison."""

from __future__ import annotations

from dataclasses import dataclass

LINE_CHANGED = "LINE_CHANGED"
MARKET_MISMATCH = "MARKET_MISMATCH"
SELECTION_MISMATCH = "SELECTION_MISMATCH"
SETTLEMENT_RULES_MISMATCH = "SETTLEMENT_RULES_MISMATCH"
MISSING_SETTLEMENT_RULES = "MISSING_SETTLEMENT_RULES"
EVENT_MISMATCH = "EVENT_MISMATCH"


@dataclass(frozen=True)
class CloseQuote:
    event_id: str
    market: str
    selection: str
    line: float
    settlement_rules: str | None
    over_american_odds: int | None = None
    under_american_odds: int | None = None


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reason_code: str | None


def _same_line(left: float, right: float) -> bool:
    return round(float(left), 4) == round(float(right), 4)


def match_close(expected: CloseQuote, observed: CloseQuote) -> MatchResult:
    """Require the same event, market, selection, line, and settlement rules.

    Odds are not read unless every identity field matches. A different line
    returns LINE_CHANGED and does not compare prices.
    """
    if expected.event_id != observed.event_id:
        return MatchResult(False, EVENT_MISMATCH)
    if expected.market != observed.market:
        return MatchResult(False, MARKET_MISMATCH)
    if expected.selection != observed.selection:
        return MatchResult(False, SELECTION_MISMATCH)
    if not expected.settlement_rules or not observed.settlement_rules:
        return MatchResult(False, MISSING_SETTLEMENT_RULES)
    if expected.settlement_rules != observed.settlement_rules:
        return MatchResult(False, SETTLEMENT_RULES_MISMATCH)
    if not _same_line(expected.line, observed.line):
        return MatchResult(False, LINE_CHANGED)
    return MatchResult(True, None)
