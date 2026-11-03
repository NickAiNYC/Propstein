"""
Money-path tests for `scripts/live_nba_sniper_worker.py` and the 3 NBA Live
Sniper "Gotchas" (Proxy Rotation + 429 Backoff, Twin Problem Fail-Closed Guard,
and Play-by-Play Desync / Duplicate Suppression + 3-Strike Stale Kill Switch).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from scripts.live_nba_sniper_worker import (
    ExponentialBackoff,
    LiveNbaSniperWorker,
    PollHttpError,
    ProxyRotator,
)
from src.agents.persistence import TruthStore


def test_player1_to_player2_substitution_triggers_single_post_and_logs_latency():
    """
    Requirement 3.1:
    Mock `nba_api` response and verify that a `PLAYER1_ID -> PLAYER2_ID`
    substitution triggers exactly one POST request to `/api/sniper/simulate-substitution`
    with `PLAYER1_ID`, `PLAYER2_ID`, `PLAYER3_ID`, `foulPersonalTotal`, and latency.
    """
    posted_calls: list[tuple[str, dict[str, Any]]] = []

    def mock_pbp_fetcher(game_id: str, proxy_url: Optional[str]) -> dict[str, Any]:
        return {
            "game": {
                "gameId": game_id,
                "actions": [
                    {
                        "actionNumber": 214,
                        "actionType": "substitution",
                        "timeActual": "2026-10-29T03:50:00.000Z",
                        "teamTricode": "MIL",
                        "PLAYER1_ID": "203081",  # Damian Lillard (OUT)
                        "PLAYER2_ID": "1631260",  # A.J. Green (IN)
                        "PLAYER3_ID": "nba_official_1",
                        "foulPersonalTotal": 2,
                    }
                ],
            }
        }

    def mock_http_poster(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted_calls.append((endpoint, payload))
        return {"status": "ok", "dispatched": True}

    worker = LiveNbaSniperWorker(
        pbp_fetcher=mock_pbp_fetcher,
        http_poster=mock_http_poster,
        proxy_rotator=ProxyRotator(proxy_urls=["http://proxy-1.internal:8080"]),
    )
    worker.seed_roster(
        game_id="2026_nba_mil_bos",
        team="MIL",
        on_court_ids=["203081", "1629018", "1627752", "203507", "201572"],
        bench_ids=["1631260", "1626171"],
    )

    now = datetime(2026, 10, 29, 3, 50, 1, 250000, tzinfo=timezone.utc)
    result = worker.poll_game_once("2026_nba_mil_bos", now=now)

    assert result["status"] == "ok"
    assert result["dispatched_count"] == 1
    assert len(posted_calls) == 1

    endpoint, payload = posted_calls[0]
    assert endpoint == "/api/sniper/simulate-substitution"
    assert payload["PLAYER1_ID"] == "203081"
    assert payload["PLAYER2_ID"] == "1631260"
    assert payload["PLAYER3_ID"] == "nba_official_1"
    assert payload["foulPersonalTotal"] == 2
    assert payload["action_to_dispatch_latency_ms"] == pytest.approx(1250.0, abs=10.0)


def test_http_429_triggers_exponential_backoff_and_proxy_rotation():
    """
    Requirement 2 & 3.2:
    Verify that HTTP 429 / 403 responses trigger exponential backoff (`5s, 10s, 20s, 40s`)
    and rotate across configured proxy URLs to prevent Akamai WAF IP bans.
    """
    seen_proxies: list[Optional[str]] = []

    def failing_429_fetcher(game_id: str, proxy_url: Optional[str]) -> dict[str, Any]:
        seen_proxies.append(proxy_url)
        raise PollHttpError(429, "Too Many Requests (Akamai WAF)")

    rotator = ProxyRotator(
        proxy_urls=[
            "http://proxy-a.propwire.internal:8000",
            "http://proxy-b.propwire.internal:8000",
            "http://proxy-c.propwire.internal:8000",
        ]
    )
    backoff = ExponentialBackoff(base_delay_sec=5.0, max_delay_sec=40.0, jitter_max_sec=0.0)
    stale_posts: list[tuple[str, dict[str, Any]]] = []

    worker = LiveNbaSniperWorker(
        pbp_fetcher=failing_429_fetcher,
        http_poster=lambda ep, pl: (stale_posts.append((ep, pl)) or {"status": "feed_stale"}),
        proxy_rotator=rotator,
        backoff=backoff,
    )

    r1 = worker.poll_game_once("2026_nba_mil_bos")
    r2 = worker.poll_game_once("2026_nba_mil_bos")
    r3 = worker.poll_game_once("2026_nba_mil_bos")

    assert r1["status_code"] == 429
    assert r1["backoff_delay_sec"] == 5.0
    assert r1["feed_stale_emitted"] is False

    assert r2["backoff_delay_sec"] == 10.0
    assert r2["feed_stale_emitted"] is False

    # 3rd consecutive failure trips the Stale Kill Switch and emits `feed_stale`
    assert r3["backoff_delay_sec"] == 20.0
    assert r3["consecutive_failures"] == 3
    assert r3["feed_stale_emitted"] is True
    assert worker.is_feed_stale["2026_nba_mil_bos"] is True
    assert len(stale_posts) == 1
    assert stale_posts[0][0] == "/api/sniper/feed-stale"
    assert stale_posts[0][1]["event_type"] == "feed_stale"

    # Proxies rotated across all 3 attempts
    assert seen_proxies == [
        "http://proxy-a.propwire.internal:8000",
        "http://proxy-b.propwire.internal:8000",
        "http://proxy-c.propwire.internal:8000",
    ]


def test_duplicate_pbp_action_and_desync_do_not_trigger_multiple_recalculations():
    """
    Requirement 2 & 3.3:
    1. Re-polling the identical PBP action (same timestamp / actionNumber) does NOT
       trigger a second POST request.
    2. Even if `actionNumber` changes on a desynced feed, if `PLAYER2_ID` is already
       on the court and `PLAYER1_ID` is already on the bench, the worker ignores it
       unless `is_correction=True` (official scorer reversal).
    """
    posted_calls: list[dict[str, Any]] = []
    actions_batch: list[dict[str, Any]] = [
        {
            "actionNumber": 301,
            "actionType": "substitution",
            "timeActual": "2026-10-29T03:52:00Z",
            "teamTricode": "MIL",
            "PLAYER1_ID": "203081",
            "PLAYER2_ID": "1631260",
            "PLAYER3_ID": "nba_official_1",
        }
    ]

    worker = LiveNbaSniperWorker(
        pbp_fetcher=lambda gid, prx: {"game": {"actions": actions_batch}},
        http_poster=lambda ep, pl: (posted_calls.append(pl) or {"status": "ok"}),
    )
    worker.seed_roster(
        game_id="2026_nba_mil_bos",
        team="MIL",
        on_court_ids=["203081", "1629018", "1627752", "203507", "201572"],
        bench_ids=["1631260", "1626171"],
    )

    # First poll: dispatches once
    first = worker.poll_game_once("2026_nba_mil_bos")
    assert first["dispatched_count"] == 1
    assert len(posted_calls) == 1

    # Second poll with identical action: skipped
    second = worker.poll_game_once("2026_nba_mil_bos")
    assert second["dispatched_count"] == 0
    assert second["skipped_duplicates"] == 1
    assert len(posted_calls) == 1

    # Desynced action with new actionNumber but same players already swapped: skipped by roster guard
    actions_batch.append(
        {
            "actionNumber": 302,
            "actionType": "substitution",
            "timeActual": "2026-10-29T03:52:05Z",
            "teamTricode": "MIL",
            "PLAYER1_ID": "203081",
            "PLAYER2_ID": "1631260",
            "PLAYER3_ID": "nba_official_1",
        }
    )
    third = worker.poll_game_once("2026_nba_mil_bos")
    assert third["dispatched_count"] == 0
    assert len(posted_calls) == 1

    # Official scorer reversal (`is_correction=True` swapping 1631260 back out for 203081): allowed
    actions_batch.append(
        {
            "actionNumber": 303,
            "actionType": "substitution",
            "timeActual": "2026-10-29T03:52:10Z",
            "edited": "2026-10-29T03:52:12Z",
            "is_correction": True,
            "teamTricode": "MIL",
            "PLAYER1_ID": "1631260",
            "PLAYER2_ID": "203081",
            "PLAYER3_ID": "nba_official_scorer",
        }
    )
    fourth = worker.poll_game_once("2026_nba_mil_bos")
    assert fourth["dispatched_count"] == 1
    assert len(posted_calls) == 2


def test_twin_problem_fail_closed_guard(tmp_path: Path):
    """
    Gotcha 2 Verification (The Twin Problem):
    1. `Jalen Williams` (OKC, SF) vs `Jaylin Williams` (OKC, C): distinguished strictly
       by `(team, position)`.
    2. `Marcus Morris` vs `Markieff Morris` on same `(team, position)` or ambiguous
       `J. Morris`: fails closed (`None`) rather than guessing.
    """
    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    truth.upsert_player_mapping(
        canonical_player_id="nba_jalen_williams_jdub",
        sport="nba",
        player_name="Jalen Williams",
        team="OKC",
        position="SF",
        nba_api_person_id="1631114",
    )
    truth.upsert_player_mapping(
        canonical_player_id="nba_jaylin_williams_jwill",
        sport="nba",
        player_name="Jaylin Williams",
        team="OKC",
        position="C",
        nba_api_person_id="1631119",
    )

    # Strict (Team, Position) resolves each OKC Williams unambiguously
    assert (
        truth.resolve_canonical_player_id(player_name="Jalen Williams", team="OKC", position="SF")
        == "nba_jalen_williams_jdub"
    )
    assert (
        truth.resolve_canonical_player_id(player_name="Jaylin Williams", team="OKC", position="C")
        == "nba_jaylin_williams_jwill"
    )

    # Missing position or team MUST fail closed (`None`)
    assert truth.resolve_canonical_player_id(player_name="Jalen Williams", team="OKC", position=None) is None

    # Twins on same (team, position) queried with ambiguous "M. Morris" -> tie fails closed (`None`)
    truth.upsert_player_mapping(
        canonical_player_id="nba_marcus_morris",
        sport="nba",
        player_name="Marcus Morris",
        team="NYK",
        position="PF",
    )
    truth.upsert_player_mapping(
        canonical_player_id="nba_markieff_morris",
        sport="nba",
        player_name="Markieff Morris",
        team="NYK",
        position="PF",
    )
    assert truth.resolve_canonical_player_id(player_name="M. Morris", team="NYK", position="PF") is None
