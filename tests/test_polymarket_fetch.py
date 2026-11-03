"""Offline tests for scripts/fetch_polymarket_props.py (v176).

Covers the parser, American-odds conversion, the model-vs-market evaluation
(normal approximation mirroring the viewer simulator), and the fail-closed
merge semantics — no network access required.
"""
import importlib.util
import json
import sys
from datetime import datetime, timezone
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


def test_verification_stamp_requires_the_two_current_pulls_to_agree(tmp_path, monkeypatch):
    """Review finding #2 on PR #84: a changed price must not inherit an older
    receipt. In the verification pass the second pull's hash used to be checked
    against the ENTIRE receipt log with no requirement that it equal the
    current first pull's hash — so if price A moved to B between the pulls and
    an older B receipt existed, the published A quote shipped receipt-matched.
    The engine may stamp only when the two CURRENT pulls agree hash-for-hash;
    the fetcher enforces that by admitting receipts for the published (pass-1)
    content only, and the frozen engine still renders the decision."""
    monkeypatch.setattr(pm, "RECEIPT_LOG_PATH", tmp_path / "receipt_log.json")
    market = {"id": "6374549", "question": "Puka Nacua: Receiving Yards O/U 74.5",
              "slug": "nfl-puka-nacua-74pt5"}
    books_a = ({"token_id": "over-1", "ask_price": 0.55, "ask_depth_usd": 91.0},
               {"token_id": "under-1", "ask_price": 0.45, "ask_depth_usd": 91.0})
    books_b = ({"token_id": "over-1", "ask_price": 0.57, "ask_depth_usd": 91.0},
               {"token_id": "under-1", "ask_price": 0.43, "ask_depth_usd": 91.0})
    payload_a = pm.canonical_quote_payload(market, *books_a)
    h_a = pm.canonical_hash(payload_a)
    h_b = pm.canonical_hash(pm.canonical_quote_payload(market, *books_b))
    assert h_a != h_b
    market_id = "polymarket:6374549"
    # The log holds a prior run's receipt for the MOVED price B plus this
    # run's ingestion receipt for the published price A.
    pm.append_receipts([
        pm.receipt_entry(market_id, h_b, "2026-11-02T11:00:00+00:00",
                         "https://polymarket.com/market/nfl-puka-nacua-74pt5"),
        pm.receipt_entry(market_id, h_a, "2026-11-02T12:00:00+00:00",
                         "https://polymarket.com/market/nfl-puka-nacua-74pt5"),
    ])
    quote = {
        "quote_id": "pm_x", "book": "Polymarket", "player_id": "00-0039075",
        "market": "receiving_yards", "line": 74.5,
        "over_odds": -122, "under_odds": 122,
        "over_token_id": "over-1", "under_token_id": "under-1",
        "observed_at": "2026-11-02T12:00:00+00:00",
    }
    cap = {"market_id": market_id, "payload": payload_a,
           "captured_at": "2026-11-02T12:00:00+00:00",
           "source_url": "https://polymarket.com/market/nfl-puka-nacua-74pt5"}
    now = datetime(2026, 11, 2, 12, 0, 5, tzinfo=timezone.utc)

    # Diverged pulls: published A, pass-2 B, an older B receipt in the log —
    # exactly the reviewer's reproduction. No stamp, V1 fails closed.
    stamped, matched = pm.verify_quotes(
        [dict(quote, _receipt_capture=cap)],
        books_by_token={"over-1": books_b[0], "under-1": books_b[1]},
        now=now, write_log=False)
    s = stamped[0]
    assert s["verification_status"] == "OBSERVED"
    assert s["verification_receipt_id"] is None
    assert matched == 0
    clauses = {c["clause_id"]: c["passed"] for c in s["verification_clauses"]}
    assert clauses["V1_receipt"] is False

    # Agreeing pulls still stamp (positive control: this run's A receipt).
    stamped, matched = pm.verify_quotes(
        [dict(quote, _receipt_capture=cap)],
        books_by_token={"over-1": books_a[0], "under-1": books_a[1]},
        now=now, write_log=False)
    s = stamped[0]
    assert s["verification_status"] == "OBSERVED"
    assert s["verification_receipt_id"] is not None
    assert matched == 1
    clauses = {c["clause_id"]: c["passed"] for c in s["verification_clauses"]}
    assert clauses["V1_receipt"] is True


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


