"""
PropStein Ingestion Data Contract — Availability & Injury Feeds
Strict validation of player injury status, designation, and vacated volume impact.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


VALID_DESIGNATIONS = {
    "OUT",
    "QUESTIONABLE",
    "DOUBTFUL",
    "IR",
    "PUP",
    "SUSPENDED",
    "HEALTH_SAFETY",
    "AVAILABLE",
    "ACTIVE",
    "PROBABLE",
}


class InjuryEntry(BaseModel):
    player_id: Optional[str] = None
    player_name: str = Field(..., min_length=1)
    team: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    designation: Optional[str] = None
    injury_desc: Optional[str] = None
    vacated_targets: Optional[float] = Field(default=0.0, ge=0.0)
    vacated_air_yards: Optional[float] = Field(default=0.0, ge=0.0)
    vacated_minutes: Optional[float] = Field(default=0.0, ge=0.0)
    last_updated: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("player_name", "team", "status")
    @classmethod
    def clean_str(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field cannot be empty")
        return s

    @model_validator(mode="after")
    def normalize_status(self) -> InjuryEntry:
        st = self.status.upper().strip()
        # Verify valid designation keyword
        matched = any(kw in st for kw in VALID_DESIGNATIONS)
        if not matched and st not in VALID_DESIGNATIONS:
            raise ValueError(f"Unknown injury status/designation: '{self.status}'")
        return self


class AvailabilityFeed(BaseModel):
    feed_timestamp: Optional[str] = None
    sport: str = Field(default="nfl")
    injuries: List[InjuryEntry] = Field(default_factory=list)
    vacated_minutes_total: Optional[float] = Field(default=0.0, ge=0.0)
    vacated_targets_total: Optional[float] = Field(default=0.0, ge=0.0)

    model_config = {"extra": "allow"}
