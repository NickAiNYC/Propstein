"""
Production process-lifecycle tests for `scripts/live_nba_sniper_worker.py`:
1. `SIGTERM` / `SIGINT` graceful shutdown handler (completes current poll, closes resources, exits 0).
2. Boot race condition retry logic (`wait_for_web_service` exponential backoff + CRITICAL log after 5 retries).
3. Lightweight `/health` HTTP server and 60s heartbeat emission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import urllib.request
from typing import Any, Optional

import pytest

from scripts.live_nba_sniper_worker import LiveNbaSniperWorker


def test_sigterm_and_sigint_graceful_shutdown_finishes_current_poll():
    """
    Requirement 3 & 6:
    When `SIGTERM` is received during a poll cycle, the worker finishes the current
    poll, closes resources (`resources_closed is True`), and returns exit code 0.
    """
    polls_completed = 0
    worker_holder: dict[str, LiveNbaSniperWorker] = {}

    def mock_pbp_fetcher(game_id: str, proxy_url: Optional[str]) -> dict[str, Any]:
        nonlocal polls_completed
        polls_completed += 1
        # Simulate SIGTERM arriving right while the first poll is in-flight
        worker_holder["worker"].handle_shutdown_signal(signal.SIGTERM)
        return {"game": {"gameId": game_id, "actions": []}}

    worker = LiveNbaSniperWorker(
        pbp_fetcher=mock_pbp_fetcher,
        http_poster=lambda ep, pl: {"status": "ok"},
        poll_interval_sec=0.01,
    )
    worker_holder["worker"] = worker

    exit_code = asyncio.run(
        worker.run_daemon(
            ["2026_nba_mil_bos"],
            max_cycles=10,
            check_web_on_boot=False,
        )
    )

    assert exit_code == 0
    assert polls_completed == 1
    assert worker.shutdown_requested is True
    assert worker.resources_closed is True


def test_boot_race_retry_succeeds_when_web_comes_up_on_third_attempt():
    """
    Requirement 4 & 6:
    Simulates simultaneous Railway deploy where `propwire-web` fails the first
    2 health checks and becomes ready on attempt 3.
    """
    attempts = 0

    def flaky_health_checker(base_url: str) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts >= 3

    worker = LiveNbaSniperWorker(
        internal_api_base="http://propwire-web.railway.internal:8000",
        health_checker=flaky_health_checker,
    )

    ready = asyncio.run(
        worker.wait_for_web_service(
            max_retries=5,
            base_delay_sec=0.005,
        )
    )

    assert ready is True
    assert attempts == 3


def test_boot_race_logs_critical_after_max_5_retries(caplog: pytest.LogCaptureFixture):
    """
    Requirement 4 & 6:
    If the web service is still unreachable after 5 exponential backoff retries,
    `wait_for_web_service` logs a CRITICAL structured event and returns False.
    """
    attempts = 0

    def dead_health_checker(base_url: str) -> bool:
        nonlocal attempts
        attempts += 1
        return False

    worker = LiveNbaSniperWorker(
        internal_api_base="http://propwire-web.railway.internal:8000",
        health_checker=dead_health_checker,
    )

    with caplog.at_level(logging.CRITICAL, logger="propwire.worker.nba_live_pbp"):
        ready = asyncio.run(
            worker.wait_for_web_service(
                max_retries=5,
                base_delay_sec=0.002,
            )
        )

    assert ready is False
    assert attempts == 5
    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical_records) >= 1
    payload = json.loads(critical_records[-1].message)
    assert payload["event"] == "boot_race_web_service_unreachable"
    assert payload["max_retries"] == 5


def test_worker_health_endpoint_and_heartbeat():
    """
    Requirement 3:
    Verifies the worker's `/health` endpoint responds with 200 OK JSON and shuts down
    cleanly when `close_resources()` is called.
    """
    worker = LiveNbaSniperWorker(heartbeat_interval_sec=0.0)
    bound_port = worker.start_health_server(port=0)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{bound_port}/health", timeout=2.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["service"] == "live_nba_sniper_worker"
        assert worker.maybe_emit_heartbeat(1, ["2026_nba_mil_bos"]) is True
    finally:
        worker.close_resources()
        assert worker.resources_closed is True
