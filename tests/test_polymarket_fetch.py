"""Offline tests for scripts/fetch_polymarket_props.py (v176).

Covers the parser, American-odds conversion, the model-vs-market evaluation
(normal approximation mirroring the viewer simulator), and the fail-closed
merge semantics — no network access required.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "fetch_polymarket_props", ROOT / "scripts" / "fetch_polymarket_props.py")
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)


def test_parser_maps_supported_stats_and_rejects_the_rest():
    assert pm.parse_market("Puka Nacua: Receiving Yards O/U 74.5") == \
        ("Puka Nacua", "receiving_yards", 74.5)
    assert pm.parse_market("Colston Loveland: Receptions O/U 4.5") == \
        ("Colston Loveland", "receptions", 4.5)
    # v1 scope: passing/rushing/TD markets are skipped, never guessed.
    assert pm.parse_market("Caleb Williams: Passing Yards O/U 249.5") is None
    assert pm.parse_market("Sam Darnold: Rushing Yards O/U 59.5") is None
    assert pm.parse_market("AJ Barner: Anytime Touchdown") is None
    assert pm.parse_market("Bears vs. Seahawks") is None


def test_cents_to_american_matches_market_convention():
    assert pm.cents_to_american(0.55) == -122
    assert pm.cents_to_american(0.45) == 122
    assert pm.cents_to_american(0.5) == -100
    # extremes clamp instead of dividing by ~zero
    assert abs(pm.cents_to_american(0.999)) >= 4000


def test_evaluation_uses_best_side_and_normal_approx():
    row = {"proj_yards": 92.0, "fair_line_yards": 85.0,
           "player_id": "00-0039075", "player_display_name": "Puka Nacua"}
    ev = pm.compute_evaluation(row, "receiving_yards", 74.5,
                               over_p=0.55, under_p=0.45,
                               over_odds=-122, under_odds=122)
    # Model proj (92) well above the line -> OVER side with real edge.
    assert ev["best_side"] == "OVER"
    assert ev["prob_edge"] > 0
    assert ev["expected_return"] > 0
    assert ev["actionable_stake"] == 0.0  # execution gating stays app-side
    assert "normal-approximation" in ev["method"]


def test_evaluation_flips_side_when_market_favors_over():
    row = {"proj_yards": 60.0, "fair_line_yards": 62.0}
    ev = pm.compute_evaluation(row, "receiving_yards", 74.5,
                               over_p=0.55, under_p=0.45,
                               over_odds=-122, under_odds=122)
    assert ev["best_side"] == "UNDER"
    assert ev["prob_edge"] < 0


def test_build_quote_refuses_dead_markets():
    market = {
        "id": "1", "question": "Puka Nacua: Receiving Yards O/U 74.5",
        "outcomes": '["Over","Under"]', "outcomePrices": '["0.5","0.5"]',
        "slug": "x", "liquidityNum": 1.92,
    }
    row = {"player_id": "00-0039075", "player_display_name": "Puka Nacua",
           "proj_yards": 92.0, "fair_line_yards": 85.0}
    # A $2-liquidity 0.5/0.5 book carries no information — never quoted.
    assert pm.build_quote(market, {}, row, "receiving_yards") is None


def test_clob_outcome_orientation_and_depth(monkeypatch):
    market = {"outcomes": '["Under", "Over"]', "clobTokenIds": '["under-id", "over-id"]'}
    assert pm.outcome_token_ids(market) == ("over-id", "under-id")
    monkeypatch.setattr(pm, "_http_json", lambda url: {"asks": [
        {"price": "0.60", "size": "100"}, {"price": "0.55", "size": "20"},
        {"price": "0.55", "size": "30"}]})
    assert pm.fetch_token_book("over-id") == {
        "token_id": "over-id", "ask_price": 0.55, "ask_depth_usd": 27.5}


def test_clob_books_are_batched_and_keyed_by_returned_asset_id(monkeypatch):
    calls = []

    def batch(url, payload):
        calls.append((url, payload))
        return [{"asset_id": item["token_id"], "asks": [{"price": "0.4", "size": "100"}]}
                for item in reversed(payload)]

    monkeypatch.setattr(pm, "_http_post_json", batch)
    books = pm.fetch_token_books(["a", "b", "c"], batch_size=2)
    assert len(calls) == 2
    assert all(len(payload) <= 2 for _, payload in calls)
    assert set(books) == {"a", "b", "c"}
    assert books["a"]["ask_depth_usd"] == 40.0


def test_clob_batch_rejects_unrequested_book(monkeypatch):
    monkeypatch.setattr(pm, "_http_post_json", lambda _url, _payload: [
        {"asset_id": "wrong", "asks": [{"price": "0.4", "size": "100"}]}
    ])
    with pytest.raises(ValueError, match="unexpected"):
        pm.fetch_token_books(["a"])


def test_merge_feed_is_idempotent_and_fails_closed(tmp_path, monkeypatch):
    feed_path = tmp_path / "live_odds_feed.json"
    feed_path.write_text(json.dumps({
        "feed_status": "UNVERIFIED_MANUAL_ONLY",
        "quotes": [{"quote_id": "syn_a", "book": "Synthetic Book A"}],
        "monitored_books": ["DraftKings"],
    }))
    monkeypatch.setattr(pm, "FEED_PATH", feed_path)
    monkeypatch.setattr(pm, "SLATE_INDEX", tmp_path / "missing.json")

    quote = {
        "quote_id": "pm_x", "book": "Polymarket", "player_id": "00-1",
        "market": "receiving_yards", "line": 74.5, "observed_at": "2026-10-29T12:00:00Z",
        "receipt_id": "pm_x", "content_hash": "a" * 64, "source_url": "https://polymarket.com/market/x",
        "over_odds": -110, "under_odds": 110, "liquidity_usd": 50.0,
        "over_token_id": "over-id", "under_token_id": "under-id",
        "over_ask_price": 0.55, "under_ask_price": 0.45,
        "over_ask_depth_usd": 50.0, "under_ask_depth_usd": 60.0,
        "evaluation": {"best_side": "OVER", "prob_edge": 0.1,
                       "expected_return": 0.2},
    }

    # Empty quote list never touches the file.
    before = feed_path.read_text()
    assert pm.merge_feed([]) is False
    assert feed_path.read_text() == before

    assert pm.merge_feed([dict(quote)])
    data = json.loads(feed_path.read_text())
    assert data["feed_status"] == "LIVE_POLYMARKET_CLOB_UNVERIFIED"
    assert data["verified_books_count"] == 0
    assert data["verified_quotes_count"] == 0
    assert (tmp_path / "live_odds_feed.manifest.json").exists()
    assert "Polymarket" in data["monitored_books"]
    # Synthetic quote preserved; re-merge replaces Polymarket quotes only.
    assert pm.merge_feed([dict(quote)])
    data2 = json.loads(feed_path.read_text())
    pm_n = [q for q in data2["quotes"] if q["book"] == "Polymarket"]
    assert len(pm_n) == 1
    assert any(q["book"] == "Synthetic Book A" for q in data2["quotes"])

    from src.contracts.polymarket import PolymarketMergedFeed
    with pytest.raises(ValueError, match="verified counts"):
        PolymarketMergedFeed.model_validate({**data2, "verified_quotes_count": 1})
    with pytest.raises(ValueError, match="independent verification"):
        PolymarketMergedFeed.model_validate({**data2, "quotes": [
            *[q for q in data2["quotes"] if q["book"] != "Polymarket"],
            {**pm_n[0], "evaluation": {"status": "VERIFIED"}},
        ]})

    # A malformed CLOB observation is quarantined without replacing the feed.
    prior = feed_path.read_bytes()
    assert pm.merge_feed([dict(quote, under_ask_price=1.2)]) is False
    assert feed_path.read_bytes() == prior


def test_selftest_entrypoint_passes():
    import subprocess
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_polymarket_props.py"),
         "--selftest"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert "ALL PASS" in out.stdout, out.stdout + out.stderr


def test_network_failure_leaves_feed_untouched(tmp_path, monkeypatch):
    feed_path = tmp_path / "live_odds_feed.json"
    feed_path.write_text('{"quotes": []}')
    monkeypatch.setattr(pm, "FEED_PATH", feed_path)

    def boom(**kwargs):
        raise OSError("network down")

    monkeypatch.setattr(pm, "fetch_events", boom)
    monkeypatch.setattr(sys, "argv", ["fetch_polymarket_props.py"])
    before = feed_path.read_bytes()
    assert pm.main() == 0
    assert feed_path.read_bytes() == before


def test_published_polymarket_snapshot_does_not_claim_verified_prices():
    feed = json.loads((ROOT / "viewer" / "live_odds_feed.json").read_text())
    polymarket = [q for q in feed["quotes"] if q.get("book") == "Polymarket"]
    assert feed["feed_status"] == "LIVE_POLYMARKET_CLOB_UNVERIFIED"
    assert feed["polymarket_quotes_count"] == len(polymarket)
    assert feed["verified_quotes_count"] == feed["verified_books_count"] == 0
    assert all(q.get("verified") is not True for q in polymarket)
    assert all((q.get("evaluation") or {}).get("status") != "VERIFIED" for q in polymarket)
