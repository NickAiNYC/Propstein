"""
Agent 2: LineupAndSubstitutionAgent

Inputs:
  - SportsDataIO confirmed lineups + depth charts + injuries
  - NBA live play-by-play with substitution flags (`is_substitution`, `is_foul`)
    via `nba_api` Live PlayByPlay / Apify NBA Play-by-Play Scraper.

Cadence: 15-30s during live games; subscribes to play-by-play stream.
Output event: `lineup.substitution` or `lineup.foul_trouble` -> Redis Stream (`propwire.events.lineup`).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.agents.persistence import TOPIC_LINEUP, DurableRedisStreamBus, TruthStore
from src.agents.schemas import (
    InjuryBeneficiary,
    LineupEventPayload,
    StructuredAgentLog,
    compute_dedup_hash,
    compute_source_hash,
)
from src.agents.stale_kill_switch import StaleKillSwitch

logger = logging.getLogger("propwire.agent.lineup")


class LineupAndSubstitutionAgent:
    """
    Processes live play-by-play substitution and foul-trouble events plus
    pregame confirmed starter lineups; emits `lineup.substitution` or
    `lineup.foul_trouble` to `propwire.events.lineup`.
    """

    AGENT_NAME = "LineupAndSubstitutionAgent"

    def __init__(
        self,
        stream_bus: DurableRedisStreamBus,
        truth_store: TruthStore,
        kill_switch: StaleKillSwitch | None = None,
    ):
        self.stream_bus = stream_bus
        self.truth_store = truth_store
        self.kill_switch = kill_switch or StaleKillSwitch()

    @staticmethod
    def is_foul_trouble(period: int, personal_fouls: int) -> bool:
        """
        Deterministic NBA foul trouble rule:
        - Q1: >= 2 personal fouls
        - Q2: >= 3 personal fouls
        - Q3: >= 4 personal fouls
        - Q4: >= 5 personal fouls
        """
        if period == 1 and personal_fouls >= 2:
            return True
        if period == 2 and personal_fouls >= 3:
            return True
        if period == 3 and personal_fouls >= 4:
            return True
        if period >= 4 and personal_fouls >= 5:
            return True
        return False

    def ingest_play_by_play(
        self,
        raw_pbp: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        source_hash = raw_pbp.get("source_hash") or compute_source_hash(raw_pbp)
        fetched_at = raw_pbp.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        elif not isinstance(fetched_at, datetime):
            fetched_at = datetime.now(timezone.utc)

        period = int(raw_pbp.get("period", 1))
        personal_fouls = int(raw_pbp.get("personal_fouls", 0))
        is_foul = bool(raw_pbp.get("is_foul", False)) or self.is_foul_trouble(period, personal_fouls)
        is_sub = bool(raw_pbp.get("is_substitution", False))

        if is_foul and self.is_foul_trouble(period, personal_fouls):
            sub_type = "foul_trouble"
            event_type = "lineup.foul_trouble"
            min_delta = float(raw_pbp.get("minutes_projection_delta", -4.5))
        elif raw_pbp.get("sub_type") == "confirmed_starter":
            sub_type = "confirmed_starter"
            event_type = "lineup.substitution"
            min_delta = float(raw_pbp.get("minutes_projection_delta", 6.0))
        else:
            sub_type = "substitution"
            event_type = "lineup.substitution"
            min_delta = float(raw_pbp.get("minutes_projection_delta", 0.0))

        beneficiaries_raw = raw_pbp.get("beneficiaries") or []
        beneficiaries = [
            b if isinstance(b, InjuryBeneficiary) else InjuryBeneficiary(**b)
            for b in beneficiaries_raw
        ]

        payload = LineupEventPayload(
            sport=raw_pbp.get("sport", "nba"),
            game_id=raw_pbp["game_id"],
            player_id=raw_pbp["player_id"],
            player_name=raw_pbp.get("player_name", raw_pbp["player_id"]),
            team=raw_pbp.get("team", "UNK"),
            opponent=raw_pbp.get("opponent", "UNK"),
            sub_type=sub_type,  # type: ignore[arg-type]
            is_substitution=is_sub,
            is_foul=is_foul,
            personal_fouls=personal_fouls,
            period=period,
            clock_remaining_minutes=float(raw_pbp.get("clock_remaining_minutes", max(0.0, (4 - period) * 12.0 + 6.0))),
            minutes_projection_delta=min_delta,
            usage_rate_delta=float(raw_pbp.get("usage_rate_delta", 0.0)),
            remaining_opportunities_delta=float(raw_pbp.get("remaining_opportunities_delta", 0.0)),
            beneficiaries=beneficiaries,
            is_live=bool(raw_pbp.get("is_live", True)),
            source_hash=source_hash,
            fetched_at=fetched_at,
        )

        is_stale, age_s, _, stale_reason = self.kill_switch.evaluate(
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            prop_id=f"{payload.game_id}::{payload.player_id}",
            feed_type="lineup",
            fetched_at=payload.fetched_at,
            source_hash=source_hash,
            is_live=payload.is_live,
            now=now,
        )

        affected_ids = [payload.player_id] + [b.player_id for b in payload.beneficiaries]
        dedup_key = compute_dedup_hash(
            payload.game_id,
            payload.player_id,
            sub_type,
            str(period),
            str(personal_fouls),
            f"{payload.clock_remaining_minutes:.1f}",
        )
        decision = "HALTED_STALE" if is_stale else "INGESTED"
        event_dict = {
            "event_type": event_type,
            "payload": payload.model_dump(mode="json"),
            "affected_player_ids": affected_ids,
            "affected_game_id": payload.game_id,
            "dedup_key": dedup_key,
            "source_hash": source_hash,
            "fetched_at": payload.fetched_at.isoformat(),
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
        }

        stream_id = self.stream_bus.xadd(TOPIC_LINEUP, event_dict, source_hash=source_hash)
        self.truth_store.record_agent_event(
            stream_topic=TOPIC_LINEUP,
            agent_name=self.AGENT_NAME,
            event_type=event_type,
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

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(
            StructuredAgentLog(
                agent=self.AGENT_NAME,
                event_type=event_type,
                prop_id=f"{payload.game_id}::{payload.player_id}",
                latency_ms=latency_ms,
                decision=decision,
                reason=stale_reason,
                source_hash=source_hash,
                feed_age_seconds=age_s,
                is_stale=is_stale,
            ).model_dump_json()
        )

        return {
            "emitted": True,
            "stream_id": stream_id,
            "event_type": event_type,
            "decision": decision,
            "source_hash": source_hash,
            "feed_age_seconds": age_s,
            "is_stale": is_stale,
            "payload": payload,
            "affected_player_ids": affected_ids,
        }

    def ingest_nba_api_live_action(
        self,
        action: dict[str, Any],
        *,
        game_id: str,
        sport: str = "nba",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Adapts `swar/nba_api` Live PlayByPlay action payloads (`PLAYER1_ID`, `PLAYER2_ID`,
        `PLAYER3_ID`, `actionType`, `period`, `clock`, `foulPersonalTotal`) into a canonical
        `lineup.substitution` or `lineup.foul_trouble` Redis Stream event within the 5s budget.
        """
        parsed = parse_nba_api_live_pbp_action(action, game_id=game_id, sport=sport)
        return self.ingest_play_by_play(parsed, now=now)


