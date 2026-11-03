"""
Agent 1: InjuryEventAgent (Highest Priority)

Inputs:
  1. Official NFL/NBA injury report RSS/HTML/JSON (parse + SHA-256 receipt)
  2. SportFeeds breaking news webhook (injuries, inactives, lineup changes)
  3. XFlux beat-writer monitor ("out / questionable / scratched / starting")

Cadence: 30-60s polling pregame, webhook-triggered in-game.
Dedup: SHA-256 of normalized `{player_id, status, body_part}` tuple.
Output: `injury.status_changed` -> Redis Stream (`propwire.events.injury`)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from src.agents.persistence import TOPIC_INJURY, DurableRedisStreamBus, TruthStore
from src.agents.schemas import (
    InjuryBeneficiary,
    InjuryEventPayload,
    StructuredAgentLog,
    compute_dedup_hash,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch

logger = logging.getLogger("propwire.agent.injury")

_XFLUX_KEYWORDS = {
    "ruled out": "OUT",
    "is out": "OUT",
    "out tonight": "OUT",
    "inactive": "OUT",
    "scratched": "SCRATCHED",
    "late scratch": "SCRATCHED",
    "will not play": "OUT",
    "doubtful": "DOUBTFUL",
    "questionable": "QUESTIONABLE",
    "game-time decision": "QUESTIONABLE",
    "starting tonight": "STARTING",
    "will start": "STARTING",
    "active": "ACTIVE",
}


class InjuryEventAgent:
    """
    Ingests official league injury reports, SportFeeds webhooks, and XFlux
    beat-writer wires; deduplicates on `{player_id, status, body_part}`;
    publishes `injury.status_changed` to `propwire.events.injury`.
    """

    AGENT_NAME = "InjuryEventAgent"

    def __init__(
        self,
        stream_bus: DurableRedisStreamBus | None = None,
        truth_store: TruthStore | None = None,
        kill_switch: StaleKillSwitch | None = None,
        bus: DurableRedisStreamBus | None = None,
    ):
        self.stream_bus = stream_bus or bus or DurableRedisStreamBus()
        self.truth_store = truth_store or TruthStore()
        self.kill_switch = kill_switch or StaleKillSwitch()
        self._in_memory_dedup: set[str] = set()

    @staticmethod
    def compute_injury_dedup_key(player_id: str, status: str, body_part: str) -> str:
        """Hash normalized `{player_id, status, body_part}` tuple."""
        return compute_dedup_hash(player_id, status.upper(), body_part.lower())

    @staticmethod
    def parse_xflux_beat_writer_text(text: str) -> Literal["OUT", "DOUBTFUL", "QUESTIONABLE", "ACTIVE", "SCRATCHED", "STARTING"] | None:
        lower = text.lower()
        for phrase, status in _XFLUX_KEYWORDS.items():
            if re.search(r"\b" + re.escape(phrase) + r"\b", lower):
                return status  # type: ignore[return-value]
        return None

    def ingest_event(
        self,
        raw_payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Validate, deduplicate, check Stale Kill Switch, persist to `agent_events`,
        and fan-out `injury.status_changed` to Redis Stream `propwire.events.injury`.
        """
        t0 = time.perf_counter()
        source_hash = raw_payload.get("source_hash") or compute_source_hash(raw_payload)
        fetched_at = raw_payload.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        elif not isinstance(fetched_at, datetime):
            fetched_at = datetime.now(timezone.utc)

        # Support XFlux beat-writer raw text parsing if status not explicitly set
        status = raw_payload.get("status")
        if not status and raw_payload.get("raw_text"):
            status = self.parse_xflux_beat_writer_text(str(raw_payload["raw_text"])) or "QUESTIONABLE"

        beneficiaries_raw = raw_payload.get("beneficiaries") or raw_payload.get("impacted_beneficiaries") or []
        beneficiaries = [
            b if isinstance(b, InjuryBeneficiary) else InjuryBeneficiary(**b)
            for b in beneficiaries_raw
        ]

        payload = InjuryEventPayload(
            sport=raw_payload.get("sport", "nba"),
            game_id=raw_payload["game_id"],
            player_id=raw_payload["player_id"],
            player_name=raw_payload.get("player_name", raw_payload["player_id"]),
            team=raw_payload.get("team", "UNK"),
            opponent=raw_payload.get("opponent", "UNK"),
            status=status or "OUT",
            body_part=raw_payload.get("body_part", "undisclosed"),
            source_provider=raw_payload.get("source_provider", "official_report"),
            vacated_minutes=float(raw_payload.get("vacated_minutes", 0.0)),
            vacated_targets=float(raw_payload.get("vacated_targets", 0.0)),
            vacated_usage=float(raw_payload.get("vacated_usage", 0.0)),
            beneficiaries=beneficiaries,
            is_live=bool(raw_payload.get("is_live", False)),
            notes=str(raw_payload.get("notes", "")),
            source_hash=source_hash,
            fetched_at=fetched_at,
        )

        dedup_key = self.compute_injury_dedup_key(payload.player_id, payload.status, payload.body_part)
        is_stale, age_s, limit_s, stale_reason = self.kill_switch.evaluate(
            agent_name=self.AGENT_NAME,
            event_type="injury.status_changed",
            prop_id=f"{payload.game_id}::{payload.player_id}",
            feed_type="injury",
            fetched_at=payload.fetched_at,
            source_hash=source_hash,
            is_live=payload.is_live,
            now=now,
        )

        affected_ids = [payload.player_id] + [b.player_id for b in payload.beneficiaries]
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        # Dedup check: never re-fire on identical {player_id, status, body_part}
        if dedup_key in self._in_memory_dedup or self.truth_store.has_dedup_key(dedup_key):
            reason = f"DEDUP_SKIPPED: identical ({payload.player_id}, {payload.status}, {payload.body_part})"
            self.truth_store.record_agent_event(
                stream_topic=TOPIC_INJURY,
                agent_name=self.AGENT_NAME,
                event_type="injury.status_changed",
                sport=payload.sport,
                affected_game_id=payload.game_id,
                affected_player_ids=affected_ids,
                dedup_key=dedup_key,
                event_payload=payload.model_dump(mode="json"),
                source_hash=source_hash,
                fetched_at=payload.fetched_at,
                feed_age_seconds=age_s,
                is_stale=is_stale,
                decision="DEDUP_SKIPPED",
                reason=reason,
            )
            return {
                "emitted": False,
                "decision": "DEDUP_SKIPPED",
                "dedup_key": dedup_key,
                "source_hash": source_hash,
                "feed_age_seconds": age_s,
                "is_stale": is_stale,
                "reason": reason,
            }

        self._in_memory_dedup.add(dedup_key)
        decision = "HALTED_STALE" if is_stale else "INGESTED"
        event_dict = {
            "event_type": "injury.status_changed",
            "payload": payload.model_dump(mode="json"),
            "affected_player_ids": affected_ids,
            "affected_game_id": payload.game_id,
            "dedup_key": dedup_key,
            "source_hash": source_hash,
            "fetched_at": payload.fetched_at.isoformat(),
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
        }

        stream_id = self.stream_bus.xadd(TOPIC_INJURY, event_dict, source_hash=source_hash)
        self.truth_store.record_agent_event(
            stream_topic=TOPIC_INJURY,
            agent_name=self.AGENT_NAME,
            event_type="injury.status_changed",
            sport=payload.sport,
            affected_game_id=payload.game_id,
            affected_player_ids=affected_ids,
            dedup_key=dedup_key,
            event_payload=payload.model_dump(mode="json"),
            source_hash=source_hash,
            fetched_at=payload.fetched_at,
            feed_age_seconds=age_s,
            is_stale=is_stale,
            decision=decision,
            reason=stale_reason,
        )

        log_msg = StructuredAgentLog(
            agent=self.AGENT_NAME,
            event_type="injury.status_changed",
            prop_id=f"{payload.game_id}::{payload.player_id}",
            latency_ms=latency_ms,
            decision=decision,
            reason=stale_reason,
            source_hash=source_hash,
            feed_age_seconds=age_s,
            is_stale=is_stale,
        )
        logger.info(log_msg.model_dump_json())

        return {
            "emitted": True,
            "stream_id": stream_id,
            "decision": decision,
            "dedup_key": dedup_key,
            "source_hash": source_hash,
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
            "payload": payload,
            "affected_player_ids": affected_ids,
        }
