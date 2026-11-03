"""
Verification Tests for the Rate-Limited Discord/Telegram Webhook Dispatch System
(`src/services/webhook_dispatcher.py`).

Tests:
1. Webhook IS dispatched for an edge of 5% when `min_edge_gate` is 4%, and formatted
   Discord embed / Telegram Markdown include player, prop, Fair Prob, Polymarket price,
   Top-3 Depth, and `[🔗 BUY YES ON POLYMARKET]` deep-link.
2. Webhook is NOT dispatched for an edge of 3% when `min_edge_gate` is 4%.
3. 5-minute deduplication lock (`webhook_lock:{user_id}:{player_id}:{prop_type}`, TTL=300s):
   firing the same alert twice within 5 minutes sends only one message.
4. SSRF protection blocks internal/arbitrary webhook URLs, and an HTTP 404 response
   automatically marks the subscription `inactive` (`active_status=False`) in the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.services.webhook_dispatcher import (
    WebhookDispatcher,
    build_webhook_lock_key,
    format_discord_embed,
    format_telegram_markdown,
    validate_webhook_target,
)


class _DummyResponse:
    def __init__(self, status_code: int = 204):
        self.status_code = status_code


def test_webhook_dispatched_for_5pct_edge_when_gate_is_4pct(tmp_path: Path):
    """
    Verify that a 5.0% edge alert IS dispatched when the subscription's
    `min_edge_gate` is 4.0%, and that the Discord/Telegram formatters include
    the required arbitrage fields.
    """
    sent_calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: float = 5.0):
        sent_calls.append({"url": url, "json": json, "timeout": timeout})
        return _DummyResponse(204)

    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    dispatcher = WebhookDispatcher(truth_store=truth, bus=bus, http_post=fake_post)

    dispatcher.register_subscription(
        user_id="user_alpha",
        platform="discord",
        webhook_url="https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz_123456",
        min_edge_gate=4.0,
        polymarket_only=True,
    )

    alert_5pct = {
        "player_id": "nba_jalen_brunson",
        "player_name": "Jalen Brunson",
        "team": "NYK",
        "market": "points",
        "market_label": "PTS Over 24.5",
        "line": 24.5,
        "fair_prob": 0.64,
        "implied_prob": 0.58,
        "poly_ask_price": 0.58,
        "edge_pct": 5.0,
        "depth_tooltip": "$500 available at $0.58, $1,200 at $0.59",
        "deep_link": "https://polymarket.com/event/nba-jalen-brunson-points-over-24-5",
        "venue_type": "polymarket",
        "book": "Polymarket",
    }

    outcomes = dispatcher.dispatch_alert(alert_5pct, async_dispatch=False, now_epoch=1700000000.0)
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "sent"
    assert len(sent_calls) == 1

    # Verify Discord embed and Telegram Markdown formatting (mission W4 format)
    discord_payload = format_discord_embed(alert_5pct)
    embed = discord_payload["embeds"][0]
    assert embed["title"] == "🚨 LIVE SNIPER ALERT: Jalen Brunson"
    assert "PTS Over 24.5" in embed["description"]
    assert "Fair **64%** vs Market **58%** ($0.58)" in embed["description"]
    assert "$500 @ $0.58, $1,200 @ $0.59" in embed["description"]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Edge"] == "+5.0%"
    assert fields["Proj Line"] == "25.7"
    assert fields["Market Line"] == "24.5"
    assert fields["Book"] == "Polymarket"
    assert embed["color"] == 0xA3E635
    button = discord_payload["components"][0]["components"][0]
    assert button["label"] == "🔗 Execute on Polymarket"
    assert button["style"] == 5
    assert button["url"] == "https://polymarket.com/event/nba-jalen-brunson-points-over-24-5"

    tg_md = format_telegram_markdown(alert_5pct)
    assert "Jalen Brunson | PTS Over 24.5" in tg_md
    assert "Fair Prob: 64%" in tg_md
    assert "Polymarket: 58% ($0.58)" in tg_md
    assert "Top-3 Depth: $500 @ $0.58, $1,200 @ $0.59" in tg_md
    assert "[🔗 BUY YES ON POLYMARKET]" in tg_md


def test_webhook_not_dispatched_for_3pct_edge_when_gate_is_4pct(tmp_path: Path):
    """
    Verify that a 3.0% edge alert is suppressed when the subscription's
    `min_edge_gate` is 4.0%.
    """
    sent_calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: float = 5.0):
        sent_calls.append({"url": url, "json": json})
        return _DummyResponse(204)

    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    dispatcher = WebhookDispatcher(truth_store=truth, bus=bus, http_post=fake_post)

    dispatcher.register_subscription(
        user_id="user_beta",
        platform="discord",
        webhook_url="https://discord.com/api/webhooks/987654321098765432/ZyXwVuTsRqPoNmLkJiHgFeDcBa_654321",
        min_edge_gate=4.0,
        polymarket_only=True,
    )

    alert_3pct = {
        "player_id": "nba_tyrese_maxey",
        "player_name": "Tyrese Maxey",
        "team": "PHI",
        "market": "points",
        "market_label": "PTS Over 26.5",
        "line": 26.5,
        "fair_prob": 0.61,
        "implied_prob": 0.58,
        "poly_ask_price": 0.58,
        "edge_pct": 3.0,
        "venue_type": "polymarket",
        "book": "Polymarket",
    }

    outcomes = dispatcher.dispatch_alert(alert_3pct, async_dispatch=False, now_epoch=1700000000.0)
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "suppressed_below_gate"
    assert len(sent_calls) == 0


def test_five_minute_deduplication_lock_prevents_duplicate_spam(tmp_path: Path):
    """
    Verify the 5-minute (300s) `webhook_lock:{user_id}:{player_id}:{prop_type}` deduplication
    lock: firing the same alert twice within 300s sends only ONE webhook message, and
    firing again after 301s sends a second message.
    """
    sent_calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: float = 5.0):
        sent_calls.append({"url": url, "json": json})
        return _DummyResponse(200)

    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    dispatcher = WebhookDispatcher(truth_store=truth, bus=bus, http_post=fake_post)

    dispatcher.register_subscription(
        user_id="user_dedup",
        platform="telegram",
        webhook_url="-1001928374650",
        min_edge_gate=4.0,
        polymarket_only=True,
    )

    alert = {
        "player_id": "nba_giannis",
        "player_name": "Giannis Antetokounmpo",
        "team": "MIL",
        "market": "points",
        "market_label": "PTS Over 31.5",
        "line": 31.5,
        "fair_prob": 0.64,
        "implied_prob": 0.58,
        "poly_ask_price": 0.58,
        "edge_pct": 6.0,
        "venue_type": "polymarket",
        "book": "Polymarket",
    }

    t0 = 1700000000.0
    # 1st dispatch at t0 -> SENT
    out1 = dispatcher.dispatch_alert(alert, async_dispatch=False, now_epoch=t0)
    assert out1[0]["status"] == "sent"
    assert len(sent_calls) == 1

    # 2nd dispatch 45 seconds later (within 300s TTL) -> SUPPRESSED by lock
    out2 = dispatcher.dispatch_alert(alert, async_dispatch=False, now_epoch=t0 + 45.0)
    assert out2[0]["status"] == "suppressed_dedup_lock"
    assert out2[0]["lock_key"] == build_webhook_lock_key("user_dedup", "nba_giannis", "points")
    assert len(sent_calls) == 1

    # 3rd dispatch 301 seconds later (after 300s TTL expires) -> SENT again
    out3 = dispatcher.dispatch_alert(alert, async_dispatch=False, now_epoch=t0 + 301.0)
    assert out3[0]["status"] == "sent"
    assert len(sent_calls) == 2


def test_ssrf_protection_and_404_auto_deactivation(tmp_path: Path):
    """
    Verify:
    1. SSRF protection blocks localhost, cloud metadata IPs, HTTP URLs, and arbitrary domains.
    2. If a Discord webhook returns HTTP 404 (deleted by user), the subscription is
       automatically marked `active_status=False` in `webhook_subscriptions`.
    """
    with pytest.raises(ValueError):
        validate_webhook_target("discord", "http://169.254.169.254/latest/meta-data/")

    with pytest.raises(ValueError):
        validate_webhook_target("discord", "https://localhost:8000/api/webhooks/123/abc")

    with pytest.raises(ValueError):
        validate_webhook_target("discord", "https://evil.example.com/api/webhooks/123/abc")

    def fake_404_post(url: str, json: dict[str, Any], timeout: float = 5.0):
        return _DummyResponse(404)

    truth = TruthStore(sqlite_path=tmp_path / "truth.db")
    bus = DurableRedisStreamBus(wal_db_path=tmp_path / "wal.db")
    dispatcher = WebhookDispatcher(truth_store=truth, bus=bus, http_post=fake_404_post)

    sub = dispatcher.register_subscription(
        user_id="user_404",
        platform="discord",
        webhook_url="https://discord.com/api/webhooks/111222333444555666/DeletedToken_999",
        min_edge_gate=4.0,
        polymarket_only=True,
    )
    assert sub["active_status"] is True

    alert = {
        "player_id": "nba_sga",
        "player_name": "Shai Gilgeous-Alexander",
        "team": "OKC",
        "market": "points",
        "line": 29.5,
        "fair_prob": 0.65,
        "implied_prob": 0.58,
        "edge_pct": 7.0,
        "venue_type": "polymarket",
    }

    outcomes = dispatcher.dispatch_alert(alert, async_dispatch=False, now_epoch=1700000000.0)
    assert outcomes[0]["status"] == "deactivated_404"

    # Subscription must now be inactive in the database
    active_subs = truth.list_webhook_subscriptions(user_id="user_404", active_only=True)
    assert len(active_subs) == 0
    all_subs = truth.list_webhook_subscriptions(user_id="user_404", active_only=False)
    assert len(all_subs) == 1
    assert all_subs[0]["active_status"] is False



def test_discord_embed_sportsbook_button_and_book_field(tmp_path: Path):
    """Mission W4: a sportsbook alert (DK/FD) gets a `View on [Book]` button
    and the Book field carries the book display name."""
    alert_dk = {
        "player_id": "nba_giannis",
        "player_name": "Giannis Antetokounmpo",
        "team": "MIL",
        "market": "points",
        "market_label": "PTS Over 31.5",
        "line": 31.5,
        "fair_line": 34.2,
        "fair_prob": 0.641,
        "implied_prob": 0.529,
        "edge_pct": 11.2,
        "depth_tooltip": "$2,000 available at $1.91",
        "deep_link": "https://sportsbook.draftkings.com/nba/giannis-pts",
        "venue_type": "sportsbook",
        "book": "DraftKings",
    }
    payload = format_discord_embed(alert_dk)
    embed = payload["embeds"][0]
    assert embed["title"] == "🚨 LIVE SNIPER ALERT: Giannis Antetokounmpo"
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Book"] == "DraftKings"
    assert fields["Proj Line"] == "34.2"
    assert fields["Edge"] == "+11.2%"
    button = payload["components"][0]["components"][0]
    assert button["label"] == "🔗 View on DraftKings"
    assert button["url"] == "https://sportsbook.draftkings.com/nba/giannis-pts"