def parse_nba_api_live_pbp_action(
    action: dict[str, Any],
    *,
    game_id: str,
    sport: str = "nba",
) -> dict[str, Any]:
    """
    Parser for `swar/nba_api` Live PlayByPlay events.
    Extracts `PLAYER1_ID` (subbed out / primary actor), `PLAYER2_ID` (subbed in / secondary),
    `PLAYER3_ID` (official / tertiary context) and maps them into usage-delta triggers.
    """
    action_type = str(action.get("actionType") or action.get("event_msg_type") or "substitution").lower()
    p1_id = str(action.get("PLAYER1_ID") or action.get("player_out_id") or action.get("personId") or "nba_unk_1")
    p2_id = str(action.get("PLAYER2_ID") or action.get("player_in_id") or "")
    p3_id = str(action.get("PLAYER3_ID") or "")

    p1_name = str(action.get("PLAYER1_NAME") or action.get("player_out_name") or action.get("playerName") or p1_id)
    p2_name = str(action.get("PLAYER2_NAME") or action.get("player_in_name") or p2_id or "Rotation Wing")
    team = str(action.get("teamTricode") or action.get("PLAYER1_TEAM_ABBREVIATION") or action.get("team") or "MIL")
    opponent = str(action.get("opponent") or "BOS")
    period = int(action.get("period") or 3)
    clock_min = float(action.get("clock_remaining_minutes") or 16.5)
    fouls = int(action.get("foulPersonalTotal") or action.get("personal_fouls") or 0)

    is_foul = "foul" in action_type or fouls >= 4
    is_sub = "sub" in action_type or bool(p2_id)

    beneficiaries: list[dict[str, Any]] = []
    if p2_id:
        beneficiaries.append(
            {
                "player_id": p2_id,
                "player_name": p2_name,
                "team": team,
                "position": str(action.get("player_in_position") or "SG"),
                "usage_boost_pct": float(action.get("usage_boost_pct") or 0.18),
                "minutes_boost": float(action.get("minutes_boost") or 6.5),
                "target_share_delta": 0.045,
                "rationale": (
                    f"nba_api Live PBP Sub: {p1_name} ({p1_id}) OUT -> {p2_name} ({p2_id}) IN "
                    f"[ref:{p3_id or 'official'}]"
                ),
            }
        )
    for extra_b in action.get("beneficiaries") or []:
        if isinstance(extra_b, dict):
            beneficiaries.append(extra_b)

    return {
        "sport": sport,
        "game_id": game_id,
        "player_id": p1_id,
        "player_name": p1_name,
        "team": team,
        "opponent": opponent,
        "sub_type": "foul_trouble" if is_foul else "substitution",
        "is_substitution": is_sub,
        "is_foul": is_foul,
        "personal_fouls": fouls,
        "period": period,
        "clock_remaining_minutes": clock_min,
        "minutes_projection_delta": float(action.get("minutes_projection_delta", -5.5 if is_sub else -4.5)),
        "usage_rate_delta": float(action.get("usage_rate_delta", -0.04)),
        "remaining_opportunities_delta": float(action.get("remaining_opportunities_delta", -3.0)),
        "beneficiaries": beneficiaries,
        "is_live": True,
        "PLAYER1_ID": p1_id,
        "PLAYER2_ID": p2_id,
        "PLAYER3_ID": p3_id,
        "fetched_at": action.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
    }


