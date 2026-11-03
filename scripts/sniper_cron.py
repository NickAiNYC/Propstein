#!/usr/bin/env python3
"""
PropWire Autonomous Market Sniper — Server-Side Cron Evaluator
Executes off-browser evaluation of incoming book quotes against execution hurdles.
Handles 3am overnight runs, enforces 15-minute de-duplication per line,
and dispatches webhook alerts without exposing tokens to client-side browsers.

Usage:
    python scripts/sniper_cron.py [--min-edge 0.15] [--webhook https://discord.com/api/webhooks/...]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIEWER_DIR = os.path.join(BASE_DIR, "viewer")
COOLDOWN_FILE = os.path.join(BASE_DIR, "data", "sniper_cooldowns.json")


def load_cooldowns() -> dict:
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cooldowns(data: dict):
    os.makedirs(os.path.dirname(COOLDOWN_FILE), exist_ok=True)
    try:
        with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        sys.stderr.write(f"[WARN] Failed to save cooldowns: {exc}\n")


def dispatch_telegram(bot_token: str, chat_id: str, payload: dict) -> bool:
    text = (
        f"⚡ <b>PROPWIRE REAL-TIME ALERT</b>
"
        f"<b>Player:</b> {payload.get('player')} ({payload.get('team')} vs {payload.get('opponent')})
"
        f"<b>Pick:</b> {payload.get('side')} {payload.get('line')} ({payload.get('odds')})
"
        f"<b>Edge:</b> +{payload.get('edge_pct')}% | <b>EV:</b> +{payload.get('expected_return')}%
"
        f"<b>Book:</b> {payload.get('book')}
"
        f"<a href="{payload.get('review_url')}">Inspect on Terminal</a>"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        sys.stderr.write(f"[ERROR] Telegram dispatch exception: {e}
")
        return False

def dispatch_webhook(webhook_url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "PROP-WIRE-Sniper-Cron/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"[ERROR] Webhook dispatch HTTP {e.code}: {e.reason}\n")
        return False
    except Exception as e:
        sys.stderr.write(f"[ERROR] Webhook dispatch exception: {e}\n")
        return False


def main():
    parser = argparse.ArgumentParser(description="Evaluate live odds against Sniper criteria server-side.")
    parser.add_argument("--min-edge", type=float, default=0.15, help="Minimum probability edge (default 0.15)")
    parser.add_argument("--gate-met-only", action="store_true", default=True, help="Require institutional gate met and EV > 0")
    parser.add_argument("--webhook", type=str, default=os.environ.get("SNIPER_WEBHOOK_URL", ""), help="Webhook URL")
    parser.add_argument("--telegram-token", type=str, default=os.environ.get("TELEGRAM_BOT_TOKEN", ""), help="Telegram Bot Token")
    parser.add_argument("--telegram-chat-id", type=str, default=os.environ.get("TELEGRAM_CHAT_ID", ""), help="Telegram Chat ID")
    parser.add_argument("--dry-run", action="store_true", help="Print alerts without dispatching webhooks")
    args = parser.parse_args()

    odds_file = os.path.join(VIEWER_DIR, "live_odds_feed.json")
    if not os.path.exists(odds_file):
        print(f"[INFO] No live odds feed found at {odds_file}. Exiting.")
        return 0

    with open(odds_file, "r", encoding="utf-8") as f:
        feed = json.load(f)

    quotes = feed.get("quotes", [])
    now_ms = int(time.time() * 1000)
    cooldowns = load_cooldowns()

    # Clean old cooldowns (> 2 hours)
    cooldowns = {k: v for k, v in cooldowns.items() if now_ms - v < 2 * 3600 * 1000}

    alerts = []
    print(f"[INFO] Evaluating {len(quotes)} quotes with min_edge >= {args.min_edge:.1%}, gate_met_only={args.gate_met_only}")

    # Load shared circuit breaker parameters (single source of truth).
    # Config is per-sport as of config_version 2026.10.24-1: sports.nfl.* is
    # canonical; the legacy flat "thresholds" shape is still accepted as a
    # fallback so older config files keep working during rollout.
    cb_config_file = os.path.join(VIEWER_DIR, "circuit_breaker_config.json")
    drift_yards_hurdle = 5.0
    drift_rec_hurdle = 1.0
    drift_pct_hurdle = 0.12
    beneficiary_max_drift_yards = 8.5
    beneficiary_max_drift_rec = 2.0
    deadman_max_age = 300
    if os.path.exists(cb_config_file):
        try:
            with open(cb_config_file, "r", encoding="utf-8") as f:
                cb_cfg = json.load(f)
            sport_cfg = (cb_cfg.get("sports") or {}).get("nfl") or {}
            th = sport_cfg.get("thresholds") or cb_cfg.get("thresholds", {})
            markets = sport_cfg.get("markets") or {}
            yards_mkt = markets.get("receiving_yards") or {}
            rec_mkt = markets.get("receptions") or {}
            drift_yards_hurdle = float(yards_mkt.get("drift_hurdle", th.get("drift_yards_hurdle", 5.0)))
            drift_rec_hurdle = float(rec_mkt.get("drift_hurdle", th.get("drift_rec_hurdle", 1.0)))
            drift_pct_hurdle = float(th.get("drift_pct_hurdle", 0.12))
            beneficiary_max_drift_yards = float(yards_mkt.get("beneficiary_max_drift", th.get("beneficiary_max_drift_yards", 8.5)))
            beneficiary_max_drift_rec = float(rec_mkt.get("beneficiary_max_drift", th.get("beneficiary_max_drift_rec", 2.0)))
            deadman_max_age = int(th.get("deadman_switch_max_age_seconds", 300))
            print(f"[INFO] Breaker config {cb_cfg.get('config_version', 'legacy')} · nfl calibrated={sport_cfg.get('calibrated', 'unknown')}")
        except Exception as exc:
            print(f"[WARN] Failed to load circuit_breaker_config.json: {exc}")

    # Load news watcher state (dead-man's switch & team locks)
    news_file = os.path.join(VIEWER_DIR, "news_watcher_state.json")
    news_stale = False
    teams_locked = {}
    if os.path.exists(news_file):
        try:
            with open(news_file, "r", encoding="utf-8") as f:
                nw = json.load(f)
                teams_locked = nw.get("teams_locked", {})
                last_polled = nw.get("last_polled_at")
                if last_polled:
                    last_dt = datetime.fromisoformat(last_polled.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if age > deadman_max_age:
                        news_stale = True
                        print(f"[DEAD-MAN'S SWITCH TRIGGERED] News watcher feed is stale ({age:.0f}s > {deadman_max_age}s limit). Suppressing all automated alerts.")
        except Exception as exc:
            print(f"[WARN] Failed to load news_watcher_state.json: {exc}")

    if news_stale:
        print("[HALT] Automated Sniper alerts suppressed due to stale news watcher feed. Exiting.")
        return 0

    # Load modeled injuries and beneficiaries for exemption check
    injuries_file = os.path.join(VIEWER_DIR, "injuries_2026_w7.json")
    modeled_beneficiaries = set()
    modeled_injuries = {}
    if os.path.exists(injuries_file):
        try:
            with open(injuries_file, "r", encoding="utf-8") as f:
                inj_data = json.load(f)
                for inj in inj_data.get("injuries", []):
                    pid = inj.get("player_id")
                    if pid:
                        modeled_injuries[pid] = inj.get("report_status", "")
                    for b_id in inj.get("redistribution_plan", {}).keys():
                        modeled_beneficiaries.add(b_id)
        except Exception as exc:
            print(f"[WARN] Failed to load injuries_2026_w7.json: {exc}")

    snaps_file = os.path.join(VIEWER_DIR, "snapshots_2026_w7.json")
    open_lines = {}
    if os.path.exists(snaps_file):
        try:
            with open(snaps_file, "r", encoding="utf-8") as f:
                snaps = json.load(f)
                for s in snaps:
                    if s.get("quote") and s["quote"].get("line") is not None:
                        open_lines[f"{s.get('player_id')}::{s.get('market')}"] = float(s["quote"]["line"])
        except Exception:
            pass

    for quote in quotes:
        ev = quote.get("evaluation", {})
        edge = float(ev.get("prob_edge", 0.0))
        expected_return = float(ev.get("expected_return", 0.0))
        is_qualified = bool(ev.get("is_qualified", False))

        qualified = not args.gate_met_only or (is_qualified and expected_return > 0)
        if edge >= args.min_edge and qualified:
            pid = quote.get("player_id")
            team = quote.get("team")
            k = f"{pid}::{quote.get('market')}"

            # Check team lock from News Watcher
            if team in teams_locked:
                print(f"[TEAM LOCK] Skipping {quote.get('player_name')} ({team}) — {teams_locked[team].get('reason', 'Offense locked')}")
                continue

            # Volatility Circuit Breaker check with bounded beneficiary exemption
            cur_line = float(quote.get("line", 0.0))
            is_yards = quote.get("market") == "receiving_yards"
            open_line = open_lines.get(k)
            if open_line is not None and open_line > 0:
                drift = round(cur_line - open_line, 1)
                abs_drift = abs(drift)
                drift_pct = abs_drift / open_line
                hurdle = drift_yards_hurdle if is_yards else drift_rec_hurdle
                max_beneficiary = beneficiary_max_drift_yards if is_yards else beneficiary_max_drift_rec

                is_modeled_surge = (pid in modeled_beneficiaries) and (drift > 0)
                is_modeled_absence = (modeled_injuries.get(pid) in ("OUT", "IR")) and (drift < 0)

                if is_modeled_surge and drift > max_beneficiary:
                    print(f"[CIRCUIT BREAKER HALT] Skipping {quote.get('player_name')} ({k}) — surge +{drift} exceeds model absorption limit (+{max_beneficiary}). Oversteamed/second-order news suspected.")
                    continue
                elif is_modeled_surge or is_modeled_absence:
                    print(f"[CIRCUIT BREAKER EXEMPTION] Allowing {quote.get('player_name')} ({k}) — move matches modeled adjustment ({drift:+}).")
                elif abs_drift >= hurdle or drift_pct >= drift_pct_hurdle:
                    print(f"[CIRCUIT BREAKER HALT] Skipping {quote.get('player_name')} ({k}) — line moved sharply {drift:+} ({drift_pct:.1%}). Model baseline may be stale — check breaking news before trading.")
                    continue

            last_alert = cooldowns.get(k, 0)
            if now_ms - last_alert < 15 * 60 * 1000:
                print(f"[COOLDOWN] Skipping {quote.get('player_name')} ({k}) — alerted within 15 mins")
                continue

            side = ev.get("best_side", "OVER")
            odds_val = quote.get("under_odds" if side == "UNDER" else "over_odds")
            alert_payload = {
                "event": "PROP_WIRE_SNIPER_ALERT",
                "source": "PropWire Server Cron",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "player_id": quote.get("player_id"),
                "player": quote.get("player_name"),
                "team": quote.get("team"),
                "opponent": quote.get("opponent"),
                "market": quote.get("market"),
                "side": side,
                "line": quote.get("line"),
                "odds": odds_val,
                "edge_pct": round(edge * 100, 1),
                "expected_return": round(expected_return * 100, 1),
                "book": quote.get("book"),
                "review_url": f"https://propwire.vercel.app/?inspect={quote.get('player_id')}&market={quote.get('market')}"
            }
            alerts.append(alert_payload)
            cooldowns[k] = now_ms

            if args.webhook and not args.dry_run:
                success = dispatch_webhook(args.webhook, alert_payload)
                print(f"[DISPATCH] Sent webhook alert for {quote.get('player_name')}: {'OK' if success else 'FAIL'}")
            if args.telegram_token and args.telegram_chat_id and not args.dry_run:
                tg_ok = dispatch_telegram(args.telegram_token, args.telegram_chat_id, alert_payload)
                print(f"[DISPATCH] Sent Telegram alert for {quote.get('player_name')}: {'OK' if tg_ok else 'FAIL'}")
            if not args.webhook and not (args.telegram_token and args.telegram_chat_id):
                print(f"[TRIGGER] {quote.get('player_name')} ({quote.get('team')}) {side} {quote.get('line')} | Edge: +{edge*100:.1f}% | EV: +{expected_return*100:.1f}%")

    save_cooldowns(cooldowns)
    print(f"[COMPLETE] {len(alerts)} alerts triggered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
