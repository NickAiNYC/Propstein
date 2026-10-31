"""
Provenance gates (audit 2026-10 hotfix: provenance-and-demo-ledger).

Locks in the two production-urgent fixes:

  1. SHIPPED DEMO FIXTURES CARRY NO REAL ATTRIBUTION
     - no real sportsbook brand on any quote/ledger row
     - no real player name or real GSIS id in any demo record
     - no "Verified" claim in any demo source string
     - observation timestamps must be distinct (no fabricated
       "independent observations" sharing one microsecond stamp)

  2. THE CLV GRADER IS DEMO-PROOF (fail-closed)
     - clv_report() excludes is_demo / status=="demo" rows before aggregation
     - an all-demo ledger yields an empty grading set (never a fake mean CLV)

These tests scan the committed artifacts, so any future regeneration that
re-leaks real names/books into demo data fails CI here first.

Rebuild note (branch reconstructed after a workspace wipe with unpushed
work): picks_log.jsonl is intentionally UNTRACKED runtime data, so a fresh
CI checkout does not have it. The ledger scan therefore SKIPS (with a
visible reason) when the file is absent instead of erroring — the scan
still runs on every developer machine and in any job that materializes the
ledger.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REAL_BOOKS = [
    "DraftKings", "FanDuel", "BetMGM", "Pinnacle", "Circa",
    "Caesars", "Pointsbet", "Bovada", "ESPN BET",
]
REAL_PLAYERS = [
    "DeMario Douglas", "Hunter Henry", "Mack Hollins", "George Kittle",
    "Christian McCaffrey", "A.J. Brown", "Amon-Ra St. Brown",
    "Ja'Marr Chase", "Chris Olave", "Justin Jefferson",
    "Trey McBride", "Puka Nacua",
]
GSIS_ID = re.compile(r"\b00-00\d{5}\b")
# Word-boundary match: "UNVERIFIED" must stay legal; a standalone "Verified"
# claim in a demo source string must not.
VERIFIED_CLAIM = re.compile(r"\bverified\b", re.IGNORECASE)


def _feed_quote_violations(path: Path):
    """v176 mixed-feed contract: the shipped odds feed either stays a pure
    demo fixture (old rules) or carries REAL Polymarket receipts — in which
    case every real attribution must ride on a fully receipted Polymarket
    quote. Fabricated real-book attribution anywhere else still fails CI."""
    data = json.loads(path.read_text())
    status = str(data.get("feed_status") or data.get("feed_origin") or "")
    pm_quotes = [q for q in data["quotes"] if q.get("book") == "Polymarket"]
    violations = []

    if pm_quotes:
        # Mixed live feed: Polymarket quotes are real observations and MUST
        # carry the full receipt chain; the synthetic baseline stays demo.
        if status != "LIVE_POLYMARKET_CLOB_UNVERIFIED":
            violations.append(f"{path}: mixed feed must self-identify honestly (got {status!r})")
        if data.get("verified_books_count") != 0 or data.get("verified_quotes_count") != 0:
            violations.append(f"{path}: local Polymarket hashes must not count as verified prices")
        for q in pm_quotes:
            missing = [k for k in ("receipt_id", "content_hash", "source_url",
                                   "observed_at", "over_odds", "under_odds",
                                   "liquidity_usd") if not q.get(k)]
            if missing:
                violations.append(f"{path}: {q.get('quote_id')}: Polymarket quote missing {missing}")
            if not str(q.get("source", "")).startswith("https://clob.polymarket.com"):
                violations.append(f"{path}: {q.get('quote_id')}: Polymarket order-book source must be the CLOB API")
            if not str(q.get("source_url", "")).startswith("https://polymarket.com/"):
                violations.append(f"{path}: {q.get('quote_id')}: source_url must point at the tradeable market")
            ev = q.get("evaluation") or {}
            if not {"best_side", "prob_edge", "expected_return"} <= set(ev):
                violations.append(f"{path}: {q.get('quote_id')}: evaluation block incomplete")
            if q.get("verified") is True or str(ev.get("status", "")).upper() == "VERIFIED":
                violations.append(f"{path}: {q.get('quote_id')}: local receipt claims independent verification")
        demo_quotes = [q for q in data["quotes"] if q.get("book") != "Polymarket"]
    else:
        # Pure demo fixture: the original no-real-attribution contract.
        if not (data.get("feed_origin") == "bundled_demonstration_fixture"
                or status == "UNVERIFIED_MANUAL_ONLY"):
            violations.append(f"{path}: demo feed must self-identify as synthetic/unverified")
        if data.get("verified_books_count") != 0:
            violations.append(f"{path}: demo feed must not claim verified books")
        demo_quotes = data["quotes"]

    for q in demo_quotes:
        blob = json.dumps(q)
        for book in REAL_BOOKS + ["Polymarket"]:
            if book in blob:
                violations.append(f"{path}: {q.get('quote_id')}: real book '{book}' on a demo quote")
        for player in REAL_PLAYERS:
            if player in blob:
                violations.append(f"{path}: {q.get('quote_id')}: real player '{player}' on a demo quote")
        if GSIS_ID.search(blob):
            violations.append(f"{path}: {q.get('quote_id')}: real GSIS id on a demo quote")
        if VERIFIED_CLAIM.search(str(q.get("source", ""))):
            violations.append(f"{path}: {q.get('quote_id')}: demo source claims 'verified'")
    return data, violations


def test_demo_feeds_carry_no_real_attribution():
    for rel in ("live_odds_feed.json", "viewer/live_odds_feed.json"):
        _, violations = _feed_quote_violations(ROOT / rel)
        assert violations == [], "\n".join(violations)


def test_demo_feed_timestamps_are_distinct():
    for rel in ("live_odds_feed.json", "viewer/live_odds_feed.json"):
        data = json.loads((ROOT / rel).read_text())
        stamps = [q["observed_at"] for q in data["quotes"]]
        assert len(set(stamps)) == len(stamps), \
            f"{rel}: shared observed_at (fabricated independent observations)"


def test_demo_ledger_is_anonymized():
    ledger = ROOT / "picks_log.jsonl"
    if not ledger.exists():
        # Untracked runtime data on a fresh CI checkout — nothing to scan here.
        import pytest
        pytest.skip("picks_log.jsonl is intentionally untracked (runtime data); "
                    "scan runs wherever the ledger is materialized")
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows, "picks_log.jsonl must not be empty"
    for r in rows:
        assert r.get("is_demo") is True and r.get("status") == "demo"
        assert r["player"] not in REAL_PLAYERS, f"real player leaked into demo ledger: {r['player']}"
        assert r["book"] not in REAL_BOOKS, f"real book leaked into demo ledger: {r['book']}"


def test_clv_report_excludes_demo_rows(tmp_path):
    from agent import clv_report
    ledger = tmp_path / "picks_log.jsonl"
    demo_rows = [
        {"player": "Player H", "book": "Synthetic Book A", "clv": 0.30,
         "is_demo": True, "status": "demo"},
        {"player": "Player I", "book": "Synthetic Book B", "clv": -0.25,
         "is_demo": True, "status": "demo"},
    ]
    real_row = {"player": "Real Player X", "book": "Real Book", "clv": 0.02,
                "is_demo": False, "status": "closed"}
    ledger.write_text("\n".join(json.dumps(r) for r in demo_rows + [real_row]) + "\n")
    report = clv_report(str(ledger))
    assert report["n"] == 1, report
    assert report["excluded_demo"] == 2, report
    assert abs(report["mean_clv"] - 0.02) < 1e-12, report


def test_clv_report_fail_closed_on_all_demo_ledger(tmp_path):
    from agent import clv_report
    ledger = tmp_path / "picks_log.jsonl"
    rows = [{"player": "Player H", "book": "Synthetic Book A", "clv": 0.30,
             "is_demo": True, "status": "demo"}]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    report = clv_report(str(ledger))
    assert report["n"] == 0, report
    assert report["excluded_demo"] == 1, report
    assert report["status"] == "no closing lines recorded yet", report
    assert "mean_clv" not in report, "empty grading set must not emit a mean"