class RealtimeStreamReconnector:
    """
    Adapts `ElcoDevRepos/realtime-sports-api-js` production reconnection pattern:
    - Exponential backoff with jitter (`base_delay * 2^attempt`)
    - Honors HTTP 429 `Retry-After` header
    - Automatic degradation from WebSocket to REST polling if max WS retries exceeded
    - Routes NBA live play-by-play to `nba_api` Live (<5s cadence) and NFL to `realtime-sports-api`
    """

    def __init__(self, base_delay_sec: float = 1.0, max_delay_sec: float = 30.0, max_ws_retries: int = 4):
        self.base_delay_sec = base_delay_sec
        self.max_delay_sec = max_delay_sec
        self.max_ws_retries = max_ws_retries
        self.attempt = 0
        self.mode: str = "websocket"

    def next_delay(self, retry_after_header: float | None = None) -> float:
        if retry_after_header is not None and retry_after_header > 0:
            self.attempt += 1
            return min(float(retry_after_header), self.max_delay_sec)
        delay = min(self.max_delay_sec, self.base_delay_sec * (2 ** self.attempt))
        self.attempt += 1
        if self.attempt >= self.max_ws_retries:
            self.mode = "rest_fallback"
        return round(delay, 2)

    def record_success(self) -> None:
        self.attempt = 0
        self.mode = "websocket"


