"""Balldontlie games and boxscore evidence contracts."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NbaGame(BaseModel):
    model_config = ConfigDict(extra="allow")
    game_id: str = Field(pattern=r"^bdl-\d+$")
    gameday: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tipoff_utc: datetime
    away_team: str = Field(min_length=2, max_length=4)
    home_team: str = Field(min_length=2, max_length=4)
    source: str = Field(pattern=r"^balldontlie$")
    fixture: bool = Field(alias="_fixture")

    @model_validator(mode="after")
    def verify(self):
        if self.fixture or self.tipoff_utc.tzinfo is None or self.away_team == self.home_team:
            raise ValueError("invalid live NBA game")
        return self


class NbaBoxscoreRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    game_id: str = Field(pattern=r"^bdl-\d+$")
    player_id: str = Field(pattern=r"^bdl-\d+$")
    player_display_name: str = Field(min_length=1)
    team: str = Field(min_length=2, max_length=4)
    pts: int | None = Field(default=None, ge=0)
    rebounds: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    fg3m: int | None = Field(default=None, ge=0)
    source: str = Field(pattern=r"^balldontlie$")
    fixture: bool = Field(alias="_fixture")

    @model_validator(mode="after")
    def verify(self):
        if self.fixture:
            raise ValueError("fixture row in live boxscore")
        return self


class NbaBoxscoreFeed(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = Field(pattern=r"^nba\.v1$")
    fixture: bool = Field(alias="_fixture")
    generated_at: datetime
    source: str = Field(pattern=r"^balldontlie$")
    rows: list[NbaBoxscoreRow]

    @model_validator(mode="after")
    def verify(self):
        if self.fixture or self.generated_at.tzinfo is None:
            raise ValueError("invalid live boxscore feed")
        return self
