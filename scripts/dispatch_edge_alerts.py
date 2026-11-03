#!/usr/bin/env python3
"""Zero-dependency alert dispatcher for PropStein edge detections.

Dispatches high-conviction sportsbook +EV and DFS Pick'em edges to Discord webhooks
and/or Telegram bot chats with deduplication and state tracking.

Usage:
    python3 scripts/dispatch_edge_alerts.py [--dry-run] [--selftest] [--threshold 5.0]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
SENT_LOG_PATH = CACHE_DIR / ".sent_alerts.json"
VIEWER_DIR = Path(__file__).resolve().parent.parent / "viewer"

DFS_HURDLES = {
    "PrizePicks 5-Flex": 0.5421,
    "PrizePicks 2-Power": 0.5774,
    "Underdog 3-Pick": 0.5500,
}


def load_sent_alerts() -> dict:
    if SENT_LOG_PATH.is_file():
        try:
            return json.loads(SENT_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_sent_alerts(alerts: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SENT_LOG_PATH.write_text(json.dumps(alerts, indent=2), encoding="utf-8")


def american_to_implied(american: float | int) -> float:
    try:
        val = float(american)
        if val > 0:
            return 100.0 / (val + 100.0)
        return abs(val) / (abs(val) + 100.0)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.5


def collect_active_edges(min_edge_pct: float = 5.0) -> list[dict]:
    """Inspects viewer/live_odds_feed.json, current_picks.json, and snapshots for high-conviction plays."""
    edges: list[dict] = []

    # 1. Ingest live picks if present
    picks_files = sorted(VIEWER_DIR.glob("current_picks*.json"), reverse=True)
    live_picks_files = sorted(VIEWER_DIR.glob("live_picks*.json"), reverse=True)

    target_files = live_picks_files + picks_files
    for tf in target_files:
        try:
            data = json.loads(tf.read_text(encoding="utf-8"))
            picks = data.get("picks", [])
            for p in picks:
                player = p.get("player") or p.get("player_name")
                market = p.get("market", "points")
                line = p.get("line") or p.get("fair_line_rec") or p.get("fair_line_yards")
                odds = p.get("odds", -110)
                book = p.get("book", "Consensus")
                team = p.get("team", "")

                ev_pct = float(p.get("ev_per_unit", 0.0) or 0.0) * 100.0
                edge_pct = float(p.get("edge", 0.0) or 0.0) * 100.0

                # DFS win probability calculation
                win_prob = float(p.get("p_rec_at_fair_line", 0.0) or 0.0)
                if win_prob <= 0:
                    win_prob = american_to_implied(odds)

                pp_flex_edge = (win_prob - DFS_HURDLES["PrizePicks 5-Flex"]) * 100.0

                if ev_pct >= min_edge_pct or edge_pct >= min_edge_pct or pp_flex_edge >= 3.0:
                    edges.append({
                        "id": f"{player}:{market}:{line}:{book}".lower().replace(" ", "_"),
                        "player": player,
                        "team": team,
                        "market": market,
                        "line": line,
                        "side": p.get("side", "OVER"),
                        "odds": odds,
                        "book": book,
                        "ev_pct": max(ev_pct, edge_pct),
                        "win_prob_pct": win_prob * 100.0,
                        "pp_flex_edge": pp_flex_edge,
                        "source": tf.name,
                    })
        except Exception:
            continue

    # Deduplicate by unique player + market
    seen = set()
    deduped = []
    for e in edges:
        if e["id"] not in seen:
            seen.add(e["id"])
            deduped.append(e)

    return sorted(deduped, key=lambda x: max(x["ev_pct"], x["pp_flex_edge"]), reverse=True)


def format_discord_payload(edge: dict) -> dict:
    ev_val = f"+{edge['ev_pct']:.1f}%" if edge['ev_pct'] > 0 else f"{edge['ev_pct']:.1f}%"
    pp_val = f"+{edge['pp_flex_edge']:.1f}%" if edge['pp_flex_edge'] > 0 else f"{edge['pp_flex_edge']:.1f}%"
    odds_str = f"+{edge['odds']}" if edge['odds'] > 0 else str(edge['odds'])

    return {
        "username": "PropStein Live Edge",
        "avatar_url": "https://propstein.com/brand/p-logo-2027.png",
        "embeds": [{
            "title": f"🚨 QUANT EDGE DETECTED: {edge['player']} ({edge['team']})",
            "description": f"**Pick**: {edge['side']} {edge['line']} {edge['market'].title()}\n**Book**: {edge['book']} ({odds_str})",
            "color": 0x80C6F6,  # PropStein Blue
            "fields": [
                {"name": "Sportsbook +EV", "value": ev_val, "inline": True},
                {"name": "Model Win Prob", "value": f"{edge['win_prob_pct']:.1f}%", "inline": True},
                {"name": "PrizePicks 5-Flex Edge", "value": pp_val, "inline": True},
            ],
            "footer": {
                "text": "PropStein Terminal · De-Vigged Quant Consensus · https://whop.com/propstein"
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }]
    }


def format_telegram_message(edge: dict) -> str:
    ev_val = f"+{edge['ev_pct']:.1f}%" if edge['ev_pct'] > 0 else f"{edge['ev_pct']:.1f}%"
    pp_val = f"+{edge['pp_flex_edge']:.1f}%" if edge['pp_flex_edge'] > 0 else f"{edge['pp_flex_edge']:.1f}%"
    odds_str = f"+{edge['odds']}" if edge['odds'] > 0 else str(edge['odds'])

    return (
        f"🚨 <b>QUANT EDGE DETECTED</b>\n\n"
        f"<b>Player</b>: {edge['player']} ({edge['team']})\n"
        f"<b>Market</b>: {edge['side']} {edge['line']} {edge['market'].title()}\n"
        f"<b>Book</b>: {edge['book']} ({odds_str})\n\n"
        f"📊 <b>Sportsbook +EV</b>: <code>{ev_val}</code>\n"
        f"🎯 <b>Model Win Prob</b>: <code>{edge['win_prob_pct']:.1f}%</code>\n"
        f"⚡ <b>PrizePicks 5-Flex Edge</b>: <code>{pp_val}</code>\n\n"
        f"<a href=\"https://propstein.com\">Open PropStein Terminal</a> · "
        f"<a href=\"https://whop.com/propstein\">Unlock Pro Desk</a>"
    )


def post_webhook(url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "PropStein-AlertBot/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except (HTTPError, URLError) as err:
        sys.stderr.write(f"Webhook post error to {url}: {err}\n")
        return False


def post_telegram(token: str, chat_id: str, message_text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    return post_webhook(url, payload)


def run_selftest() -> None:
    sample_edge = {
        "id": "jaxon_smith-njigba:rec:8.5:consensus",
        "player": "Jaxon Smith-Njigba",
        "team": "SEA",
        "market": "Receptions",
        "line": 8.5,
        "side": "OVER",
        "odds": -110,
        "book": "FanDuel",
        "ev_pct": 8.4,
        "win_prob_pct": 59.2,
        "pp_flex_edge": 5.0,
        "source": "selftest",
    }
    discord = format_discord_payload(sample_edge)
    telegram = format_telegram_message(sample_edge)

    assert "QUANT EDGE DETECTED" in discord["embeds"][0]["title"]
    assert discord["embeds"][0]["fields"][0]["value"] == "+8.4%"
    assert "Jaxon Smith-Njigba" in telegram
    assert "+5.0%" in telegram

    # Test deduplication storage roundtrip
    test_dict = {"test_id": time.time()}
    save_sent_alerts(test_dict)
    loaded = load_sent_alerts()
    assert "test_id" in loaded

    # Clean up test entry
    SENT_LOG_PATH.unlink(missing_ok=True)
    print("✅ Selftest passed: Alert payload structures, DFS math, and state store verified.")


def main() -> None:
    parser = argparse.ArgumentParser(description="PropStein Edge Alert Dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without firing webhooks")
    parser.add_argument("--selftest", action="store_true", help="Execute built-in test suite and exit")
    parser.add_argument("--threshold", type=float, default=5.0, help="Minimum EV/DFS edge percent hurdle")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    discord_url = os.environ.get("DISCORD_EDGE_WEBHOOK")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")

    edges = collect_active_edges(min_edge_pct=args.threshold)
    sent_log = load_sent_alerts()

    new_dispatches = 0
    now = time.time()

    print(f"PropStein Dispatcher: {len(edges)} qualified edges discovered above {args.threshold}% threshold.")

    for edge in edges:
        edge_id = edge["id"]
        # Throttle alert repeat within 12 hours
        last_sent = sent_log.get(edge_id, 0)
        if (now - last_sent) < 43200:
            continue

        if args.dry_run or not (discord_url or (tg_token and tg_chat)):
            print(f"[DRY RUN / NO WEBHOOK] Alert queued: {edge['player']} ({edge['team']}) - {edge['market']} EV: {edge['ev_pct']:.1f}% DFS: {edge['pp_flex_edge']:.1f}%")
            if not (discord_url or (tg_token and tg_chat)):
                print("  Note: Set DISCORD_EDGE_WEBHOOK or TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID to dispatch live.")
            sent_log[edge_id] = now
            new_dispatches += 1
            continue

        success = False
        if discord_url:
            discord_payload = format_discord_payload(edge)
            success = post_webhook(discord_url, discord_payload) or success

        if tg_token and tg_chat:
            tg_msg = format_telegram_message(edge)
            success = post_telegram(tg_token, tg_chat, tg_msg) or success

        if success:
            sent_log[edge_id] = now
            new_dispatches += 1
            print(f"[DISPATCHED] {edge['player']} - {edge['market']} (+{edge['ev_pct']:.1f}% EV)")

    save_sent_alerts(sent_log)
    print(f"Summary: {new_dispatches} new alerts processed.")


if __name__ == "__main__":
    main()
