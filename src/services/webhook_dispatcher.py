"""
Rate-Limited Discord & Telegram Webhook Dispatch Service (`src/services/webhook_dispatcher.py`).

Responsibilities:
1. Subscribers Management (`webhook_subscriptions` table in `TruthStore`):
   Stores `user_id`, `platform` (`discord` / `telegram`), `webhook_url` (or `chat_id`),
   `min_edge_gate`, `polymarket_only`, and `active_status`.
2. 5-Minute Rate Limiting & Deduplication Lock:
   Enforces `webhook_lock:{user_id}:{player_id}:{prop_type}` with a 300-second TTL
   in Redis (with durable SQLite fallback) so jittering live lines never spam users.
3. Institutional Formatting (mission W4 — clean, high-contrast Lime):
   `format_discord_embed(alert)`:
   - Title: `🚨 LIVE SNIPER ALERT: [Player Name]`
   - Fields: `Edge` (lime embed), `Proj Line` vs `Market Line`, `Book`
   - Description: prop label, Fair % vs Market %, Top-3 Depth
   - Link button: `🔗 Execute on Polymarket` / `🔗 View on DraftKings`
   `format_telegram_markdown(alert)` keeps the compact one-pastebin layout.
4. Security & Resilience:
   - SSRF Protection (`validate_webhook_target`) strictly whitelists official Discord
     and Telegram endpoints and blocks private/internal IPs or arbitrary hosts.
   - Graceful 404 Deactivation: If a webhook returns HTTP 404 (deleted by user),
     automatically marks the subscription `inactive` (`active_status = False`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ipaddress
import logging
import os
import re
import sqlite3
import time
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from src.agents.persistence import DurableRedisStreamBus, TruthStore
from src.agents.schemas import SniperAlert

logger = logging.getLogger("propwire.service.webhook_dispatcher")

WEBHOOK_LOCK_TTL_SECONDS = 300  # 5-minute deduplication window per (user, player, prop)

ALLOWED_DISCORD_HOSTS = {
    "discord.com",
    "www.discord.com",
    "discordapp.com",
    "www.discordapp.com",
    "ptb.discord.com",
    "canary.discord.com",
}
DISCORD_WEBHOOK_PATH_RE = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_\-]+/?$")

ALLOWED_TELEGRAM_HOSTS = {"api.telegram.org"}
TELEGRAM_CHAT_ID_RE = re.compile(r"^(?:@[A-Za-z0-9_]{4,64}|-?\d{5,20})$")

# Book display names for the Discord `Book` field / button label (W4)
BOOK_DISPLAY = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "polymarket": "Polymarket",
    "betmgm": "BetMGM",
    "pinnacle": "Pinnacle",
    "caesars": "Caesars",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "bet365": "bet365",
}


def build_webhook_lock_key(user_id: str, player_id: str, prop_type: str) -> str:
    """Return canonical 5-minute rate-limit Redis key."""
    u = str(user_id or "default").strip().lower()
    p = str(player_id or "unknown").strip().lower()
    m = str(prop_type or "points").strip().lower()
    return f"webhook_lock:{u}:{p}:{m}"


def _is_forbidden_ip_or_host(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host or host in ("localhost", "0.0.0.0", "127.0.0.1", "::1", "169.254.169.254"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def validate_webhook_target(platform: str, webhook_url_or_chat_id: str) -> str:
    """
    SSRF Protection:
    Validate that user-supplied webhook targets point strictly to official
    Discord (`discord.com/api/webhooks/...`) or Telegram (`api.telegram.org/bot...`
    or valid Telegram `chat_id`) endpoints over HTTPS.
    """
    plat = str(platform or "").strip().lower()
    raw = str(webhook_url_or_chat_id or "").strip()
    if not raw:
        raise ValueError("Webhook target cannot be empty")

    if plat == "discord":
        parsed = urlparse(raw)
        if parsed.scheme != "https":
            raise ValueError("Discord webhook URL must use https://")
        host = (parsed.hostname or "").lower()
        if _is_forbidden_ip_or_host(host) or host not in ALLOWED_DISCORD_HOSTS:
            raise ValueError(f"Forbidden Discord webhook host '{host}' (SSRF guard)")
        if not DISCORD_WEBHOOK_PATH_RE.match(parsed.path or ""):
            raise ValueError("Discord webhook path must match /api/webhooks/{id}/{token}")
        return raw

    if plat == "telegram":
        # Allow either a valid Telegram chat_id (e.g. "-100123456789" or "@propwire_alerts")
        # or a full https://api.telegram.org/bot<TOKEN>/sendMessage URL.
        if TELEGRAM_CHAT_ID_RE.match(raw):
            return raw
        parsed = urlparse(raw)
        if parsed.scheme != "https":
            raise ValueError("Telegram webhook URL must use https:// or be a valid chat_id")
        host = (parsed.hostname or "").lower()
        if _is_forbidden_ip_or_host(host) or host not in ALLOWED_TELEGRAM_HOSTS:
            raise ValueError(f"Forbidden Telegram webhook host '{host}' (SSRF guard)")
        if not (parsed.path or "").startswith("/bot"):
            raise ValueError("Telegram URL path must start with /bot")
        return raw

    raise ValueError(f"Unsupported webhook platform '{platform}' (expected 'discord' or 'telegram')")


def _normalize_alert_dict(alert: dict[str, Any] | SniperAlert, arb_card: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = alert.model_dump(mode="json") if isinstance(alert, SniperAlert) else dict(alert)
    card = dict(arb_card or {})

    player_name = str(card.get("player_name") or raw.get("player_name") or "Player")
    market = str(card.get("market") or raw.get("market") or "points").lower()
    line = float(card.get("line") if card.get("line") is not None else raw.get("line", 24.5))
    mkt_short = (
        "PTS"
        if market == "points"
        else "REB"
        if market == "rebounds"
        else "AST"
        if market == "assists"
        else "3PT"
        if market == "threes"
        else "REC YDS"
        if market == "receiving_yards"
        else market.upper()
    )
    market_label = str(card.get("market_label") or f"{mkt_short} Over {line:.1f}")

    fair_prob_raw = float(card.get("fair_prob") if card.get("fair_prob") is not None else raw.get("fair_prob", 0.64))
    fair_prob_pct = round(fair_prob_raw * 100.0 if fair_prob_raw <= 1.0 else fair_prob_raw)

    imp_prob_raw = float(card.get("implied_prob") if card.get("implied_prob") is not None else raw.get("implied_prob", 0.58))
    imp_prob_pct = round(imp_prob_raw * 100.0 if imp_prob_raw <= 1.0 else imp_prob_raw)

    poly_price = float(
        card.get("poly_ask_price")
        if card.get("poly_ask_price") is not None
        else (imp_prob_raw if imp_prob_raw <= 1.0 else imp_prob_raw / 100.0)
    )
    edge_pct = float(card.get("poly_edge_pct") if card.get("poly_edge_pct") is not None else raw.get("edge_pct", 6.0))

    raw_depth = str(
        card.get("depth_tooltip")
        or raw.get("depth_tooltip")
        or "$500 @ $0.58, $1,200 @ $0.59"
    )
    compact_depth = raw_depth.replace(" available at ", " @ ").replace(" at ", " @ ")

    deep_link = str(
        card.get("action_url")
        or card.get("deep_link")
        or raw.get("deep_link")
        or "https://polymarket.com"
    )

    raw_fair_line = (
        card.get("fair_line")
        if card.get("fair_line") is not None
        else raw.get("fair_line")
    )
    try:
        fair_line = float(raw_fair_line) if raw_fair_line is not None else 0.0
    except (TypeError, ValueError):
        fair_line = 0.0
    if fair_line <= 0:
        # Same projection fallback the arb ledger uses when no explicit fair line ships
        fair_line = round(line * (1.0 + max(edge_pct, 0.0) / 100.0), 1)

    book_raw = str(raw.get("book") or ("Polymarket" if str(card.get("venue_type") or raw.get("venue_type") or "") == "polymarket" else "DraftKings"))
    book_display = BOOK_DISPLAY.get(book_raw.strip().lower(), book_raw.strip())

    return {
        "player_id": str(card.get("player_id") or raw.get("player_id") or player_name.lower().replace(" ", "_")),
        "player_name": player_name,
        "team": str(card.get("team") or raw.get("team") or ""),
        "market": market,
        "market_label": market_label,
        "line": line,
        "fair_line": fair_line,
        "fair_prob_pct": fair_prob_pct,
        "implied_prob_pct": imp_prob_pct,
        "poly_price": poly_price,
        "edge_pct": edge_pct,
        "top3_depth": compact_depth,
        "deep_link": deep_link,
        "venue_type": str(raw.get("venue_type") or ("polymarket" if card else "sportsbook")).lower(),
        "book": book_raw,
        "book_display": book_display,
    }


def format_discord_embed(
    alert: dict[str, Any] | SniperAlert,
    arb_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a clean, high-contrast Discord webhook payload (mission W4):
      - Title: `🚨 LIVE SNIPER ALERT: [Player Name]`
      - Fields: `Edge` (lime embed color), `Proj Line` vs `Market Line`, `Book`
      - One-line description: prop · Fair % vs Market % · Top-3 Depth
      - Link button: `🔗 Execute on Polymarket` or `🔗 View on [Book]`
    """
    info = _normalize_alert_dict(alert, arb_card=arb_card)
    is_polymarket = info["venue_type"] == "polymarket" or info["book_display"].lower() == "polymarket"
    button_label = (
        "🔗 Execute on Polymarket"
        if is_polymarket
        else f"🔗 View on {info['book_display']}"
    )
    edge_sign = "+" if float(info["edge_pct"]) >= 0 else ""
    description = (
        f"**{info['market_label']}** · "
        f"Fair **{info['fair_prob_pct']}%** vs Market **{info['implied_prob_pct']}%** (${info['poly_price']:.2f})\n"
        f"Top-3 Depth: {info['top3_depth']}"
    )
    return {
        "username": "PropWire Sniper Terminal",
        "content": "",
        "embeds": [
            {
                "title": f"🚨 LIVE SNIPER ALERT: {info['player_name']}",
                "url": info["deep_link"],
                "description": description,
                "color": 0xA3E635,  # Lime-400 (terminal accent)
                "fields": [
                    {"name": "Edge", "value": f"{edge_sign}{info['edge_pct']:.1f}%", "inline": True},
                    {"name": "Proj Line", "value": f"{info['fair_line']:.1f}", "inline": True},
                    {"name": "Market Line", "value": f"{info['line']:.1f}", "inline": True},
                    {"name": "Book", "value": info["book_display"], "inline": True},
                ],
                "footer": {"text": "PropWire · No LLM in Decision Path"},
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,  # LINK button
                        "label": button_label,
                        "url": info["deep_link"],
                    }
                ],
            }
        ],
    }