# ---------------------------------------------------------------------------
# Live NBA Tactical Court Lineups State (Powers Visual Court Diagram UI)
# ---------------------------------------------------------------------------
NBA_LIVE_COURT_GAMES: dict[str, dict[str, Any]] = {
    "2026_nba_mil_bos": {
        "game_id": "2026_nba_mil_bos",
        "league": "NBA Live · Play-by-Play Stream",
        "date_label": "29 Oct, 2026",
        "status_pill": "Q3 04:18",
        "quarter_summary": "(Q1: 29-26) (HT: 58-54) (Q3: 86-81)",
        "away_team": "MIL",
        "away_name": "Milwaukee Bucks",
        "away_score": 86,
        "home_team": "BOS",
        "home_name": "Boston Celtics",
        "home_score": 81,
        "pbp_latency_sec": 3.8,
        "odds_cache_age_sec": 6.4,
        "event_ticker": [
            {"player": "Damian Lillard", "detail": "SUB OUT -> A.J. Green SUB IN (Q3 04:18 · PLAYER1_ID:203081 -> PLAYER2_ID:1631260)", "type": "sub"},
            {"player": "Giannis Antetokounmpo", "detail": "+4.8% Usage Vacuum Boost · Fair 34.9 PTS (+6.3% Edge)", "type": "boost"},
            {"player": "Jaylen Brown", "detail": "4th Personal Foul (Q3 06:12 · Foul Trouble Gate Active)", "type": "foul"},
        ],
        "teams": {
            "MIL": {
                "team": "MIL",
                "team_name": "Milwaukee Bucks",
                "usage_share_active": "99.2% (+4.8% Vacuum)",
                "pace": "102.4 Poss/48m",
                "ts_pct": "61.8% TS · 14/31 3PT",
                "on_court": [
                    {
                        "player_id": "nba_aj_green",
                        "nba_id": "1631260",
                        "name": "A.J. Green",
                        "short_name": "A.J. Green",
                        "position": "PG",
                        "formation_row": 1,
                        "sub_status": "SUB_IN",
                        "personal_fouls": 1,
                        "usage_rate": 0.195,
                        "usage_delta_pct": 3.8,
                        "minutes_remaining": 11.5,
                        "market": "threes",
                        "line": 2.5,
                        "fair_line": 3.2,
                        "edge_pct": 5.4,
                    },
                    {
                        "player_id": "nba_gary_trent",
                        "nba_id": "1629018",
                        "name": "Gary Trent Jr.",
                        "short_name": "G. Trent Jr.",
                        "position": "SG",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 2,
                        "usage_rate": 0.210,
                        "usage_delta_pct": 2.4,
                        "minutes_remaining": 14.0,
                        "market": "points",
                        "line": 14.5,
                        "fair_line": 16.4,
                        "edge_pct": 4.2,
                    },
                    {
                        "player_id": "nba_taurean_prince",
                        "nba_id": "1627752",
                        "name": "Taurean Prince",
                        "short_name": "T. Prince",
                        "position": "SF",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 2,
                        "usage_rate": 0.145,
                        "usage_delta_pct": 1.1,
                        "minutes_remaining": 12.5,
                        "market": "rebounds",
                        "line": 4.5,
                        "fair_line": 5.1,
                        "edge_pct": 3.1,
                    },
                    {
                        "player_id": "nba_giannis",
                        "nba_id": "203507",
                        "name": "Giannis Antetokounmpo",
                        "short_name": "G. Antetokounmpo",
                        "position": "PF",
                        "formation_row": 3,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 2,
                        "usage_rate": 0.382,
                        "usage_delta_pct": 4.8,
                        "minutes_remaining": 15.2,
                        "market": "points",
                        "line": 31.5,
                        "fair_line": 34.9,
                        "edge_pct": 6.3,
                    },
                    {
                        "player_id": "nba_brook_lopez",
                        "nba_id": "201572",
                        "name": "Brook Lopez",
                        "short_name": "B. Lopez",
                        "position": "C",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 3,
                        "usage_rate": 0.168,
                        "usage_delta_pct": 1.5,
                        "minutes_remaining": 13.0,
                        "market": "rebounds",
                        "line": 5.5,
                        "fair_line": 6.4,
                        "edge_pct": 3.9,
                    },
                ],
                "bench": [
                    {
                        "player_id": "nba_damian_lillard",
                        "nba_id": "203081",
                        "name": "Damian Lillard",
                        "short_name": "D. Lillard",
                        "position": "PG",
                        "sub_status": "SUB_OUT",
                        "personal_fouls": 2,
                        "usage_rate": 0.305,
                        "minutes_remaining": 12.0,
                        "market": "points",
                        "line": 25.5,
                        "fair_line": 27.1,
                        "edge_pct": 3.5,
                    },
                    {
                        "player_id": "nba_bobby_portis",
                        "nba_id": "1626171",
                        "name": "Bobby Portis",
                        "short_name": "B. Portis",
                        "position": "PF",
                        "sub_status": "BENCH",
                        "personal_fouls": 1,
                        "usage_rate": 0.225,
                        "minutes_remaining": 10.5,
                        "market": "rebounds",
                        "line": 7.5,
                        "fair_line": 8.6,
                        "edge_pct": 4.6,
                    },
                ],
            },
            "BOS": {
                "team": "BOS",
                "team_name": "Boston Celtics",
                "usage_share_active": "98.6% (+3.9% Tatum Boost)",
                "pace": "102.4 Poss/48m",
                "ts_pct": "59.4% TS · 16/38 3PT",
                "on_court": [
                    {
                        "player_id": "nba_jrue_holiday",
                        "nba_id": "201950",
                        "name": "Jrue Holiday",
                        "short_name": "J. Holiday",
                        "position": "PG",
                        "formation_row": 1,
                        "sub_status": "STARTER",
                        "personal_fouls": 1,
                        "usage_rate": 0.172,
                        "usage_delta_pct": 1.4,
                        "minutes_remaining": 14.0,
                        "market": "assists",
                        "line": 4.5,
                        "fair_line": 5.3,
                        "edge_pct": 3.8,
                    },
                    {
                        "player_id": "nba_derrick_white",
                        "nba_id": "1628401",
                        "name": "Derrick White",
                        "short_name": "D. White",
                        "position": "SG",
                        "formation_row": 2,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 2,
                        "usage_rate": 0.224,
                        "usage_delta_pct": 3.1,
                        "minutes_remaining": 14.5,
                        "market": "threes",
                        "line": 3.5,
                        "fair_line": 4.3,
                        "edge_pct": 5.1,
                    },
                    {
                        "player_id": "nba_jaylen_brown",
                        "nba_id": "1627759",
                        "name": "Jaylen Brown",
                        "short_name": "J. Brown",
                        "position": "SF",
                        "formation_row": 2,
                        "sub_status": "FOUL_RISK",
                        "personal_fouls": 4,
                        "usage_rate": 0.275,
                        "usage_delta_pct": -3.2,
                        "minutes_remaining": 10.2,
                        "market": "points",
                        "line": 24.5,
                        "fair_line": 21.8,
                        "edge_pct": 5.7,
                    },
                    {
                        "player_id": "nba_jayson_tatum",
                        "nba_id": "1628369",
                        "name": "Jayson Tatum",
                        "short_name": "J. Tatum",
                        "position": "PF",
                        "formation_row": 3,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 1,
                        "usage_rate": 0.348,
                        "usage_delta_pct": 3.9,
                        "minutes_remaining": 15.5,
                        "market": "points",
                        "line": 28.5,
                        "fair_line": 31.4,
                        "edge_pct": 5.9,
                    },
                    {
                        "player_id": "nba_al_horford",
                        "nba_id": "201143",
                        "name": "Al Horford",
                        "short_name": "A. Horford",
                        "position": "C",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 2,
                        "usage_rate": 0.135,
                        "usage_delta_pct": 0.5,
                        "minutes_remaining": 11.5,
                        "market": "rebounds",
                        "line": 6.5,
                        "fair_line": 7.2,
                        "edge_pct": 3.4,
                    },
                ],
                "bench": [
                    {
                        "player_id": "nba_payton_pritchard",
                        "nba_id": "1630202",
                        "name": "Payton Pritchard",
                        "short_name": "P. Pritchard",
                        "position": "PG",
                        "sub_status": "BENCH",
                        "personal_fouls": 1,
                        "usage_rate": 0.205,
                        "minutes_remaining": 11.0,
                        "market": "threes",
                        "line": 2.5,
                        "fair_line": 3.1,
                        "edge_pct": 4.4,
                    },
                    {
                        "player_id": "nba_sam_hauser",
                        "nba_id": "1630573",
                        "name": "Sam Hauser",
                        "short_name": "S. Hauser",
                        "position": "SF",
                        "sub_status": "BENCH",
                        "personal_fouls": 0,
                        "usage_rate": 0.160,
                        "minutes_remaining": 9.5,
                        "market": "threes",
                        "line": 1.5,
                        "fair_line": 2.1,
                        "edge_pct": 3.9,
                    },
                ],
            },
        },
    },
    "2026_nba_gsw_sac": {
        "game_id": "2026_nba_gsw_sac",
        "league": "NBA Live · Play-by-Play Stream",
        "date_label": "29 Oct, 2026",
        "status_pill": "Q4 07:12",
        "quarter_summary": "(Q1: 31-28) (HT: 62-60) (Q3: 94-91)",
        "away_team": "GSW",
        "away_name": "Golden State Warriors",
        "away_score": 104,
        "home_team": "SAC",
        "home_name": "Sacramento Kings",
        "home_score": 101,
        "pbp_latency_sec": 3.2,
        "odds_cache_age_sec": 5.1,
        "event_ticker": [
            {"player": "Stephen Curry", "detail": "SUB IN for B. Podziemski (Q4 07:12 · Closing Rotation)", "type": "sub"},
            {"player": "Domantas Sabonis", "detail": "5th Personal Foul (Q4 07:45 · Severe Foul Trouble)", "type": "foul"},
            {"player": "De'Aaron Fox", "detail": "+5.2% Usage Surge with Sabonis Restricted", "type": "boost"},
        ],
        "teams": {
            "GSW": {
                "team": "GSW",
                "team_name": "Golden State Warriors",
                "usage_share_active": "99.5% (+5.1% Curry Closing)",
                "pace": "104.8 Poss/48m",
                "ts_pct": "63.1% TS · 17/39 3PT",
                "on_court": [
                    {
                        "player_id": "nba_stephen_curry",
                        "nba_id": "201939",
                        "name": "Stephen Curry",
                        "short_name": "S. Curry",
                        "position": "PG",
                        "formation_row": 1,
                        "sub_status": "SUB_IN",
                        "personal_fouls": 2,
                        "usage_rate": 0.355,
                        "usage_delta_pct": 5.1,
                        "minutes_remaining": 7.2,
                        "market": "points",
                        "line": 28.5,
                        "fair_line": 31.8,
                        "edge_pct": 6.8,
                    },
                    {
                        "player_id": "nba_buddy_hield",
                        "nba_id": "1627741",
                        "name": "Buddy Hield",
                        "short_name": "B. Hield",
                        "position": "SG",
                        "formation_row": 2,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 1,
                        "usage_rate": 0.235,
                        "usage_delta_pct": 2.9,
                        "minutes_remaining": 7.2,
                        "market": "threes",
                        "line": 3.5,
                        "fair_line": 4.4,
                        "edge_pct": 5.5,
                    },
                    {
                        "player_id": "nba_andrew_wiggins",
                        "nba_id": "203952",
                        "name": "Andrew Wiggins",
                        "short_name": "A. Wiggins",
                        "position": "SF",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 3,
                        "usage_rate": 0.195,
                        "usage_delta_pct": 0.8,
                        "minutes_remaining": 7.2,
                        "market": "points",
                        "line": 16.5,
                        "fair_line": 17.9,
                        "edge_pct": 3.7,
                    },
                    {
                        "player_id": "nba_jonathan_kuminga",
                        "nba_id": "1630228",
                        "name": "Jonathan Kuminga",
                        "short_name": "J. Kuminga",
                        "position": "PF",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 2,
                        "usage_rate": 0.220,
                        "usage_delta_pct": 1.6,
                        "minutes_remaining": 6.8,
                        "market": "points",
                        "line": 15.5,
                        "fair_line": 17.1,
                        "edge_pct": 4.1,
                    },
                    {
                        "player_id": "nba_draymond_green",
                        "nba_id": "203110",
                        "name": "Draymond Green",
                        "short_name": "D. Green",
                        "position": "C",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 4,
                        "usage_rate": 0.140,
                        "usage_delta_pct": 0.4,
                        "minutes_remaining": 7.2,
                        "market": "assists",
                        "line": 6.5,
                        "fair_line": 7.4,
                        "edge_pct": 4.3,
                    },
                ],
                "bench": [
                    {
                        "player_id": "nba_brandin_podziemski",
                        "nba_id": "1641764",
                        "name": "Brandin Podziemski",
                        "short_name": "B. Podziemski",
                        "position": "PG",
                        "sub_status": "SUB_OUT",
                        "personal_fouls": 2,
                        "usage_rate": 0.180,
                        "minutes_remaining": 3.5,
                        "market": "assists",
                        "line": 4.5,
                        "fair_line": 4.9,
                        "edge_pct": 2.8,
                    },
                ],
            },
            "SAC": {
                "team": "SAC",
                "team_name": "Sacramento Kings",
                "usage_share_active": "99.1% (+5.2% Fox Surge)",
                "pace": "104.8 Poss/48m",
                "ts_pct": "60.2% TS · 13/34 3PT",
                "on_court": [
                    {
                        "player_id": "nba_deaaron_fox",
                        "nba_id": "1628368",
                        "name": "De'Aaron Fox",
                        "short_name": "D. Fox",
                        "position": "PG",
                        "formation_row": 1,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 2,
                        "usage_rate": 0.362,
                        "usage_delta_pct": 5.2,
                        "minutes_remaining": 7.2,
                        "market": "points",
                        "line": 27.5,
                        "fair_line": 30.8,
                        "edge_pct": 6.5,
                    },
                    {
                        "player_id": "nba_malik_monk",
                        "nba_id": "1628370",
                        "name": "Malik Monk",
                        "short_name": "M. Monk",
                        "position": "SG",
                        "formation_row": 2,
                        "sub_status": "SUB_IN",
                        "personal_fouls": 1,
                        "usage_rate": 0.248,
                        "usage_delta_pct": 3.4,
                        "minutes_remaining": 7.0,
                        "market": "points",
                        "line": 16.5,
                        "fair_line": 18.7,
                        "edge_pct": 5.1,
                    },
                    {
                        "player_id": "nba_demar_derozan",
                        "nba_id": "201942",
                        "name": "DeMar DeRozan",
                        "short_name": "D. DeRozan",
                        "position": "SF",
                        "formation_row": 2,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 2,
                        "usage_rate": 0.285,
                        "usage_delta_pct": 2.8,
                        "minutes_remaining": 7.2,
                        "market": "points",
                        "line": 22.5,
                        "fair_line": 24.9,
                        "edge_pct": 5.3,
                    },
                    {
                        "player_id": "nba_keegan_murray",
                        "nba_id": "1631099",
                        "name": "Keegan Murray",
                        "short_name": "K. Murray",
                        "position": "PF",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 3,
                        "usage_rate": 0.175,
                        "usage_delta_pct": 1.1,
                        "minutes_remaining": 7.2,
                        "market": "rebounds",
                        "line": 6.5,
                        "fair_line": 7.4,
                        "edge_pct": 4.0,
                    },
                    {
                        "player_id": "nba_domantas_sabonis",
                        "nba_id": "1627734",
                        "name": "Domantas Sabonis",
                        "short_name": "D. Sabonis",
                        "position": "C",
                        "formation_row": 3,
                        "sub_status": "FOUL_RISK",
                        "personal_fouls": 5,
                        "usage_rate": 0.215,
                        "usage_delta_pct": -4.1,
                        "minutes_remaining": 4.8,
                        "market": "rebounds",
                        "line": 12.5,
                        "fair_line": 10.8,
                        "edge_pct": 5.8,
                    },
                ],
                "bench": [
                    {
                        "player_id": "nba_kevin_huerter",
                        "nba_id": "1628989",
                        "name": "Kevin Huerter",
                        "short_name": "K. Huerter",
                        "position": "SG",
                        "sub_status": "SUB_OUT",
                        "personal_fouls": 2,
                        "usage_rate": 0.165,
                        "minutes_remaining": 3.0,
                        "market": "threes",
                        "line": 2.5,
                        "fair_line": 2.8,
                        "edge_pct": 3.1,
                    },
                ],
            },
        },
    },
    "2025_ucl_ars_atm": {
        "game_id": "2025_ucl_ars_atm",
        "sport": "soccer",
        "league": "Champion League",
        "date_label": "21 Oct, 2025",
        "status_pill": "Full Time",
        "quarter_summary": "(HT: 0-0) (FT: 4-0)",
        "away_team": "ARS",
        "away_name": "Arsenal",
        "away_score": 4,
        "home_team": "ATM",
        "home_name": "Atlético de Madrid",
        "home_score": 0,
        "pbp_latency_sec": 1.2,
        "odds_cache_age_sec": 3.4,
        "event_ticker": [
            {"player": "Gabriel Magalhães", "detail": "Goal 57' · Header from corner assist Saka", "type": "goal"},
            {"player": "Gabriel Martinelli", "detail": "Goal 64' · Right-footed strike bottom right", "type": "goal"},
            {"player": "Viktor Gyökeres", "detail": "Goal 67' & 70' · Brace (Open play + Penalty)", "type": "goal"},
        ],
        "teams": {
            "ARS": {
                "team": "ARS",
                "team_name": "Arsenal",
                "usage_share_active": "~51.5%",
                "pace": "19",
                "ts_pct": "8",
                "stats": {
                    "possession": "~51.5%",
                    "shots": "19",
                    "shots_on_target": "8",
                    "passes": "542 (89% Acc)",
                    "tackles": "14",
                    "fouls": "9",
                    "corners": "7",
                    "xg": "3.18 vs 0.44",
                },
                "on_court": [
                    {
                        "player_id": "soc_david_raya",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p215359.png",
                        "name": "David Raya",
                        "short_name": "D. Raya",
                        "position": "GK",
                        "formation_row": 1,
                        "sub_status": "STARTER",
                        "personal_fouls": 0,
                        "usage_rate": 0.08,
                        "usage_delta_pct": 0.0,
                        "minutes_remaining": 0.0,
                        "market": "clean_sheet",
                        "line": 0.5,
                        "fair_line": 0.95,
                        "edge_pct": 8.5,
                    },
                    {
                        "player_id": "soc_myles_lewis_skelly",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p547477.png",
                        "name": "Myles Lewis-Skelly",
                        "short_name": "M. Lewis-Skelly",
                        "position": "LB",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 1,
                        "usage_rate": 0.12,
                        "usage_delta_pct": 1.2,
                        "minutes_remaining": 0.0,
                        "market": "tackles",
                        "line": 1.5,
                        "fair_line": 2.2,
                        "edge_pct": 4.8,
                    },
                    {
                        "player_id": "soc_gabriel_magalhaes",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p244855.png",
                        "name": "Gabriel Magalhães",
                        "short_name": "G. Magalhães",
                        "position": "CB",
                        "formation_row": 2,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 0,
                        "usage_rate": 0.15,
                        "usage_delta_pct": 3.4,
                        "minutes_remaining": 0.0,
                        "market": "goals",
                        "line": 0.5,
                        "fair_line": 1.0,
                        "edge_pct": 9.2,
                    },
                    {
                        "player_id": "soc_william_saliba",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p462424.png",
                        "name": "William Saliba",
                        "short_name": "W. Saliba",
                        "position": "CB",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 0,
                        "usage_rate": 0.11,
                        "usage_delta_pct": 0.8,
                        "minutes_remaining": 0.0,
                        "market": "passes",
                        "line": 64.5,
                        "fair_line": 71.0,
                        "edge_pct": 5.1,
                    },
                    {
                        "player_id": "soc_jurrien_timber",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p464947.png",
                        "name": "Jurriën Timber",
                        "short_name": "J. Timber",
                        "position": "RB",
                        "formation_row": 2,
                        "sub_status": "STARTER",
                        "personal_fouls": 1,
                        "usage_rate": 0.13,
                        "usage_delta_pct": 1.1,
                        "minutes_remaining": 0.0,
                        "market": "tackles",
                        "line": 2.5,
                        "fair_line": 3.1,
                        "edge_pct": 4.2,
                    },
                    {
                        "player_id": "soc_eberechi_eze",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p232413.png",
                        "name": "Eberechi Eze",
                        "short_name": "E. Eze",
                        "position": "LM",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 0,
                        "usage_rate": 0.18,
                        "usage_delta_pct": 2.1,
                        "minutes_remaining": 0.0,
                        "market": "shots",
                        "line": 2.5,
                        "fair_line": 3.2,
                        "edge_pct": 6.1,
                    },
                    {
                        "player_id": "soc_martin_zubimendi",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p243571.png",
                        "name": "Martín Zubimendi",
                        "short_name": "M. Zubimendi",
                        "position": "CM",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 1,
                        "usage_rate": 0.16,
                        "usage_delta_pct": 1.5,
                        "minutes_remaining": 0.0,
                        "market": "passes",
                        "line": 58.5,
                        "fair_line": 64.2,
                        "edge_pct": 4.7,
                    },
                    {
                        "player_id": "soc_declan_rice",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p204480.png",
                        "name": "Declan Rice",
                        "short_name": "D. Rice",
                        "position": "CM",
                        "formation_row": 3,
                        "sub_status": "STARTER",
                        "personal_fouls": 2,
                        "usage_rate": 0.17,
                        "usage_delta_pct": 1.8,
                        "minutes_remaining": 0.0,
                        "market": "tackles",
                        "line": 2.5,
                        "fair_line": 3.4,
                        "edge_pct": 5.9,
                    },
                    {
                        "player_id": "soc_bukayo_saka",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p246669.png",
                        "name": "Bukayo Saka",
                        "short_name": "B. Saka",
                        "position": "RM",
                        "formation_row": 3,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 1,
                        "usage_rate": 0.24,
                        "usage_delta_pct": 4.2,
                        "minutes_remaining": 0.0,
                        "market": "assists",
                        "line": 0.5,
                        "fair_line": 1.1,
                        "edge_pct": 8.3,
                    },
                    {
                        "player_id": "soc_viktor_gyokeres",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p235552.png",
                        "name": "Viktor Gyökeres",
                        "short_name": "V. Gyökeres",
                        "position": "ST",
                        "formation_row": 4,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 0,
                        "usage_rate": 0.31,
                        "usage_delta_pct": 6.8,
                        "minutes_remaining": 0.0,
                        "market": "goals",
                        "line": 1.5,
                        "fair_line": 2.1,
                        "edge_pct": 11.4,
                    },
                    {
                        "player_id": "soc_gabriel_martinelli",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p444145.png",
                        "name": "Gabriel Martinelli",
                        "short_name": "G. Martinelli",
                        "position": "ST",
                        "formation_row": 4,
                        "sub_status": "BOOSTED",
                        "personal_fouls": 1,
                        "usage_rate": 0.26,
                        "usage_delta_pct": 5.1,
                        "minutes_remaining": 0.0,
                        "market": "goals",
                        "line": 0.5,
                        "fair_line": 1.2,
                        "edge_pct": 9.8,
                    },
                ],
                "bench": [
                    {
                        "player_id": "soc_leandro_trossard",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p116151.png",
                        "name": "Leandro Trossard",
                        "short_name": "L. Trossard",
                        "position": "LW",
                        "sub_status": "SUB_OUT",
                        "personal_fouls": 0,
                        "usage_rate": 0.18,
                        "minutes_remaining": 15.0,
                        "market": "shots",
                        "line": 1.5,
                        "fair_line": 1.8,
                        "edge_pct": 3.4,
                    },
                ],
            },
            "ATM": {
                "team": "ATM",
                "team_name": "Atlético de Madrid",
                "usage_share_active": "~48.5%",
                "pace": "8",
                "ts_pct": "2",
                "stats": {
                    "possession": "~48.5%",
                    "shots": "8",
                    "shots_on_target": "2",
                    "passes": "418 (82% Acc)",
                    "tackles": "18",
                    "fouls": "14",
                    "corners": "3",
                    "xg": "0.44 vs 3.18",
                },
                "on_court": [
                    {
                        "player_id": "soc_jan_oblak",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p12086.png",
                        "name": "Jan Oblak",
                        "short_name": "J. Oblak",
                        "position": "GK",
                        "formation_row": 1,
                        "sub_status": "STARTER",
                        "personal_fouls": 0,
                        "usage_rate": 0.08,
                        "usage_delta_pct": 0.0,
                        "minutes_remaining": 0.0,
                        "market": "saves",
                        "line": 4.5,
                        "fair_line": 5.2,
                        "edge_pct": 4.1,
                    },
                    {
                        "player_id": "soc_antoine_griezmann",
                        "headshot_url": "https://resources.premierleague.com/premierleague/photos/players/250x250/p80254.png",
                        "name": "Antoine Griezmann",
                        "short_name": "A. Griezmann",
                        "position": "ST",
                        "formation_row": 4,
                        "sub_status": "STARTER",
                        "personal_fouls": 1,
                        "usage_rate": 0.28,
                        "usage_delta_pct": 0.5,
                        "minutes_remaining": 0.0,
                        "market": "shots",
                        "line": 2.5,
                        "fair_line": 2.7,
                        "edge_pct": 2.9,
                    },
                ],
                "bench": [],
            },
        },
    },
}


def get_active_court_lineups() -> dict[str, dict[str, Any]]:
    import copy
    return copy.deepcopy(NBA_LIVE_COURT_GAMES)

