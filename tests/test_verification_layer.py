"""Verification Layer — contract tests for src/contracts/verification.py (verification.v1).

These tests enforce the Phase 2 trust spine: the frozen surface, the
deterministic status assignment, the receipt/staleness/conflict clause
semantics, fail-closed behavior at every boundary, the bridge into quant.v1's
gate, and the API surfaces (POST /api/v1/verify-quote, POST
/api/v1/context-freshness) including the removed demo fallback on
/api/v1/verify-receipt.

If a change to verification.py breaks a test here, the contract was amended —
that requires a written migration plan and a VERIFICATION_CONTRACTS_VERSION
bump, not a test tweak.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from src.contracts.quant import (
    LOCKING_STATUSES,
    GateVerdict,
    VerificationStatus,
    build_pricing_output,
)
from src.contracts.verification import (
    VERIFICATION_CLAUSE_IDS,
    VERIFICATION_CONTRACTS_VERSION,
    ConflictSnapshot,
    ContextFeedKind,
    ContextFreshness,
    ContextFreshnessConfig,
    PeerQuote,
    QuoteObservation,
    ReceiptRecord,
    VerificationConfig,
    VerificationDecision,
    evaluate_context_freshness,
    staleness_limit_minutes,
    to_provenance,
    verify_quote,
)

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
KICKOFF = NOW + timedelta(hours=3)          # 180 minutes to kickoff
NEAR_KICKOFF = NOW + timedelta(minutes=20)  # inside the 30-minute window
IN_GAME_KICKOFF = NOW - timedelta(minutes=5)  # game already started

HASH_A = hashlib.sha256(b"raw-payload-a").hexdigest()
HASH_B = hashlib.sha256(b"raw-payload-b").hexdigest()
MARKET = "player_reception_yds:player-123:over:3.5"
OTHER_MARKET = "player_receptions:player-456:over:1.5"


def observation(
    *,
    book: str = "draftkings",
    fetched_minutes_ago: float = 10.0,
    payload_hash: str = HASH_A,
    market: str = MARKET,
    over_odds: int = -110,
    under_odds: int | None = -110,
    side: str = "over",
) -> QuoteObservation:
    return QuoteObservation(
        source="the-odds-api",
        book_id=book,
        market_id=market,
        fetched_at=NOW - timedelta(minutes=fetched_minutes_ago),
        raw_payload_hash=payload_hash,
        side=side,
        over_odds=over_odds,
        under_odds=under_odds,
        book_line=34.5,
    )


def receipt(
    *,
    receipt_id: str = "receipt-001",
    payload_hash: str = HASH_A,
    market: str = MARKET,
    book: str = "draftkings",
    captured_minutes_ago: float = 9.0,
) -> ReceiptRecord:
    return ReceiptRecord(
        receipt_id=receipt_id,
        market_id=market,
        book_id=book,
        raw_payload_hash=payload_hash,
        captured_at=NOW - timedelta(minutes=captured_minutes_ago),
    )


def peer(
    *,
    book: str,
    no_vig_prob: float,
    fetched_minutes_ago: float = 8.0,
    market: str = MARKET,
) -> PeerQuote:
    return PeerQuote(
        book_id=book,
        market_id=market,
        no_vig_prob=no_vig_prob,
        fetched_at=NOW - timedelta(minutes=fetched_minutes_ago),
    )


#: Two sharp books in agreement (~1pp apart) — the happy-path peer set.
AGREEING_SHARPS = [
    peer(book="pinnacle", no_vig_prob=0.55),
    peer(book="betonlineag", no_vig_prob=0.56),
]


def decide(
    *,
    obs: QuoteObservation | None = None,
    receipts: list[ReceiptRecord] | None = None,
    peers: list[PeerQuote] | None = None,
    kickoff: datetime | None = KICKOFF,
    config: VerificationConfig | None = None,
    now: datetime = NOW,
) -> VerificationDecision:
    return verify_quote(
        observation=obs or observation(),
        now=now,
        kickoff=kickoff,
        config=config,
        receipts=[receipt()] if receipts is None else receipts,
        peers=AGREEING_SHARPS if peers is None else peers,
    )


# ---------------------------------------------------------------------------
# 1. The frozen surface
# ---------------------------------------------------------------------------

class TestContractSurfaceFrozen:
    def test_contracts_version(self):
        assert VERIFICATION_CONTRACTS_VERSION == "verification.v1"

    def test_field_surfaces_are_exactly_as_frozen(self):
        assert set(VerificationConfig.model_fields) == {
            "sharp_books", "min_sharp_books", "conflict_divergence_pct",
            "staleness_pregame_minutes", "staleness_near_kickoff_minutes",
            "staleness_in_game_minutes", "near_kickoff_window_minutes",
        }
        assert set(QuoteObservation.model_fields) == {
            "source", "book_id", "market_id", "fetched_at",
            "raw_payload_hash", "side", "over_odds", "under_odds", "book_line",
        }
        assert set(ReceiptRecord.model_fields) == {
            "receipt_id", "market_id", "book_id", "raw_payload_hash", "captured_at",
        }
        assert set(PeerQuote.model_fields) == {
            "book_id", "market_id", "no_vig_prob", "fetched_at",
        }
        assert set(ConflictSnapshot.model_fields) == {
            "books", "no_vig_probs", "spread_pct", "excluded_stale", "included_self",
        }
        assert set(VerificationDecision.model_fields) == {
            "status", "receipt_id", "clauses", "conflict", "config_snapshot",
        }
        assert set(ContextFreshness.model_fields) == {
            "kind", "age_minutes", "threshold_minutes", "is_fresh", "fail_closed",
        }
        assert set(ContextFreshnessConfig.model_fields) == {
            "injury_max_age_minutes", "lineup_max_age_minutes", "news_max_age_minutes",
        }

    def test_clause_id_set_is_frozen(self):
        assert VERIFICATION_CLAUSE_IDS == {"V1_receipt", "V2_staleness", "V3_conflict"}
        decision = decide()
        assert {c.clause_id for c in decision.clauses} == set(VERIFICATION_CLAUSE_IDS)

    def test_default_config_mirrors_frozen_constants(self):
        cfg = VerificationConfig()
        assert cfg.sharp_books == ["pinnacle", "betonlineag", "lowvig", "circasports"]  # mirrors src/odds.py SHARP_BOOKS
        assert cfg.staleness_pregame_minutes == 90.0     # matches quant.v1 GateConfig
        assert cfg.staleness_near_kickoff_minutes == 15.0
        assert cfg.conflict_divergence_pct == 5.0

    def test_config_rejects_inverted_staleness_tiers(self):
        with pytest.raises(Exception):
            VerificationConfig(staleness_near_kickoff_minutes=120.0)
        with pytest.raises(Exception):
            VerificationConfig(staleness_in_game_minutes=30.0)

    def test_config_requires_at_least_two_sharp_books_for_conflict(self):
        with pytest.raises(Exception):
            VerificationConfig(min_sharp_books=1)

    def test_decision_rejects_foreign_clause_sets(self):
        from src.contracts.quant import GateClause

        with pytest.raises(Exception):
            VerificationDecision(
                status=VerificationStatus.VERIFIED,
                receipt_id="r",
                clauses=[
                    GateClause(clause_id="X_custom", description="x", operator="==",
                               actual=1, threshold=1, passed=True),
                    GateClause(clause_id="Y_custom", description="y", operator="==",
                               actual=1, threshold=1, passed=True),
                    GateClause(clause_id="Z_custom", description="z", operator="==",
                               actual=1, threshold=1, passed=True),
                ],
                config_snapshot={},
            )


# ---------------------------------------------------------------------------
# 2. Receipt validation (V1)
# ---------------------------------------------------------------------------

class TestReceiptValidation:
    def test_matching_receipt_yields_verified(self):
        d = decide()
        assert d.status == VerificationStatus.VERIFIED
        assert d.receipt_id == "receipt-001"
        assert d.reasoning()[0] == "V1_receipt: receipt_found == receipt_found -> PASS"

    def test_no_receipts_supplied_is_observed(self):
        d = decide(receipts=[])
        assert d.status == VerificationStatus.OBSERVED
        assert d.receipt_id is None
        assert "receipt_missing" in d.reasoning()[0]

    def test_hash_mismatch_is_observed(self):
        d = decide(receipts=[receipt(payload_hash=HASH_B)])
        assert d.status == VerificationStatus.OBSERVED
        assert d.receipt_id is None

    def test_receipt_for_other_market_is_not_evidence(self):
        d = decide(receipts=[receipt(market=OTHER_MARKET)])
        assert d.status == VerificationStatus.OBSERVED

    def test_receipt_for_other_book_is_not_evidence(self):
        d = decide(receipts=[receipt(book="fanduel")])
        assert d.status == VerificationStatus.OBSERVED

    def test_future_receipt_is_not_evidence_yet(self):
        d = decide(receipts=[receipt(captured_minutes_ago=-5.0)])
        assert d.status == VerificationStatus.OBSERVED
        assert d.receipt_id is None

    def test_most_recent_matching_receipt_wins(self):
        older = receipt(receipt_id="receipt-old", captured_minutes_ago=60.0)
        newer = receipt(receipt_id="receipt-new", captured_minutes_ago=2.0)
        d = decide(receipts=[older, newer])
        assert d.receipt_id == "receipt-new"

    def test_receipt_tie_breaks_on_receipt_id(self):
        a = receipt(receipt_id="aaa")
        b = receipt(receipt_id="bbb")
        d = decide(receipts=[b, a])
        assert d.receipt_id == "bbb"  # deterministic tie-break, order-independent


# ---------------------------------------------------------------------------
# 3. Staleness regime (V2) — time-to-kickoff aware, config-driven
# ---------------------------------------------------------------------------

class TestStalenessRegime:
    def test_staleness_limit_function(self):
        assert staleness_limit_minutes(now=NOW, kickoff=KICKOFF) == 90.0
        assert staleness_limit_minutes(now=NOW, kickoff=NEAR_KICKOFF) == 15.0
        assert staleness_limit_minutes(now=NOW, kickoff=IN_GAME_KICKOFF) == 2.0
        assert staleness_limit_minutes(now=NOW, kickoff=None) == 90.0

    def test_pregame_quote_beyond_90_minutes_is_stale(self):
        d = decide(obs=observation(fetched_minutes_ago=91.0))
        assert d.status == VerificationStatus.STALE
        assert "V2_staleness: 91.0 <= 90.0 -> FAIL" in d.reasoning()

    def test_pregame_quote_at_boundary_is_fresh(self):
        d = decide(obs=observation(fetched_minutes_ago=90.0))
        assert d.status == VerificationStatus.VERIFIED

    def test_near_kickoff_regime_is_tighter(self):
        # 20 minutes old with 20 minutes to kickoff: limit is 15, not 90.
        d = decide(obs=observation(fetched_minutes_ago=20.0), kickoff=NEAR_KICKOFF)
        assert d.status == VerificationStatus.STALE

    def test_in_game_regime_is_tightest(self):
        # Peers must be fresh under the in-game regime too (limit 2 min),
        # otherwise the conflict check is uncheckable and masks the assertion.
        fresh_in_game = [
            peer(book="pinnacle", no_vig_prob=0.55, fetched_minutes_ago=1.0),
            peer(book="betonlineag", no_vig_prob=0.56, fetched_minutes_ago=1.0),
        ]
        d = decide(obs=observation(fetched_minutes_ago=3.0), kickoff=IN_GAME_KICKOFF, peers=fresh_in_game)
        assert d.status == VerificationStatus.STALE
        d2 = decide(obs=observation(fetched_minutes_ago=1.0), kickoff=IN_GAME_KICKOFF, peers=fresh_in_game)
        assert d2.status == VerificationStatus.VERIFIED

    def test_staleness_thresholds_are_config_driven(self):
        cfg = VerificationConfig(staleness_pregame_minutes=30.0)
        d = decide(obs=observation(fetched_minutes_ago=45.0), config=cfg)
        assert d.status == VerificationStatus.STALE
        assert d.config_snapshot["staleness_pregame_minutes"] == 30.0

    def test_staleness_dominates_conflict(self):
        # Stale AND sharp books diverging: STALE wins — a stale quote's
        # divergence math describes the past, not the present.
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50),
            peer(book="betonlineag", no_vig_prob=0.62),
        ]
        d = decide(obs=observation(fetched_minutes_ago=120.0), peers=diverging)
        assert d.status == VerificationStatus.STALE

    def test_future_dated_observation_is_rejected_outright(self):
        with pytest.raises(ValueError, match="future"):
            verify_quote(
                observation=observation(fetched_minutes_ago=-5.0),
                now=NOW, kickoff=KICKOFF, receipts=[receipt()], peers=AGREEING_SHARPS,
            )

    def test_naive_now_is_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            verify_quote(
                observation=observation(),
                now=NOW.replace(tzinfo=None),  # type: ignore[arg-type]
                kickoff=KICKOFF, receipts=[receipt()], peers=AGREEING_SHARPS,
            )


# ---------------------------------------------------------------------------
# 4. Sharp-book divergence (V3)
# ---------------------------------------------------------------------------

class TestConflictDetection:
    def test_agreeing_sharps_yield_verified(self):
        d = decide()
        v3 = [c for c in d.clauses if c.clause_id == "V3_conflict"][0]
        assert v3.passed is True
        assert v3.actual == pytest.approx(1.0)  # 55% vs 56% -> 1.0pp spread

    def test_diverging_sharps_yield_conflict(self):
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50),
            peer(book="betonlineag", no_vig_prob=0.62),
        ]
        d = decide(peers=diverging)
        assert d.status == VerificationStatus.CONFLICT
        assert d.conflict is not None
        assert d.conflict.spread_pct == pytest.approx(12.0)
        assert d.conflict.books == ["betonlineag", "pinnacle"]  # sorted

    def test_conflict_snapshot_carries_the_evidence(self):
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50),
            peer(book="betonlineag", no_vig_prob=0.58),
        ]
        d = decide(peers=diverging)
        assert d.conflict is not None
        assert d.conflict.no_vig_probs == [0.58, 0.50]  # aligned with sorted books
        assert 0.50 <= min(d.conflict.no_vig_probs) and max(d.conflict.no_vig_probs) <= 0.58

    def test_boundary_spread_exactly_at_threshold_passes(self):
        exactly = [
            peer(book="pinnacle", no_vig_prob=0.525),
            peer(book="betonlineag", no_vig_prob=0.575),
        ]
        d = decide(peers=exactly)
        assert d.status == VerificationStatus.VERIFIED  # 5.0pp <= 5.0pp

    def test_recreational_divergence_is_ignored(self):
        # Recreational books diverging wildly must NOT trip CONFLICT, but with
        # no sharp quotes the check is uncheckable -> OBSERVED, never VERIFIED.
        recreational = [
            peer(book="draftkings", no_vig_prob=0.40),
            peer(book="fanduel", no_vig_prob=0.70),
        ]
        d = decide(peers=recreational)
        assert d.status == VerificationStatus.OBSERVED
        v3 = [c for c in d.clauses if c.clause_id == "V3_conflict"][0]
        assert v3.passed is False
        assert v3.actual is None  # UNKNOWN, not zero

    def test_single_sharp_peer_cannot_certify_no_conflict(self):
        d = decide(peers=[peer(book="pinnacle", no_vig_prob=0.55)])
        assert d.status == VerificationStatus.OBSERVED
        v3 = [c for c in d.clauses if c.clause_id == "V3_conflict"][0]
        assert v3.passed is False
        assert v3.actual is None

    def test_stale_sharp_peer_is_excluded_and_counted(self):
        peers = [
            peer(book="pinnacle", no_vig_prob=0.55, fetched_minutes_ago=200.0),  # stale
            peer(book="betonlineag", no_vig_prob=0.56),
        ]
        d = decide(peers=peers)
        assert d.status == VerificationStatus.OBSERVED  # only 1 usable sharp
        assert d.conflict is not None
        assert d.conflict.excluded_stale == 1

    def test_future_dated_peer_is_excluded(self):
        peers = [
            peer(book="pinnacle", no_vig_prob=0.55, fetched_minutes_ago=-3.0),
            peer(book="betonlineag", no_vig_prob=0.56),
        ]
        d = decide(peers=peers)
        assert d.status == VerificationStatus.OBSERVED
        assert d.conflict is not None
        assert d.conflict.excluded_stale == 1

    def test_peers_for_other_markets_are_ignored(self):
        peers = [
            peer(book="pinnacle", no_vig_prob=0.55, market=OTHER_MARKET),
            peer(book="betonlineag", no_vig_prob=0.56),
        ]
        d = decide(peers=peers)
        assert d.status == VerificationStatus.OBSERVED
        assert d.conflict is not None
        assert d.conflict.books == ["betonlineag"]

    def test_sharp_observation_joins_its_own_comparison(self):
        # The observed book IS pinnacle (sharp): self + one sharp peer = 2.
        # The receipt must match the observed book, not the default one.
        obs = observation(book="pinnacle", over_odds=-110, under_odds=-110)
        # -110/-110 devigs to 0.5/0.5.
        peers = [peer(book="betonlineag", no_vig_prob=0.51)]
        d = decide(obs=obs, peers=peers, receipts=[receipt(book="pinnacle")])
        assert d.status == VerificationStatus.VERIFIED
        assert d.conflict is not None
        assert d.conflict.included_self is True
        assert d.conflict.books == ["betonlineag", "pinnacle"]

    def test_one_sided_sharp_observation_cannot_join_comparison(self):
        obs = observation(book="pinnacle", under_odds=None)
        peers = [peer(book="betonlineag", no_vig_prob=0.51)]
        d = decide(obs=obs, peers=peers)
        assert d.status == VerificationStatus.OBSERVED
        assert d.conflict is not None
        assert d.conflict.included_self is False

    def test_under_side_observation_devigs_correctly(self):
        # devig(-110, -110) -> (0.5, 0.5); the under side self-no-vig is 0.5.
        obs = observation(book="pinnacle", side="under")
        peers = [
            peer(book="betonlineag", no_vig_prob=0.505),
            peer(book="lowvig", no_vig_prob=0.495),
        ]
        d = decide(obs=obs, peers=peers, receipts=[receipt(book="pinnacle")])
        assert d.status == VerificationStatus.VERIFIED

    def test_conflict_divergence_threshold_is_config_driven(self):
        cfg = VerificationConfig(conflict_divergence_pct=15.0)
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50),
            peer(book="betonlineag", no_vig_prob=0.62),
        ]
        d = decide(peers=diverging, config=cfg)
        assert d.status == VerificationStatus.VERIFIED  # 12pp <= 15pp now

    def test_no_peers_at_all_leaves_conflict_none_and_observed(self):
        d = decide(peers=[])
        assert d.status == VerificationStatus.OBSERVED
        assert d.conflict is None
        v3 = [c for c in d.clauses if c.clause_id == "V3_conflict"][0]
        assert v3.passed is False


# ---------------------------------------------------------------------------
# 5. Status precedence: STALE > CONFLICT > OBSERVED > VERIFIED
# ---------------------------------------------------------------------------

class TestStatusPrecedence:
    def test_conflict_beats_missing_receipt(self):
        # A measured divergence must surface even when the receipt is missing.
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50),
            peer(book="betonlineag", no_vig_prob=0.62),
        ]
        d = decide(receipts=[], peers=diverging)
        assert d.status == VerificationStatus.CONFLICT

    def test_stale_beats_conflict(self):
        diverging = [
            peer(book="pinnacle", no_vig_prob=0.50, fetched_minutes_ago=8.0),
            peer(book="betonlineag", no_vig_prob=0.62, fetched_minutes_ago=8.0),
        ]
        d = decide(obs=observation(fetched_minutes_ago=200.0), peers=diverging)
        assert d.status == VerificationStatus.STALE

    def test_receipt_missing_with_uncheckable_conflict_is_observed(self):
        d = decide(receipts=[], peers=[])
        assert d.status == VerificationStatus.OBSERVED

    def test_all_clauses_pass_is_verified(self):
        d = decide()
        assert d.status == VerificationStatus.VERIFIED
        assert all(c.passed for c in d.clauses)
        assert d.receipt_id is not None


# ---------------------------------------------------------------------------
# 6. Determinism and purity
# ---------------------------------------------------------------------------

class TestDeterminismAndPurity:
    def test_same_inputs_byte_identical(self):
        for _ in range(3):
            a = decide()
            b = decide()
            assert a.model_dump_json() == b.model_dump_json()

    def test_peer_order_permutation_invariance(self):
        peers = [
            peer(book="pinnacle", no_vig_prob=0.55),
            peer(book="betonlineag", no_vig_prob=0.56),
            peer(book="lowvig", no_vig_prob=0.54),
        ]
        d1 = decide(peers=peers)
        d2 = decide(peers=list(reversed(peers)))
        assert d1.model_dump_json() == d2.model_dump_json()

    def test_receipt_order_permutation_invariance(self):
        receipts = [
            receipt(receipt_id="aaa", captured_minutes_ago=60.0),
            receipt(receipt_id="bbb", captured_minutes_ago=2.0),
        ]
        d1 = decide(receipts=receipts)
        d2 = decide(receipts=list(reversed(receipts)))
        assert d1.model_dump_json() == d2.model_dump_json()

    def test_verify_quote_source_has_no_io_or_clock(self):
        import inspect

        from src.contracts import verification as mod

        src = inspect.getsource(mod.verify_quote)
        # Call-shaped patterns only — the docstring legitimately says "no
        # randomness", which contains the substring "random".
        for banned in (
            "open(", "requests.", "urllib", "httpx", "datetime.now",
            "random.", "uuid.", "subprocess", "time.time",
        ):
            assert banned not in src, f"verify_quote() must not touch {banned}"

    def test_config_snapshot_is_serializable_and_complete(self):
        d = decide()
        snap = json.loads(json.dumps(d.config_snapshot))
        assert set(snap) == set(VerificationConfig.model_fields)


# ---------------------------------------------------------------------------
# 7. Fail-closed integration with the quant.v1 gate
# ---------------------------------------------------------------------------

class TestGateIntegration:
    def test_locking_statuses_never_unlock_action(self):
        # Strong edge numbers: 62% fair vs 50% market at -110 -> edge 12pp.
        # If action is still locked, the lock is driven by verification.
        obs = observation()
        for status in LOCKING_STATUSES:
            prov = to_provenance(_raw_decision(status), obs)
            out = build_pricing_output(
                fair_prob=0.62, market_prob=0.50, odds=-110,
                provenance=prov, model_version="test",
                news_age_minutes=10.0,
            )
            assert out.gate.action_locked is True, f"{status} must lock action"
            assert out.gate.verdict == GateVerdict.RED

    def test_verified_with_strong_edge_unlocks(self):
        d = decide()
        prov = to_provenance(d, observation())
        out = build_pricing_output(
            fair_prob=0.62, market_prob=0.50, odds=-110,
            provenance=prov, model_version="test",
            news_age_minutes=10.0,
        )
        assert out.gate.verdict == GateVerdict.GREEN
        assert out.gate.action_locked is False
        assert out.kelly_fraction > 0

    def test_to_provenance_carries_the_full_spine(self):
        d = decide()
        obs = observation()
        prov = to_provenance(d, obs, source_url="https://api.example/v4")
        assert prov.source == obs.source
        assert prov.book_id == obs.book_id
        assert prov.fetched_at == obs.fetched_at
        assert prov.raw_payload_hash == obs.raw_payload_hash
        assert prov.market_id == obs.market_id
        assert prov.receipt_id == d.receipt_id
        assert prov.verification_status == d.status
        assert prov.book_odds == obs.over_odds
        assert prov.source_url == "https://api.example/v4"


def _raw_decision(status: VerificationStatus) -> VerificationDecision:
    """Build a minimal-but-valid VerificationDecision with the given status,
    bypassing verify_quote() to exercise the gate lock directly."""
    from src.contracts.quant import GateClause

    passed = status == VerificationStatus.VERIFIED
    clauses = [
        GateClause(clause_id="V1_receipt", description="receipt log match for (market, book, payload hash)",
                   operator="==", actual="receipt_found" if passed else "receipt_missing",
                   threshold="receipt_found", passed=passed),
        GateClause(clause_id="V2_staleness", description="quote age vs staleness limit (minutes)",
                   operator="<=", actual=10.0, threshold=90.0, passed=passed),
        GateClause(clause_id="V3_conflict", description="sharp-book no-vig divergence (percentage points)",
                   operator="<=", actual=1.0 if passed else None, threshold=5.0, passed=passed),
    ]
    return VerificationDecision(
        status=status,
        receipt_id="r" if passed else None,
        clauses=clauses,
        conflict=ConflictSnapshot(books=["betonlineag", "pinnacle"], no_vig_probs=[0.55, 0.56],
                                  spread_pct=1.0, excluded_stale=0, included_self=False),
        config_snapshot=VerificationConfig().model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 8. Context freshness — injuries / news / lineups are first-class
# ---------------------------------------------------------------------------

class TestContextFreshness:
    def test_fresh_feeds(self):
        for kind, age in ((ContextFeedKind.INJURY, 30.0), (ContextFeedKind.LINEUP, 20.0),
                          (ContextFeedKind.NEWS, 40.0)):
            cf = evaluate_context_freshness(
                kind=kind, last_checked_at=NOW - timedelta(minutes=age), now=NOW,
            )
            assert cf.is_fresh is True
            assert cf.fail_closed is False
            assert cf.age_minutes == age

    def test_stale_feeds(self):
        cf = evaluate_context_freshness(
            kind=ContextFeedKind.NEWS,
            last_checked_at=NOW - timedelta(minutes=46.0), now=NOW,
        )
        assert cf.is_fresh is False
        assert cf.fail_closed is False

    def test_unknown_last_check_fails_closed(self):
        cf = evaluate_context_freshness(kind=ContextFeedKind.INJURY, last_checked_at=None, now=NOW)
        assert cf.is_fresh is False
        assert cf.fail_closed is True
        assert cf.age_minutes is None

    def test_future_last_check_fails_closed(self):
        cf = evaluate_context_freshness(
            kind=ContextFeedKind.LINEUP,
            last_checked_at=NOW + timedelta(minutes=5), now=NOW,
        )
        assert cf.is_fresh is False
        assert cf.fail_closed is True
        assert cf.age_minutes is None

    def test_per_kind_thresholds(self):
        cfg = ContextFreshnessConfig()
        fresh_at_40 = evaluate_context_freshness(
            kind=ContextFeedKind.LINEUP, last_checked_at=NOW - timedelta(minutes=40), now=NOW,
        )
        assert fresh_at_40.threshold_minutes == cfg.lineup_max_age_minutes
        assert fresh_at_40.is_fresh is False  # 40 > 30

    def test_thresholds_config_driven(self):
        cfg = ContextFreshnessConfig(news_max_age_minutes=15.0)
        cf = evaluate_context_freshness(
            kind=ContextFeedKind.NEWS,
            last_checked_at=NOW - timedelta(minutes=20), now=NOW, config=cfg,
        )
        assert cf.is_fresh is False

    def test_news_threshold_matches_gate_config(self):
        # The terminal freshness panel and the gate's C6 clause must agree.
        from src.contracts.quant import GateConfig

        assert ContextFreshnessConfig().news_max_age_minutes == GateConfig().news_max_age_minutes


# ---------------------------------------------------------------------------
# 9. API surface: POST /api/v1/verify-quote and POST /api/v1/context-freshness
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from api.main import app

    return TestClient(app)


def api_body(**overrides) -> dict:
    body = {
        "observation": {
            "source": "the-odds-api",
            "book_id": "draftkings",
            "market_id": MARKET,
            "fetched_at": (NOW - timedelta(minutes=10)).isoformat(),
            "raw_payload_hash": HASH_A,
            "over_odds": -110,
            "under_odds": -110,
            "book_line": 34.5,
        },
        "receipts": [{
            "receipt_id": "receipt-001",
            "market_id": MARKET,
            "book_id": "draftkings",
            "raw_payload_hash": HASH_A,
            "captured_at": (NOW - timedelta(minutes=9)).isoformat(),
        }],
        "peers": [
            {"book_id": "pinnacle", "market_id": MARKET, "no_vig_prob": 0.55,
             "fetched_at": (NOW - timedelta(minutes=8)).isoformat()},
            {"book_id": "betonlineag", "market_id": MARKET, "no_vig_prob": 0.56,
             "fetched_at": (NOW - timedelta(minutes=7)).isoformat()},
        ],
        "now": NOW.isoformat(),
        "kickoff": KICKOFF.isoformat(),
    }
    body.update(overrides)
    return body


class TestVerifyQuoteAPI:
    def test_happy_path_returns_full_decision(self, client):
        r = client.post("/api/v1/verify-quote", json=api_body())
        assert r.status_code == 200
        payload = r.json()
        assert payload["contracts_version"] == "verification.v1"
        assert payload["decision"]["status"] == "VERIFIED"
        assert payload["decision"]["receipt_id"] == "receipt-001"
        clause_ids = {c["clause_id"] for c in payload["decision"]["clauses"]}
        assert clause_ids == set(VERIFICATION_CLAUSE_IDS)
        assert payload["decision"]["conflict"]["books"] == ["betonlineag", "pinnacle"]

    def test_deterministic_with_pinned_now(self, client):
        r1 = client.post("/api/v1/verify-quote", json=api_body())
        r2 = client.post("/api/v1/verify-quote", json=api_body())
        assert r1.json()["decision"] == r2.json()["decision"]

    def test_config_override_round_trips(self, client):
        body = api_body(config={
            "staleness_pregame_minutes": 5.0,
            "staleness_near_kickoff_minutes": 5.0,
            "staleness_in_game_minutes": 1.0,
        })
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 200
        assert r.json()["decision"]["status"] == "STALE"  # 10min old vs 5min limit

    def test_no_receipts_returns_observed_not_error(self, client):
        r = client.post("/api/v1/verify-quote", json=api_body(receipts=[]))
        assert r.status_code == 200
        assert r.json()["decision"]["status"] == "OBSERVED"
        assert r.json()["decision"]["receipt_id"] is None

    def test_future_observation_rejected_422(self, client):
        body = api_body()
        body["observation"]["fetched_at"] = (NOW + timedelta(minutes=5)).isoformat()
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 422
        assert "verification rejected the input" in r.json()["detail"]

    def test_naive_datetime_rejected_422(self, client):
        body = api_body()
        body["observation"]["fetched_at"] = "2026-11-02T17:50:00"
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 422

    def test_malformed_hash_rejected_422(self, client):
        body = api_body()
        body["observation"]["raw_payload_hash"] = "not-a-hash"
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 422

    def test_missing_observation_rejected_422(self, client):
        r = client.post("/api/v1/verify-quote", json={"receipts": []})
        assert r.status_code == 422

    def test_invalid_odds_rejected_422(self, client):
        body = api_body()
        body["observation"]["over_odds"] = -50
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 422

    def test_request_id_header_honored(self, client):
        r = client.post(
            "/api/v1/verify-quote", json=api_body(), headers={"X-Request-ID": "verify-test-001"},
        )
        assert r.headers.get("x-request-id") == "verify-test-001"

    def test_conflict_case_surfaces_snapshot(self, client):
        body = api_body()
        body["peers"][1]["no_vig_prob"] = 0.68
        r = client.post("/api/v1/verify-quote", json=body)
        assert r.status_code == 200
        decision = r.json()["decision"]
        assert decision["status"] == "CONFLICT"
        assert decision["conflict"]["spread_pct"] == pytest.approx(13.0)


class TestContextFreshnessAPI:
    def test_fresh_news(self, client):
        r = client.post("/api/v1/context-freshness", json={
            "kind": "news",
            "last_checked_at": (NOW - timedelta(minutes=10)).isoformat(),
            "now": NOW.isoformat(),
        })
        assert r.status_code == 200
        assert r.json()["freshness"]["is_fresh"] is True

    def test_unknown_last_check_fails_closed(self, client):
        r = client.post("/api/v1/context-freshness", json={
            "kind": "injury", "last_checked_at": None, "now": NOW.isoformat(),
        })
        assert r.status_code == 200
        f = r.json()["freshness"]
        assert f["is_fresh"] is False and f["fail_closed"] is True

    def test_invalid_kind_rejected_422(self, client):
        r = client.post("/api/v1/context-freshness", json={"kind": "weather"})
        assert r.status_code == 422

    def test_naive_now_rejected_422(self, client):
        r = client.post("/api/v1/context-freshness", json={
            "kind": "news", "last_checked_at": None, "now": "2026-11-02T18:00:00",
        })
        assert r.status_code == 422


class TestVerifyReceiptFailClosed:
    """Phase 2 removed the demo fallback that fabricated a
    'CRYPTOGRAPHICALLY_PROVEN' lifecycle for any unknown hash."""

    def test_unknown_hash_is_404_with_honest_body(self, client):
        r = client.post("/api/v1/verify-receipt", json={"receipt_hash": "f" * 16})
        assert r.status_code == 404
        body = r.json()
        assert "not found" in body["detail"].lower()
        assert "Tucker Kraft" not in json.dumps(body)  # no demo record
        assert "CRYPTOGRAPHICALLY_PROVEN" not in json.dumps(body)

    def test_missing_hash_is_400(self, client):
        r = client.post("/api/v1/verify-receipt", json={})
        assert r.status_code == 400

    def test_garbage_hash_is_404_not_fabricated(self, client):
        r = client.post("/api/v1/verify-receipt", json={"receipt_hash": "zzzz-not-a-receipt"})
        assert r.status_code == 404
        assert "Tucker Kraft" not in r.text

    def test_legacy_receipt_requires_original_commitments(self, client, monkeypatch, tmp_path):
        from api import main

        receipt = "8e038b2029e5b60d"
        report = tmp_path / "report.json"
        report.write_text(json.dumps({
            "records": [{"settlement_receipt": receipt, "outcome": "WIN"}],
        }), encoding="utf-8")
        monkeypatch.setattr(main, "resolve_file", lambda *_: str(report))

        known = client.post("/api/v1/verify-receipt", json={"receipt_hash": receipt})
        assert known.status_code == 422
        assert "original lifecycle commitments" in known.json()["detail"]
        partial = client.post("/api/v1/verify-receipt", json={"receipt_hash": receipt[:-1]})
        assert partial.status_code == 404

    def test_non_object_body_is_400(self, client):
        response = client.post("/api/v1/verify-receipt", json=["receipt"])
        assert response.status_code == 400