def format_telegram_markdown(
    alert: dict[str, Any] | SniperAlert,
    arb_card: dict[str, Any] | None = None,
) -> str:
    """
    Build a clean Telegram Markdown alert message containing:
      - `[PLAYER NAME] | PTS Over 24.5`
      - `Fair Prob: 64%`
      - `Polymarket: 58% ($0.58)`
      - `Top-3 Depth: $500 @ $0.58, $1,200 @ $0.59`
      - `[🔗 BUY YES ON POLYMARKET]` deep link
    """
    info = _normalize_alert_dict(alert, arb_card=arb_card)
    return (
        f"🟢 *{info['player_name']} | {info['market_label']}*\n"
        f"Fair Prob: {info['fair_prob_pct']}%\n"
        f"Polymarket: {info['implied_prob_pct']}% (${info['poly_price']:.2f})\n"
        f"Edge: +{info['edge_pct']:.1f}%\n"
        f"Top-3 Depth: {info['top3_depth']}\n"
        f"[🔗 BUY YES ON POLYMARKET]({info['deep_link']})"
    )


class WebhookDispatcher:
    """
    Rate-limited, SSRF-hardened Discord & Telegram webhook dispatcher.
    """

    def __init__(
        self,
        truth_store: TruthStore | None = None,
        bus: DurableRedisStreamBus | None = None,
        http_post: Callable[..., Any] | None = None,
        lock_ttl_seconds: int = WEBHOOK_LOCK_TTL_SECONDS,
    ) -> None:
        self.truth = truth_store or TruthStore()
        self.bus = bus or DurableRedisStreamBus()
        self.http_post = http_post or requests.post
        self.lock_ttl_seconds = int(lock_ttl_seconds)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="propwire-webhook")
        self._maybe_seed_env_subscriptions()

    def _maybe_seed_env_subscriptions(self) -> None:
        """Seed subscriptions from DISCORD_WEBHOOK_URL env var if provided and valid."""
        env_discord = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if env_discord:
            try:
                self.register_subscription(
                    user_id="default_user",
                    platform="discord",
                    webhook_url=env_discord,
                    min_edge_gate=float(os.environ.get("WEBHOOK_MIN_EDGE_GATE", "4.0")),
                    polymarket_only=os.environ.get("WEBHOOK_POLYMARKET_ONLY", "false").lower() in ("1", "true", "yes"),
                    active_status=True,
                    subscription_id="env_default_discord",
                )
            except Exception as exc:
                logger.warning("Could not auto-seed DISCORD_WEBHOOK_URL: %s", exc)

    def register_subscription(
        self,
        *,
        user_id: str,
        platform: str,
        webhook_url: str,
        min_edge_gate: float = 4.0,
        polymarket_only: bool = True,
        active_status: bool = True,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate SSRF rules and persist a user's Discord or Telegram webhook subscription."""
        validated_target = validate_webhook_target(platform, webhook_url)
        return self.truth.upsert_webhook_subscription(
            user_id=user_id,
            platform=platform.lower(),
            webhook_url=validated_target,
            min_edge_gate=float(min_edge_gate),
            polymarket_only=bool(polymarket_only),
            active_status=bool(active_status),
            subscription_id=subscription_id,
        )

    def acquire_dedup_lock(
        self,
        *,
        user_id: str,
        player_id: str,
        prop_type: str,
        ttl_seconds: int | None = None,
        now_epoch: float | None = None,
    ) -> bool:
        """
        Attempt to acquire the 5-minute deduplication lock:
          `webhook_lock:{user_id}:{player_id}:{prop_type}`
        Returns `True` if acquired (ok to send), or `False` if already locked within TTL.
        """
        ttl = int(ttl_seconds if ttl_seconds is not None else self.lock_ttl_seconds)
        now_ts = float(now_epoch if now_epoch is not None else time.time())
        lock_key = build_webhook_lock_key(user_id, player_id, prop_type)

        # 1. Check live Redis if available
        if self.bus._redis is not None and now_epoch is None:
            try:
                acquired = self.bus._redis.set(lock_key, "1", ex=ttl, nx=True)
                if not acquired:
                    return False
            except Exception:
                pass

        # 2. Enforce durable SQLite lock table
        with sqlite3.connect(self.truth.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT expires_at_epoch FROM webhook_locks WHERE lock_key = ?",
                (lock_key,),
            ).fetchone()
            if row and float(row["expires_at_epoch"]) > now_ts:
                return False

            conn.execute(
                """
                INSERT OR REPLACE INTO webhook_locks (lock_key, expires_at_epoch)
                VALUES (?, ?)
                """,
                (lock_key, now_ts + ttl),
            )
        return True

    def _deliver_single_subscription(
        self,
        sub: dict[str, Any],
        alert: dict[str, Any] | SniperAlert,
        arb_card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver formatted alert to a single validated Discord or Telegram subscription."""
        platform = str(sub["platform"]).lower()
        target = str(sub["webhook_url"])
        sub_id = str(sub["subscription_id"])

        try:
            validate_webhook_target(platform, target)
        except ValueError as exc:
            logger.warning("Disabling invalid webhook subscription %s: %s", sub_id, exc)
            self.truth.deactivate_webhook_subscription(sub_id)
            return {"subscription_id": sub_id, "status": "deactivated_invalid_url", "reason": str(exc)}

        if platform == "discord":
            payload = format_discord_embed(alert, arb_card=arb_card)
            url = target
        else:
            text_md = format_telegram_markdown(alert, arb_card=arb_card)
            if target.startswith("https://"):
                url = target
                payload = {"text": text_md, "parse_mode": "Markdown", "disable_web_page_preview": False}
            else:
                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "test_bot_token")
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": target,
                    "text": text_md,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                }

        try:
            resp = self.http_post(url, json=payload, timeout=5.0)
            status_code = int(getattr(resp, "status_code", 200))
            if status_code == 404:
                # Webhook was deleted by user -> mark subscription inactive and stop trying
                self.truth.deactivate_webhook_subscription(sub_id)
                return {
                    "subscription_id": sub_id,
                    "platform": platform,
                    "status": "deactivated_404",
                    "status_code": 404,
                }
            if 200 <= status_code < 300:
                return {
                    "subscription_id": sub_id,
                    "platform": platform,
                    "status": "sent",
                    "status_code": status_code,
                    "payload": payload,
                }
            return {
                "subscription_id": sub_id,
                "platform": platform,
                "status": "failed_http",
                "status_code": status_code,
            }
        except Exception as exc:
            logger.warning("Webhook delivery error for %s: %s", sub_id, exc)
            return {
                "subscription_id": sub_id,
                "platform": platform,
                "status": "error",
                "reason": str(exc),
            }

    def dispatch_alert(
        self,
        alert: dict[str, Any] | SniperAlert,
        *,
        arb_card: dict[str, Any] | None = None,
        user_id: str | None = None,
        async_dispatch: bool = False,
        now_epoch: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Evaluate an incoming `SniperAlert` or Cross-Venue Arb against active
        `webhook_subscriptions`:
          1. Check `alert.edge_pct >= subscription.min_edge_gate`
          2. Check `polymarket_only` preference
          3. Check 5-minute Redis/SQLite deduplication lock `webhook_lock:{user_id}:{player_id}:{prop_type}`
          4. Dispatch formatted Discord embed or Telegram Markdown
        """
        info = _normalize_alert_dict(alert, arb_card=arb_card)
        edge_pct = float(info["edge_pct"])
        player_id = str(info["player_id"])
        prop_type = str(info["market"])
        venue_type = str(info["venue_type"])

        subs = self.truth.list_webhook_subscriptions(user_id=user_id, active_only=True)
        outcomes: list[dict[str, Any]] = []

        for sub in subs:
            sub_id = str(sub["subscription_id"])
            sub_user = str(sub["user_id"])
            min_gate = float(sub["min_edge_gate"])
            poly_only = bool(sub.get("polymarket_only", True))

            if poly_only and venue_type != "polymarket":
                outcomes.append(
                    {
                        "subscription_id": sub_id,
                        "status": "suppressed_venue_filter",
                        "reason": "Subscription configured for Polymarket Arbs only",
                    }
                )
                continue

            if edge_pct < min_gate:
                outcomes.append(
                    {
                        "subscription_id": sub_id,
                        "status": "suppressed_below_gate",
                        "edge_pct": edge_pct,
                        "min_edge_gate": min_gate,
                    }
                )
                continue

            lock_acquired = self.acquire_dedup_lock(
                user_id=sub_user,
                player_id=player_id,
                prop_type=prop_type,
                now_epoch=now_epoch,
            )
            if not lock_acquired:
                outcomes.append(
                    {
                        "subscription_id": sub_id,
                        "status": "suppressed_dedup_lock",
                        "lock_key": build_webhook_lock_key(sub_user, player_id, prop_type),
                    }
                )
                continue

            if async_dispatch:
                self._executor.submit(self._deliver_single_subscription, sub, alert, arb_card)
                outcomes.append(
                    {
                        "subscription_id": sub_id,
                        "platform": sub["platform"],
                        "status": "queued_async",
                    }
                )
            else:
                res = self._deliver_single_subscription(sub, alert, arb_card=arb_card)
                outcomes.append(res)

        return outcomes
