"""Offline tests for scripts/fetch_nfl_props_sweep.py (Phase 1A book #2).

The sweep adds sharp sportsbook player props (The Odds API bulk endpoint) to
the mixed feed. These tests pin the fail-closed contract:
  * book #1 is never blocked — every failure path exits 0, feed untouched;
  * credits are spent only inside an active slate window and above the
    remaining-credit floor;
  * the sweep replaces only ITS OWN rows; Polymarket receipt stamps, synthetic
    rows and feed_status pass through untouched;
  * no sweep row ever carries a verification claim — a second book makes the
    frozen V3 clause checkable per market, it never stamps VERIFIED itself.
No network access: api_get is monkeypatched everywhere.
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "fetch_nfl_props_sweep", ROOT / "scripts" / "fetch_nfl_props_sweep.py")
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)

PM_ROW = {
    "quote_id": "pm_x", "book": "Polymarket", "player_id": "00-0039075",
    "market": "receiving_yards", "line": 74.5, "observed_at": "2026-11-02T12:00:00Z",
    "receipt_id": "pm_x", "content_hash": "a" * 64,
    "source_url": "https://polymarket.com/market/x",
    "over_odds": -110, "under_odds": 110, "liquidity_usd": 50.0,
    "over_token_id": "o", "under_token_id": "u",
    "over_ask_price": 0.55, "under_ask_price": 0.45,
    "over_ask_depth_usd": 50.0, "under_ask_depth_usd": 60.0,
    "verification_status": "OBSERVED", "verification_engine": "verification.v1",
    "verification_receipt_id": "pmr_" + "a" * 16, "verification_clauses": [],
}
SYN_ROW = {"quote_id": "syn_a", "book": "Synthetic Book A",
           "source": "Synthetic Book A Manual Entry (UNVERIFIED - harness fixture)"}


def write_sample_feed(tmp_path):
    feed_path = tmp_path / "live_odds_feed.json"
    feed_path.write_text(json.dumps({
        "feed_status": "LIVE_POLYMARKET_CLOB_RECEIPTED",
        "updated_at": "2026-11-02T21:00:00Z",
        "quotes": [dict(PM_ROW), dict(SYN_ROW)],
        "monitored_books": ["Polymarket"],
        "total_quotes": 2, "polymarket_quotes_count": 1,
        "receipt_matched_quotes_count": 1,
    }), encoding="utf-8")
    return feed_path


def slate_idx():
    pm = sw._load_pm_module()
    return pm.index_slate([
        {"player_id": "00-0039075", "player_display_name": "Puka Nacua",
         "team": "LA", "opponent_team": "LAC", "game_id": "2026_09_LA_LAC"},
        {"player_id": "00-0041234", "player_display_name": "Colston Loveland",
         "team": "CHI", "opponent_team": "ARI", "game_id": "2026_09_CHI_ARI"},
    ])


def bulk_payload():
    """Shaped like the documented bulk /odds response. Pinnacle AND LowVig
    quote the same market/line — the pair that makes frozen V3 checkable."""
    return [
        {"id": "evt1", "commence_time": "2026-11-08T18:15:00Z", "bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -122, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 122, "point": 74.5},
                    {"name": "Over", "description": "Mystery Player", "price": -110, "point": 10.5},
                    {"name": "Under", "description": "Mystery Player", "price": -110, "point": 10.5}]}]},
            {"key": "lowvig", "title": "LowVig", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -120, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 120, "point": 74.5}]}]},
            {"key": "draftkings", "title": "DraftKings", "markets": [
                {"key": "player_reception_yds", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -118, "point": 74.5},
                    {"name": "Under", "description": "Puka Nacua", "price": 118, "point": 74.5},
                    {"name": "Over", "description": "Lonely Player", "price": -120, "point": 30.5}]},
                {"key": "player_receptions", "outcomes": [
                    {"name": "Over", "description": "Puka Nacua", "price": -105, "point": 4.5},
                    {"name": "Under", "description": "Puka Nacua", "price": -115, "point": 4.5}]}]}]},
        {"id": "evt2", "commence_time": "2026-11-08T21:30:00Z", "bookmakers": [
            {"key": "betonlineag", "title": "BetOnline", "markets": [
                {"key": "player_receptions", "outcomes": [
                    {"name": "Over", "description": "Colston Loveland", "price": -110, "point": 4.5},
                    {"name": "Under", "description": "Colston Loveland", "price": -110, "point": 4.5}]}]}]},
    ]


def no_api(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no API call allowed in this path")
    monkeypatch.setattr(sw, "api_get", boom)


def test_missing_key_skips_cleanly_and_never_touches_the_feed(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    no_api(monkeypatch)
    feed_path = write_sample_feed(tmp_path)
    before = feed_path.read_bytes()
    assert sw.run("auto", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0
    assert feed_path.read_bytes() == before


def test_mode_off_skips_even_with_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    no_api(monkeypatch)
    feed_path = write_sample_feed(tmp_path)
    before = feed_path.read_bytes()
    assert sw.run("off", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0
    assert feed_path.read_bytes() == before


def test_inactive_slate_window_spends_no_credits(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    no_api(monkeypatch)
    monkeypatch.setattr(sw, "active_slate_window", lambda: False)
    feed_path = write_sample_feed(tmp_path)
    before = feed_path.read_bytes()
    assert sw.run("auto", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0
    assert feed_path.read_bytes() == before


def test_credit_floor_skips_before_spending(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(sw, "active_slate_window", lambda: True)
    calls = []

    def fake_api(path, params, key):
        calls.append(path)
        assert path.endswith("/events")  # the free probe only
        return [], "50"  # 50 remaining < floor 100

    monkeypatch.setattr(sw, "api_get", fake_api)
    feed_path = write_sample_feed(tmp_path)
    before = feed_path.read_bytes()
    assert sw.run("auto", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0
    assert calls == [f"/sports/{sw.SPORT}/events"]
    assert feed_path.read_bytes() == before


def test_api_failure_exits_zero_and_preserves_book1(tmp_path, monkeypatch):
    """A dead key or API outage must never block the Polymarket publication
    steps around the sweep — main() swallows and logs, exit 0."""
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(sw, "active_slate_window", lambda: True)

    def dead_api(path, params, key):
        raise RuntimeError("HTTP 401 from /sports/americanfootball_nfl/events: bad key")

    monkeypatch.setattr(sw, "api_get", dead_api)
    feed_path = write_sample_feed(tmp_path)
    before = feed_path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["fetch_nfl_props_sweep.py", "--mode", "auto"])
    assert sw.main() == 0
    assert feed_path.read_bytes() == before


def test_bulk_sweep_merges_sharp_books_and_preserves_book1(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(sw, "active_slate_window", lambda: True)

    def fake_api(path, params, key):
        if path.endswith("/events"):
            return [], "5000"
        assert path.endswith("/odds"), path
        assert params["markets"] == "player_receptions,player_reception_yds"
        assert params["regions"] == "us"
        assert "apiKey" not in params  # the key is appended inside api_get only
        return bulk_payload(), "4998"

    monkeypatch.setattr(sw, "api_get", fake_api)
    feed_path = write_sample_feed(tmp_path)
    assert sw.run("auto", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0

    merged = json.loads(feed_path.read_text(encoding="utf-8"))
    sweep_rows = [q for q in merged["quotes"] if q.get("source") == sw.SWEEP_SOURCE]
    # 5 matched quotes: 3x receiving_yards (pinnacle/lowvig/draftkings) +
    # 1x receptions (draftkings) + 1x receptions (betonlineag).
    assert len(sweep_rows) == 5
    # The V3-relevant pair is present and identified — never stamped.
    assert merged["sharp_books_present"] == ["betonlineag", "lowvig", "pinnacle"]
    assert all("verification_status" not in q and q["verified"] is False for q in sweep_rows)
    sharp_flags = {q["book_key"] for q in sweep_rows if q["sharp"]}
    assert sharp_flags == {"pinnacle", "lowvig", "betonlineag"}
    # Book #1 passes through byte-for-byte; synthetic rows persist.
    assert [q for q in merged["quotes"] if q["book"] == "Polymarket"] == [PM_ROW]
    assert any(q["book"] == "Synthetic Book A" for q in merged["quotes"])
    assert merged["feed_status"] == "LIVE_POLYMARKET_CLOB_RECEIPTED"
    assert merged["receipt_matched_quotes_count"] == 1
    assert merged["total_quotes"] == len(merged["quotes"]) == 7
    assert merged["oddsapi_quotes_count"] == 5
    # Atomic publication: fresh manifest whose hash matches the bytes on disk.
    manifest = json.loads((tmp_path / "live_odds_feed.manifest.json").read_text())
    assert manifest["status"] == "PASS_ATOMIC_PUBLISHED"
    assert manifest["sha256"] == hashlib.sha256(feed_path.read_bytes()).hexdigest()

    # Idempotence: a re-sweep replaces its own rows, never duplicates them.
    assert sw.run("auto", 100, slate_idx=slate_idx(), feed_path=feed_path) == 0
    merged2 = json.loads(feed_path.read_text(encoding="utf-8"))
    sweep_rows2 = [q for q in merged2["quotes"] if q.get("source") == sw.SWEEP_SOURCE]
    assert len(sweep_rows2) == 5
    assert merged2["total_quotes"] == 7


def test_parse_bulk_quotes_discards_junk_and_maps_markets():
    rows, off_slate, books_seen = sw.parse_bulk_quotes(
        bulk_payload(), slate_idx(), "2026-11-02T21:00:00+00:00",
        {"pinnacle", "betonlineag", "lowvig", "circasports"})
    assert off_slate == 1  # Mystery Player is not on the slate
    assert books_seen == ["betonlineag", "draftkings", "lowvig", "pinnacle"]
    assert not any("Lonely" in r["player_name"] for r in rows)  # unpaired side dropped
    assert {r["market"] for r in rows} == {"receiving_yards", "receptions"}
    assert all(isinstance(r["over_odds"], int) and isinstance(r["under_odds"], int) for r in rows)
    assert len({r["quote_id"] for r in rows}) == len(rows)
    by_book_market = {(r["book_key"], r["market"], r["line"]) for r in rows}
    # Two sharp books on the same market and line: the frozen V3 join.
    assert ("pinnacle", "receiving_yards", 74.5) in by_book_market
    assert ("lowvig", "receiving_yards", 74.5) in by_book_market


def test_workflow_wiring_matches_the_audit_plan():
    wf = (ROOT / ".github" / "workflows" / "odds_freshness.yml").read_text(encoding="utf-8")
    assert "cron: '7,22,37,52 * * * *'" in wf  # 15-min cadence, offset from news ticks
    assert "ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}" in wf
    assert 'run: python scripts/fetch_nfl_props_sweep.py --mode "$SWEEP_MODE"' in wf
    assert "${{ inputs.sweep || 'auto' }}" in wf  # scheduled runs default to auto
    # Order discipline: book #1 refreshes first, the optional sweep can never
    # sit between the freshness gate and publication, and the gate runs last.
    i_pm = wf.index("python scripts/fetch_polymarket_props.py")
    i_sweep = wf.index("python scripts/fetch_nfl_props_sweep.py")
    i_check = wf.index("python scripts/check_odds_freshness.py --max-age-hours")
    assert i_pm < i_sweep < i_check


def test_selftest_entrypoint_passes():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_nfl_props_sweep.py"),
         "--selftest"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert "ALL PASS" in out.stdout, out.stdout + out.stderr
