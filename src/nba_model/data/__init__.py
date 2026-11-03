"""Data-layer building blocks: normalized providers + tidy dataset assembly."""

from __future__ import annotations

from .providers import (
    BalldontlieProvider,
    FixtureProvider,
    SyntheticSeasonProvider,
    MissingKeyError,
    TierError,
)
from .dataset import build_dataset

__all__ = [
    "BalldontlieProvider",
    "FixtureProvider",
    "SyntheticSeasonProvider",
    "MissingKeyError",
    "TierError",
    "build_dataset",
]
