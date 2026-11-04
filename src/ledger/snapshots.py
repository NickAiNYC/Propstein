"""Resolve model fields from PropStein's stored freeze snapshots.

Client-supplied model fields are ignored by the API. Frozen snapshots
(negbin-gamma-v3.2 in the week journals) do not carry an uncertainty interval,
so that interval stays null. Probability at the requested line is computed
from the snapshot's stored distribution parameters with the same functions
that wrote the snapshot. It is stored, and withheld from responses while
coverage is uncalibrated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MARKET_TO_SNAPSHOT = {
    "player_receptions": "receptions",
    "receptions": "receptions",
    "player_reception_yds": "receiving_yards",
    "player_reception_yards": "receiving_yards",
    "receiving_yards": "receiving_yards",
}
CANONICAL_MARKET = {
    "receptions": "player_receptions",
    "receiving_yards": "player_reception_yds",
}


@dataclass(frozen=True)
class ServerSnapshot:
    snapshot_id: str
    content_hash: str
    created_at: datetime
    game_id: str
    player_id: str
    player_name: str | None
    team: str | None
    opponent: str | None
    market: str
    canonical_market: str
    model_version: str
    fair_line: float
    projected_volume: float
    distribution_params: dict
    model_probability: float


def coverage_label(root: Path | None = None) -> str:
    """This release reports uncalibrated coverage.

    The published week-1 holdout Brier skill is negative. A missing file also
    stays uncalibrated. This function does not promote coverage.
    """
    del root
    return "uncalibrated"


def published_brier_skill(root: Path) -> float | None:
    path = root / "viewer" / "holdout_eval_2026_w1.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return float(payload["metrics"]["brier_skill_score_pct"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _aware(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _probability(market: str, params: dict, line: float, selection: str) -> float | None:
    try:
        mu_rec = float(params["mu_rec"])
        mu_ypr = float(params["mu_ypr"])
        alpha = float(params["alpha"])
        k = float(params["k"])
    except (KeyError, TypeError, ValueError):
        return None
    from src.freeze_slate import ReceivingModel, compute_rec_probs, compute_yards_probs

    if market == "receptions":
        over, under, _push = compute_rec_probs(mu_rec, line, alpha)
    else:
        model = ReceivingModel(None, None, alpha, k, None, None, None)
        over, under, _push = compute_yards_probs(model, mu_rec, mu_ypr, line)
    if selection == "over":
        return float(over)
    if selection == "under":
        return float(under)
    return None


def _hash_ok(row: dict) -> bool:
    from src.freeze_slate import compute_canonical_hash

    payload = {key: value for key, value in row.items() if key != "content_hash"}
    return row.get("content_hash") == compute_canonical_hash(payload)


class SnapshotStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self._rows: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        rows: list[dict] = []
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("snapshots_*.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict) and _hash_ok(row):
                        rows.append(row)
        self._rows = rows
        return rows

    def resolve(
        self,
        *,
        player_id: str,
        market: str,
        line: float,
        selection: str,
        observed_at: datetime,
    ) -> ServerSnapshot | None:
        internal = MARKET_TO_SNAPSHOT.get(market)
        if internal is None:
            return None
        chosen: dict | None = None
        chosen_at: datetime | None = None
        for row in self._load():
            if str(row.get("player_id")) != player_id or row.get("market") != internal:
                continue
            if row.get("snapshot_type") not in (None, "pre_kickoff"):
                continue
            created = _aware(str(row.get("created_at") or ""))
            if created is None or created > observed_at:
                continue
            if chosen_at is None or created >= chosen_at:
                chosen = row
                chosen_at = created
        if chosen is None or chosen_at is None:
            return None
        projection = chosen.get("projection") or {}
        params = projection.get("distribution_params") or {}
        probability = _probability(internal, params, line, selection)
        version = str((chosen.get("model") or {}).get("version") or "")
        if probability is None or not version:
            return None
        try:
            fair_line = float(projection["fair_line"])
            projected_volume = float(projection["proj_volume"])
        except (KeyError, TypeError, ValueError):
            return None
        return ServerSnapshot(
            snapshot_id=str(chosen["snapshot_id"]),
            content_hash=str(chosen["content_hash"]),
            created_at=chosen_at,
            game_id=str(chosen["game_id"]),
            player_id=player_id,
            player_name=chosen.get("player_name"),
            team=chosen.get("team"),
            opponent=chosen.get("opponent"),
            market=internal,
            canonical_market=CANONICAL_MARKET[internal],
            model_version=version,
            fair_line=fair_line,
            projected_volume=projected_volume,
            distribution_params=dict(params),
            model_probability=probability,
        )
