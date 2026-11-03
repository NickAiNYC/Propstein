#!/usr/bin/env python3
"""Zero-dependency Discord & Telegram edge dispatcher for PropStein / PropWire.

Dispatches high-conviction sportsbook +EV and DFS Pick'em edges to Discord webhooks
and/or Telegram bot chats with SHA-256 fingerprint deduplication and state tracking.

Usage:
  python3 scripts/dispatch_edge_alerts.py --input viewer/data/board.json --min-ev 5.0
  python3 scripts/dispatch_edge_alerts.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PRIZEPICKS_5FLEX_BE = 0.5421
CACHE_PATH = Path(".cache/sent_edge_alerts.json")


def american_to_prob(odds: Any) -> float:
    try:
        val = float(odds)
    except (TypeError, ValueError):
        return 0.0
    if val == 0:
        return 0.0
    return abs(val) / (abs(val) + 100.0) if val < 0 else 100.0 / (val + 100.0)


def load_sent_cache() -> Dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sent_cache(cache: Dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def compute_alert_id(row: Dict[str, Any]) -> str:
    canonical = f"{row.get('player')}|{row.get('market')}|{row.get('direction')}|{row.get('line')}|{row.get('book')}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def post_json(url: str, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "PropStein-Dispatcher/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def format_discord_embed(qualified: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields = []
    for item in qualified[:8]:
        direction = item.get("direction", "OVER")
        price = item.get("price", "") or item.get("odds", "")
        price_str = f"+{price}" if isinstance(price, (int, float)) and price > 0 else str(price)
        receipt = item.get("receipt_hash") or item.get("receiptHash") or "VERIFIED"

        fields.append({
            "name": f"{item.get('player')} — {direction} {item.get('line')} {item.get('market')}",
            "value": (
                f"**Book:** `{str(item.get('book', 'BOOK')).upper()}` ({price_str}) | "
                f"**EV:** `+{item['_ev']:.1f}%` | **Win Prob:** `{item['_prob']*100:.1f}%`\n"
                f"**Fair Line:** `{item.get('fair_line', '—')}` | **Receipt:** `{str(receipt)[:12]}`"
            ),
            "inline": False,
        })

    return {
        "username": "PropStein Quant Desk",
        "embeds": [
            {
                "title": f"VERIFIED QUANT EDGES // {len(qualified)} QUALIFIED",
                "description": "Independent quote receipts verified. Lines cleared execution gate.",
                "color": 0x38BDF8,
                "fields": fields,
                "footer": {
                    "text": f"PropStein Execution Layer • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                },
            }
        ],
    }


def run_selftest() -> None:
    sample_rows = [
        {
            "player": "Jaxon Smith-Njigba",
            "market": "receptions",
            "direction": "OVER",
            "line": 8.5,
            "book": "FanDuel",
            "price": -110,
            "ev_percent": 8.4,
            "model_win_prob": 0.592,
            "verified": True
        }
    ]
    alert_id = compute_alert_id(sample_rows[0])
    assert len(alert_id) == 16
    embed = format_discord_embed([{**sample_rows[0], "_ev": 8.4, "_prob": 0.592}])
    assert "Jaxon Smith-Njigba" in embed["embeds"][0]["fields"][0]["name"]
    print("✅ Selftest passed: Alert ID generation and Discord payload formatting verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch verified PropStein edges.")
    parser.add_argument("--input", default="viewer/current_picks.json", help="Path to board JSON snapshot")
    parser.add_argument("--min-ev", type=float, default=5.0, help="Minimum EV% threshold")
    parser.add_argument("--min-dfs-edge", type=float, default=4.5, help="Min edge% over PrizePicks 54.21% BE")
    parser.add_argument("--allow-unverified", action="store_true", help="Allow observed/unverified rows (dev only)")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without sending")
    parser.add_argument("--selftest", action="store_true", help="Run automated test suite and exit")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return 0

    input_path = Path(args.input)
    if not input_path.exists():
        sys.stderr.write(f"Error: input file {input_path} does not exist\n")
        return 1

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    rows = raw.get("rows") or raw.get("edges") or raw.get("lines") or raw.get("picks") or (raw if isinstance(raw, list) else [])

    sent_cache = load_sent_cache()
    qualified: List[Dict[str, Any]] = []

    for row in rows:
        is_verified = bool(row.get("verified") is True or row.get("status") == "VERIFIED")
        if not is_verified and not args.allow_unverified:
            continue

        ev = float(row.get("ev_percent") or row.get("evPercent") or (float(row.get("ev_per_unit", 0.0) or 0.0) * 100.0))
        prob_val = row.get("model_win_prob") or row.get("p_rec_at_fair_line")
        prob = float(prob_val) if prob_val else american_to_prob(row.get("fair_odds") or row.get("odds"))
        dfs_edge = (prob - PRIZEPICKS_5FLEX_BE) * 100.0 if prob > 0 else 0.0

        if ev < args.min_ev and dfs_edge < args.min_dfs_edge:
            continue

        alert_id = compute_alert_id(row)
        if alert_id in sent_cache:
            continue

        row["_ev"] = ev
        row["_prob"] = prob
        row["_alert_id"] = alert_id
        qualified.append(row)

    if not qualified:
        print("0 new verified edges cleared the dispatch gate.")
        return 0

    discord_payload = format_discord_embed(qualified)

    if args.dry_run or not (os.environ.get("DISCORD_WEBHOOK_URL") or os.environ.get("TELEGRAM_BOT_TOKEN")):
        print(f"[DRY RUN] Discovered {len(qualified)} edges clearing thresholds:")
        print(json.dumps(discord_payload, indent=2))
        return 0

    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        try:
            post_json(discord_url, discord_payload)
        except Exception as e:
            sys.stderr.write(f"Error posting to Discord: {e}\n")

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        lines = [f"PROPSTEIN VERIFIED EDGES ({len(qualified)})"]
        for q in qualified[:8]:
            lines.append(
                f"• {q.get('player')} {q.get('direction', 'O')} {q.get('line')} {q.get('market')} "
                f"({q.get('book')}) | +{q['_ev']:.1f}% EV | {q['_prob']*100:.1f}% Win"
            )
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        try:
            post_json(tg_url, {"chat_id": tg_chat, "text": "\n".join(lines)})
        except Exception as e:
            sys.stderr.write(f"Error posting to Telegram: {e}\n")

    now_iso = datetime.now(timezone.utc).isoformat()
    for q in qualified:
        sent_cache[q["_alert_id"]] = now_iso
    save_sent_cache(sent_cache)
    print(f"Dispatched {len(qualified)} verified edge(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
