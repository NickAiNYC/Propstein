"""Foundation Freeze — contract tests for src/contracts/quant.py (quant.v1).

These tests are the enforcement of the freeze: they pin the field surface,
the unit conventions, the fail-closed invariants, and the determinism of
evaluate_gate()/build_pricing_output(). If a change to quant.py breaks any
test here, the contract was amended — that requires a written migration plan
and a CONTRACTS_VERSION bump, not a test tweak.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from src.contracts.quant import (
    CONTRACTS_VERSION,
    ArtifactHeader,
    GateClause,
    GateConfig,
    GateDecision,
    GateVerdict,
    LOCKING_STATUSES,
    PricingOutput,
    QuoteProvenance,
    VerificationStatus,
    artifact_header,
    build_pricing_output,
    evaluate_gate,
    new_run_id,
)
from src.model import american_to_prob, devig_two_way, ev_per_unit, kelly_fraction

T0 = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)


def provenance(
    *,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    market_id: str = "player_reception_yds:player-123:over:3.5",
    book: str = "draftkings",
) -> QuoteProvenance:
    return QuoteProvenance(
        source="the-odds-api",
        book_id=book,
        fetched_at=T0,
        raw_payload_hash=hashlib.sha256(b"raw").hexdigest(),
        verification_status=status,
        market_id=market_id,
        receipt_id="receipt-001" if status == VerificationStatus.VERIFIED else None,
    )


# ---------------------------------------------------------------------------
# 1. The frozen surface
# ---------------------------------------------------------------------------

class TestContractSurfaceFrozen:
    def test_contracts_version(self):
        assert CONTRACTS_VERSION == "quant.v1"

    def test_field_surface_is_exactly_as_frozen(self):
        assert set(QuoteProvenance.model_fields) == {
            "source", "book_id", "fetched_at", "raw_payload_hash",
            "verification_status", "market_id", "receipt_id", "source_url",
            "book_line", "book_odds",
        }
        assert set(PricingOutput.model_fields) == {
            "market_id", "fair_prob", "fair_line", "edge_pct", "ev_per_unit",
            "kelly_fraction", "market_prob", "odds", "provenance", "gate",
            "model_version",
        }
        assert set(GateDecision.model_fields) == {
            "verdict", "action_locked", "clauses", "config_snapshot",
        }
        assert set(GateClause.model_fields) == {
            "clause_id", "description", "operator", "actual", "threshold", "passed",
        }
        assert set(ArtifactHeader.model_fields) == {
            "run_id", "commit_sha", "data_cutoff_timestamp", "model_version",
            "contracts_version", "generator",
        }

    def test_verification_vocabulary_is_closed(self):
        assert {s.value for s in VerificationStatus} == {
            "VERIFIED", "OBSERVED", "STALE", "CONFLICT", "UNVERIFIED",
        }
        assert {v.value for v in GateVerdict} == {"GREEN", "YELLOW", "RED"}

    def test_only_verified_unlocks(self):
        # The trust invariant, stated once, at the vocabulary level.
        assert LOCKING_STATUSES == frozenset(
            {VerificationStatus.OBSERVED, VerificationStatus.STALE,
             VerificationStatus.CONFLICT, VerificationStatus.UNVERIFIED}
        )
        assert VerificationStatus.VERIFIED not in LOCKING_STATUSES

    def test_extra_fields_rejected(self):
        # A closed contract: nothing rides along unnoticed.
        with pytest.raises(Exception):
            QuoteProvenance(
                source="s", book_id="b", fetched_at=T0,
                raw_payload_hash="a" * 64, market_id="m",
                surprise_field="nope",
            )


# ---------------------------------------------------------------------------
# 2. Provenance validation
# ---------------------------------------------------------------------------

class TestQuoteProvenance:
    def test_valid_provenance_round_trips(self):
        p = provenance()
        again = QuoteProvenance.model_validate_json(p.model_dump_json())
        assert again == p

    def test_bad_hash_rejected(self):
        with pytest.raises(Exception):
            QuoteProvenance(
                source="s", book_id="b", fetched_at=T0,
                raw_payload_hash="not-a-sha", market_id="m",
            )

    def test_naive_datetime_rejected(self):
        with pytest.raises(Exception):
            QuoteProvenance(
                source="s", book_id="b",
                fetched_at=datetime(2026, 11, 2, 17, 0),  # naive
                raw_payload_hash="a" * 64, market_id="m",
            )

    def test_verified_without_receipt_rejected(self):
        # The anti-fake-trust rule: verified claims must name their receipt.
        with pytest.raises(Exception):
            QuoteProvenance(
                source="s", book_id="b", fetched_at=T0,
                raw_payload_hash="a" * 64, market_id="m",
                verification_status=VerificationStatus.VERIFIED,
                receipt_id=None,
            )

    def test_default_state_is_unverified(self):
        p = QuoteProvenance(
            source="s", book_id="b", fetched_at=T0,
            raw_payload_hash="a" * 64, market_id="m",
        )
        assert p.verification_status == VerificationStatus.UNVERIFIED


# ---------------------------------------------------------------------------
# 3. The gate — deterministic, full-reasoning, fail-closed
# ---------------------------------------------------------------------------

class TestEvaluateGate:
    def test_green_path_unlocks(self):
        gate = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        assert gate.verdict == GateVerdict.GREEN
        assert gate.action_locked is False
        assert all(c.passed for c in gate.clauses)
        assert len(gate.clauses) == 6  # C1..C6

    @pytest.mark.parametrize("status", sorted(LOCKING_STATUSES, key=lambda s: s.value))
    def test_every_locking_status_locks_even_with_a_huge_edge(self, status):
        # The core fail-closed invariant: no edge, however large, unlocks an
        # unverified quote.
        gate = evaluate_gate(
            fair_prob=0.90, market_prob=0.10, odds=+150,
            provenance=provenance(status=status), news_age_minutes=5.0,
        )
        assert gate.verdict == GateVerdict.RED
        assert gate.action_locked is True
        assert any(not c.passed for c in gate.clauses)

    def test_yellow_is_watch_only(self):
        # Edge above zero, below threshold, everything else clean.
        gate = evaluate_gate(
            fair_prob=0.545, market_prob=0.535, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        assert gate.verdict == GateVerdict.YELLOW
        assert gate.action_locked is True

    def test_stale_news_blocks_green(self):
        gate = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=120.0,  # > 45 default
        )
        assert gate.verdict != GateVerdict.GREEN
        assert gate.action_locked is True
        # And the failed clause says exactly why, with the numbers.
        c6 = [c for c in gate.clauses if c.clause_id == "C6_news"][0]
        assert c6.passed is False
        assert c6.actual == 120.0 and c6.threshold == 45.0

    def test_unknown_news_fails_closed(self):
        gate = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=None,
        )
        assert gate.action_locked is True
        c6 = [c for c in gate.clauses if c.clause_id == "C6_news"][0]
        assert c6.passed is False and c6.actual is None

    def test_negative_edge_is_red(self):
        gate = evaluate_gate(
            fair_prob=0.40, market_prob=0.55, odds=-110,
            provenance=provenance(), news_age_minutes=5.0,
        )
        assert gate.verdict == GateVerdict.RED

    def test_byte_identical_for_identical_inputs(self):
        kwargs = dict(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        a, b = evaluate_gate(**kwargs), evaluate_gate(**kwargs)
        assert a.model_dump_json() == b.model_dump_json()

    def test_gate_carries_no_timestamp_or_run_id(self):
        # Determinism contract: reproducibility lives in (commit_sha,
        # data_cutoff), not inside the decision object.
        gate = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        blob = gate.model_dump_json()
        for absent in ("ts", "timestamp", "now", "created", "run_id"):
            assert absent not in blob

    def test_clause_rendering_shows_exact_numbers(self):
        gate = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        rendered = " | ".join(gate.reasoning())
        assert "C1_edge: 10.0 >= 3.0 -> PASS" in rendered
        assert "C4_verification: VERIFIED == VERIFIED -> PASS" in rendered

    def test_custom_thresholds_are_honored(self):
        # edge_pct here is 100*(0.62-0.52) = 10.0 points.
        # Default threshold 3.0 -> GREEN; raised to 12.0 -> YELLOW (watch only).
        base = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
        )
        assert base.verdict == GateVerdict.GREEN
        raised = evaluate_gate(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), news_age_minutes=10.0,
            config=GateConfig(edge_min_pct=12.0),
        )
        assert raised.verdict == GateVerdict.YELLOW
        assert raised.action_locked is True
        c1 = [c for c in raised.clauses if c.clause_id == "C1_edge"][0]
        assert c1.passed is False and c1.threshold == 12.0

    def test_near_kickoff_tighter_than_pregame_enforced(self):
        with pytest.raises(Exception):
            GateConfig(staleness_near_kickoff_minutes=120.0, staleness_pregame_minutes=90.0)


# ---------------------------------------------------------------------------
# 4. Pricing output — coherence between numbers, gate, and provenance
# ---------------------------------------------------------------------------

class TestPricingOutput:
    def _green_output(self, **over):
        kw = dict(
            fair_prob=0.62, market_prob=0.52, odds=-110,
            provenance=provenance(), model_version="nb-gamma-v1",
            news_age_minutes=10.0,
        )
        kw.update(over)
        return build_pricing_output(**kw)

    def test_build_is_green_and_consistent(self):
        out = self._green_output()
        assert out.gate.verdict == GateVerdict.GREEN
        assert out.gate.action_locked is False
        assert out.edge_pct == pytest.approx(100.0 * (0.62 - 0.52), abs=1e-6)
        assert out.ev_per_unit == pytest.approx(ev_per_unit(0.62, -110), abs=1e-6)
        assert out.kelly_fraction == pytest.approx(kelly_fraction(0.62, -110, cap=0.015), abs=1e-6)

    def test_math_matches_model_module(self):
        # The frozen contract must agree with the production math on the
        # exact same inputs — no reinterpretation.
        p, odds = 0.58, -120
        out = self._green_output(fair_prob=p, odds=odds)
        po, pu = devig_two_way(odds, -odds)  # placeholder sanity: devig sums to 1
        assert po + pu == pytest.approx(1.0)
        assert out.kelly_fraction <= 0.015 + 1e-12
        assert (out.ev_per_unit > 0) == (p > american_to_prob(odds))

    def test_observed_locks_even_when_numbers_are_great(self):
        out = self._green_output(provenance=provenance(status=VerificationStatus.OBSERVED))
        assert out.gate.action_locked is True
        assert out.gate.verdict == GateVerdict.RED

    def test_handbuilt_output_with_unlocked_observed_is_rejected(self):
        # The validators are the backstop: you cannot construct a lie even
        # by bypassing build_pricing_output.
        good = self._green_output()
        with pytest.raises(Exception):
            PricingOutput(
                **{**good.model_dump(), },
                provenance=provenance(status=VerificationStatus.OBSERVED).model_dump(),
                gate=GateDecision(
                    verdict=GateVerdict.GREEN, action_locked=False,
                    clauses=good.gate.clauses, config_snapshot=good.gate.config_snapshot,
                ).model_dump(),
            )

    def test_kelly_on_nonpositive_ev_rejected(self):
        # Start from a REAL red-locked output (fair < market), then corrupt
        # the money fields: kelly > 0 with ev <= 0 must be rejected by the
        # PricingOutput validators themselves.
        red = self._green_output(fair_prob=0.30)  # edge negative -> RED gate
        assert red.gate.verdict == GateVerdict.RED
        payload = red.model_dump()
        payload["ev_per_unit"] = -0.02
        payload["kelly_fraction"] = 0.01
        with pytest.raises(Exception):
            PricingOutput(**payload)

    def test_market_id_mismatch_rejected(self):
        good = self._green_output()
        payload = good.model_dump()
        payload["provenance"]["market_id"] = "some:other:market"
        payload["provenance"]["receipt_id"] = "receipt-001"
        with pytest.raises(Exception):
            PricingOutput(**payload)

    def test_deterministic_round_trip(self):
        out = self._green_output()
        again = PricingOutput.model_validate_json(out.model_dump_json())
        assert again == out


# ---------------------------------------------------------------------------
# 5. Artifact header
# ---------------------------------------------------------------------------

class TestArtifactHeader:
    def test_helper_resolves_real_commit_sha(self):
        h = artifact_header(model_version="nb-gamma-v1", data_cutoff=T0)
        assert h.commit_sha  # resolved from git in this repo
        assert h.contracts_version == CONTRACTS_VERSION
        assert h.run_id.startswith("run_")

    def test_new_run_ids_are_unique(self):
        assert new_run_id() != new_run_id()

    def test_bad_commit_sha_rejected(self):
        with pytest.raises(Exception):
            ArtifactHeader(
                run_id="run_x", commit_sha="zzz-not-sha",
                data_cutoff_timestamp=T0, model_version="v1",
            )

    def test_naive_cutoff_rejected(self):
        with pytest.raises(Exception):
            ArtifactHeader(
                run_id="run_x", commit_sha="a" * 40,
                data_cutoff_timestamp=datetime(2026, 11, 2),  # naive
                model_version="v1",
            )
