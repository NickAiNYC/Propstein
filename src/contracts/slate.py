"""
PropStein Ingestion Data Contract — Slates & Player Projections
Strict validation of modeled projection rows, intervals, distributions, and universes.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any, Union
import math
from pydantic import BaseModel, Field, field_validator, model_validator


class SlateRow(BaseModel):
    player_id: str = Field(..., min_length=1)
    player_display_name: Optional[str] = None
    full_name: Optional[str] = None
    team: Optional[str] = None
    position: Optional[str] = None
    position_hist: Optional[str] = None
    opponent_team: Optional[str] = None
    status: Optional[str] = None
    
    # Projections / Expectations (NFL or generic)
    proj_rec: Optional[float] = None
    proj_yards: Optional[float] = None
    fair_line_rec: Optional[float] = None
    fair_line_yards: Optional[float] = None
    
    # Generic market format
    market: Optional[str] = None
    proj_volume: Optional[float] = None
    fair_line: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None

    # Extra fields allowed for backward compatibility with stats/features
    model_config = {"extra": "allow"}

    @field_validator("player_id")
    @classmethod
    def validate_player_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("player_id must not be blank")
        return s

    @model_validator(mode="after")
    def validate_projections(self) -> SlateRow:
        # Check non-negative projection values if present
        for key in ["proj_rec", "proj_yards", "fair_line_rec", "fair_line_yards", "proj_volume", "fair_line"]:
            val = getattr(self, key, None)
            if val is not None:
                if not math.isfinite(val) or val < 0.0:
                    raise ValueError(f"Field {key} must be finite non-negative number, got {val}")

        # If CI bounds present, ensure ci_low <= ci_high
        if self.ci_low is not None and self.ci_high is not None:
            if self.ci_low > self.ci_high:
                raise ValueError(f"ci_low ({self.ci_low}) cannot exceed ci_high ({self.ci_high})")
        return self


class SlateUniverse(BaseModel):
    slate_key: Optional[str] = None
    rows: List[SlateRow] = Field(..., min_length=1)
    min_players_threshold: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def check_slate_integrity(self) -> SlateUniverse:
        if len(self.rows) < self.min_players_threshold:
            raise ValueError(
                f"Slate universe contains only {len(self.rows)} rows, "
                f"minimum threshold is {self.min_players_threshold}"
            )

        # Check duplicates: (player_id, market) pairs must be unique
        seen = set()
        duplicates = []
        for r in self.rows:
            m = r.market or "default"
            key = (r.player_id, m)
            if key in seen:
                duplicates.append(key)
            seen.add(key)

        if duplicates:
            raise ValueError(f"Found {len(duplicates)} duplicate player/market records in slate: {duplicates[:5]}")
        return self
