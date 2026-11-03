"""Contract for immutable freeze records published to the viewer."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SnapshotRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    snapshot_id: str = Field(min_length=1)
    snapshot_type: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    slate: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    projection: dict[str, Any]
    quote: dict[str, Any]
    content_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def verify_content_hash(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("snapshot must be an object")
        payload = {key: item for key, item in value.items() if key != "content_hash"}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if value.get("content_hash") != digest:
            raise ValueError("snapshot content hash mismatch")
        return value
