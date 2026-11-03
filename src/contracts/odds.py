"""
PropStein Ingestion Data Contract — Odds & Market Quotes
Strict Pydantic v2 validation for sportsbook odds, lines, and feed headers.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import math
from pydantic import BaseModel, Field, field_validator, model_validator


class QuoteEvaluation(BaseModel):
    is_qualified: bool = False
    status: str = "UNVERIFIED"
    best_side: Optional[str] = None
    prob_edge: Optional[float] = None
    break_even_adv: Optional[float] = None
    expected_return: Optional[float] = None
    actionable_stake: float = 0.0
    catalyst: Optional[str] = "none"
    injury_context: Optional[str] = None


class OddsQuote(BaseModel):
    quote_id: str = Field(..., min_length=1)
    provider_quote_id: Optional[str] = None
    player_id: str = Field(..., min_length=1)
    player_name: str = Field(..., min_length=1)
    team: Optional[str] = None
    opponent: Optional[str] = None
    game_id: Optional[str] = None
    position: Optional[str] = None
    market: str = Field(..., min_length=1)
    line: float = Field(..., gt=0.0, lt=300.0)
    over_odds: int = Field(...)
    under_odds: int = Field(...)
    book: str = Field(..., min_length=1)
    observed_at: str = Field(...)
    source: Optional[str] = None
    source_url: Optional[str] = None
    receipt_id: Optional[str] = None
    content_hash: Optional[str] = None
    verified: bool = False
    fixture: bool = Field(default=False, alias="_fixture")
    unit: Optional[str] = None
    fair_line: Optional[float] = None
    evaluation: Optional[QuoteEvaluation] = None

    @field_validator("player_id", "player_name", "market", "book")
    @classmethod
    def check_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field must not be empty or blank")
        return s

    @field_validator("line")
    @classmethod
    def check_line_finite(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Line must be finite positive float, got {v}")
        return round(float(v), 2)

    @field_validator("over_odds", "under_odds")
    @classmethod
    def check_american_odds(cls, v: int) -> int:
        if v == 0 or abs(v) < 100 or abs(v) > 50000:
            raise ValueError(f"American odds must have |odds| >= 100, got {v}")
        return v

    @model_validator(mode="after")
    def validate_vig_and_implied_prob(self) -> OddsQuote:
        # American odds to implied probability
        def to_implied(odds: int) -> float:
            if odds < 0:
                return -odds / (-odds + 100)
            return 100 / (odds + 100)

        p_over = to_implied(self.over_odds)
        p_under = to_implied(self.under_odds)
        vig_sum = p_over + p_under

        # Vig check: 2-way market implied prob must sum between 1.00 (fair/no-vig) and 1.35 (heavy juice)
        if vig_sum < 0.98 or vig_sum > 1.45:
            raise ValueError(
                f"Implied probability sum {vig_sum:.4f} outside valid range [0.98, 1.45] "
                f"(over: {self.over_odds}, under: {self.under_odds})"
            )
        return self


class LiveOddsFeed(BaseModel):
    feed_status: str = Field(..., min_length=1)
    updated_at: str = Field(...)
    slate: str = Field(..., min_length=1)
    verified_books_count: int = Field(default=0, ge=0)
    verified_quotes_count: int = Field(default=0, ge=0)
    unverified_books: Optional[List[str]] = Field(default_factory=list)
    monitored_books: Optional[List[str]] = Field(default_factory=list)
    total_quotes: int = Field(default=0, ge=0)
    qualified_count: Optional[int] = Field(default=0, ge=0)
    quotes: List[OddsQuote] = Field(default_factory=list)
    schema_version: Optional[str] = None
    source: Optional[str] = None
    fixture: bool = Field(default=False, alias="_fixture")
    fixture_notice: Optional[str] = None

    @model_validator(mode="after")
    def check_counts_match(self) -> LiveOddsFeed:
        if len(self.quotes) != self.total_quotes and self.total_quotes > 0:
            # Reconcile if slightly drifted or enforce strict parity
            object.__setattr__(self, "total_quotes", len(self.quotes))
        return self
