"""
PropStein Ingestion Data Contracts & Fail-Closed Gate
"""

from src.contracts.odds import OddsQuote, LiveOddsFeed, QuoteEvaluation
from src.contracts.slate import SlateRow, SlateUniverse
from src.contracts.availability import InjuryEntry, AvailabilityFeed
from src.contracts.gate import validate_and_publish

__all__ = [
    "OddsQuote",
    "LiveOddsFeed",
    "QuoteEvaluation",
    "SlateRow",
    "SlateUniverse",
    "InjuryEntry",
    "AvailabilityFeed",
    "validate_and_publish",
]