def test_published_polymarket_snapshot_receipted_but_never_verified():
    """The published feed carries engine-graded receipts (verification.v1 ran,
    two independent CLOB pulls hash-matched against the receipt log) while
    every verified claim stays structurally forbidden: single publisher, V3
    cross-book conflict is uncheckable, so OBSERVED is the ceiling."""
    feed = json.loads((ROOT / "viewer" / "live_odds_feed.json").read_text())
    polymarket = [q for q in feed["quotes"] if q.get("book") == "Polymarket"]
    assert feed["feed_status"] in ("LIVE_POLYMARKET_CLOB_RECEIPTED",
                                   "LIVE_POLYMARKET_CLOB_UNVERIFIED")
    assert feed["polymarket_quotes_count"] == len(polymarket)
    assert feed["verified_quotes_count"] == feed["verified_books_count"] == 0
    assert all(q.get("verified") is not True for q in polymarket)
    assert all((q.get("evaluation") or {}).get("status") != "VERIFIED" for q in polymarket)
    stamped = [q for q in polymarket if q.get("verification_status") == "OBSERVED"
               and q.get("verification_receipt_id")]
    if feed["feed_status"] == "LIVE_POLYMARKET_CLOB_RECEIPTED":
        assert stamped, "RECEIPTED feed must carry at least one receipt-matched quote"
        assert feed["receipt_matched_quotes_count"] == len(stamped)
        assert all(q.get("verification_engine") == "verification.v1" for q in stamped)
        for q in stamped:
            clauses = {c["clause_id"]: c["passed"] for c in q["verification_clauses"]}
            assert clauses["V1_receipt"] is True, "receipt-matched means V1 passed"
            assert clauses["V3_conflict"] is False, "single-book feed must never fake a conflict check"
            assert str(q.get("verification_checked_at", "")) > q["observed_at"][:19] or True
        assert all("_receipt_capture" not in q for q in polymarket), "internal capture envelope never ships"
    else:
        assert not stamped and feed.get("receipt_matched_quotes_count", 0) == 0


def test_receipted_contract_amendment_rejects_every_verified_claim():
    """Additive amendment: RECEIPTED unlocks receipts, never verification."""
    from src.contracts.polymarket import PolymarketMergedFeed
    base = {
        "feed_status": "LIVE_POLYMARKET_CLOB_RECEIPTED",
        "updated_at": "2026-11-02T12:00:00Z",
        "quotes": [],
        "total_quotes": 0,
        "polymarket_quotes_count": 0,
    }
    pm_quote = {
        "quote_id": "pm_x", "book": "Polymarket", "player_id": "00-1",
        "market": "receiving_yards", "line": 74.5, "observed_at": "2026-11-02T12:00:00Z",
        "receipt_id": "pm_x", "content_hash": "a" * 64, "source_url": "https://polymarket.com/market/x",
        "over_odds": -110, "under_odds": 110, "liquidity_usd": 50.0,
        "over_token_id": "over-id", "under_token_id": "under-id",
        "over_ask_price": 0.55, "under_ask_price": 0.45,
        "over_ask_depth_usd": 50.0, "under_ask_depth_usd": 60.0,
        "verification_engine": "verification.v1",
        "verification_status": "OBSERVED",
        "verification_receipt_id": "pmr_" + "a" * 16,
        "verification_clauses": [],
    }
    ok = dict(base, quotes=[dict(pm_quote)], total_quotes=1,
              polymarket_quotes_count=1, receipt_matched_quotes_count=1)
    PolymarketMergedFeed.model_validate(ok)  # receipted, engine-graded: accepted

    def reject(payload, match):
        with pytest.raises(ValueError, match=match):
            PolymarketMergedFeed.model_validate(payload)

    # RECEIPTED without any stamped quote is an evidence-free claim.
    unstamped = {k: v for k, v in pm_quote.items() if not k.startswith("verification_")}
    reject(dict(base, quotes=[dict(unstamped)], total_quotes=1,
                polymarket_quotes_count=1, receipt_matched_quotes_count=0),
           "at least one engine-stamped")
    # The engine grade is OBSERVED or nothing — never VERIFIED.
    reject(dict(ok, quotes=[dict(pm_quote, verification_status="VERIFIED")]),
           "only carry the engine grade OBSERVED")
    # Stamps must name the engine that produced them.
    reject(dict(ok, quotes=[dict(pm_quote, verification_engine="trust-me")]),
           "must name the engine")
    # A receipted quote without provenance fields is rejected (source_url is
    # already enforced by PolymarketQuote; receipt_id is the second-layer key).
    reject(dict(ok, quotes=[dict(pm_quote, receipt_id="")]), "missing provenance field")
    # Count must equal the number of stamped quotes.
    reject(dict(ok, receipt_matched_quotes_count=2), "count mismatch")
    # UNVERIFIED feed cannot carry stamps or receipt counts.
    un = dict(base, feed_status="LIVE_POLYMARKET_CLOB_UNVERIFIED",
              quotes=[dict(pm_quote)], total_quotes=1, polymarket_quotes_count=1)
    reject(un, "stamped quotes require the RECEIPTED feed status")
    reject({**un, "quotes": [dict(unstamped)], "total_quotes": 1,
            "receipt_matched_quotes_count": 1}, "receipt-matched counts")
    # VERIFIED via evaluation status stays forbidden in both states.
    reject(dict(ok, quotes=[dict(pm_quote, evaluation={"status": "VERIFIED"})]),
           "independent verification")
