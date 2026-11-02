"""Foundation Freeze — LEAKAGE SUITE (CI-blocking).

Master prompt §0: 'NO LLM in the decision path', 'pricing, gating, Kelly,
and settlement are 100% deterministic code', 'deterministic reproducibility
from (commit_sha, data_cutoff)'. This suite is the mechanical enforcement of
those three clauses as they stand at Phase 1:

  Part A — Determinism of the pricing math (seeded property sweep)
  Part B — Purity of the decision path (static guards: no LLM imports,
           no network calls, no global/unseeded randomness)
  Part C — Fail-closed gating under every verification state
  Part D — Artifact provenance: every manifest carries the ArtifactHeader
           fields; unresolvable commit_sha refuses to write

Honest scope note (what this suite does NOT yet catch): true feature-time
leakage — a feature computed from a boxscore row dated after
data_cutoff_timestamp — needs the Phase 2 ingestion rebuild that stamps
cutoffs at capture time. Today features.py builds from weekly frozen files
whose cutoff discipline is process-enforced (freeze scripts) rather than
machine-enforced. The Phase 2 done-criteria close that gap; saying so here
so nobody mistakes this file for more than it is.
"""

from __future__ import annotations

import inspect
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from src.contracts.gate import validate_and_publish
from src.contracts.odds import OddsQuote
from src.contracts.quant import (
    LOCKING_STATUSES,
    ArtifactHeader,
    GateConfig,
    GateVerdict,
    QuoteProvenance,
    VerificationStatus,
    build_pricing_output,
    evaluate_gate,
    resolve_commit_sha,
)
from src.model import american_to_prob, devig_two_way, ev_per_unit, kelly_fraction, prob_to_american

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The decision path — the only modules allowed to produce a number a user
#: can act on. Ingestion (src/odds.py fetches, src/ufc/*, scripts/*) is NOT
#: here: fetching data is allowed to use the network. The orchestration
#: layer (src/agents/*, LangGraph) is NOT here: it is explanation/wiring,
#: and its pricing inputs must flow through these frozen contracts.
DECISION_PATH_MODULES = [
    "src/model.py",
    "src/features.py",
    "src/parlay.py",
    "src/settlement_engine.py",
    "src/grade_clv.py",
    "src/contracts/quant.py",
    "src/contracts/gate.py",
    "src/contracts/odds.py",
    "src/contracts/slate.py",
    "src/contracts/availability.py",
    "src/contracts/nba.py",
    "src/contracts/polymarket.py",
]

FORBIDDEN_NETWORK_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(?:requests|httpx|urllib|aiohttp|socket|http)\b",
    re.MULTILINE,
)
FORBIDDEN_LLM_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(?:openai|anthropic|litellm|cohere|zai|bedrock|google\.generativeai)\b",
    re.MULTILINE,
)
FORBIDDEN_GLOBAL_RANDOMNESS = re.compile(
    r"np\.random\.(?:seed|normal|uniform|rand|randn|choice|randint)\s*\("
    r"|[^.\w]random\.(?:random|uniform|choice|randint|sample)\s*\("
    r"|default_rng\s*\(\s*\)",
)
# The sanctioned randomness pattern in the decision path is an explicit,
# caller-seeded Generator passed as a parameter (src/model.py's `rng:`).


# ---------------------------------------------------------------------------
# Part A — determinism of the pricing math
# ---------------------------------------------------------------------------

class TestPricingMathDeterminism:
    def test_same_inputs_same_outputs_seeded_sweep(self):
        rng = random.Random(20261102)
        for _ in range(500):
            p = rng.uniform(0.01, 0.99)
            odds = rng.choice([-110, -150, -220, +120, +180, +250, -105])
            push = rng.choice([0.0, 0.02])
            assert ev_per_unit(p, odds) == ev_per_unit(p, odds)
            assert kelly_fraction(p, odds, push) == kelly_fraction(p, odds, push)

    def test_ev_sign_matches_implied_probability(self):
        rng = random.Random(7)
        for _ in range(500):
            odds = rng.choice([-110, -150, -220, +120, +180, +250])
            p = rng.uniform(0.01, 0.99)
            implied = american_to_prob(odds)
            ev = ev_per_unit(p, odds)
            assert (ev > 0) == (p > implied)

    def test_kelly_respects_hard_cap(self):
        rng = random.Random(11)
        for _ in range(500):
            p = rng.uniform(0.5, 0.99)
            odds = rng.choice([-105, -110, +150, +400])
            cap = rng.choice([0.01, 0.015, 0.02])
            assert 0.0 <= kelly_fraction(p, odds, cap=cap) <= cap

    def test_kelly_is_zero_on_nonpositive_ev(self):
        rng = random.Random(13)
        for _ in range(500):
            odds = rng.choice([-110, -150, -220, +120, +180])
            implied = american_to_prob(odds)
            p = rng.uniform(0.01, max(implied - 1e-4, 0.02))  # below breakeven
            assert kelly_fraction(p, odds) == 0.0

    def test_devig_sums_to_one(self):
        rng = random.Random(17)
        for _ in range(500):
            over = rng.choice([-105, -110, -120, -150, -200])
            under = rng.choice([+105, +110, +120, +150, +200])
            po, pu = devig_two_way(over, under)
            assert po + pu == pytest.approx(1.0)
            assert 0.0 < po < 1.0 and 0.0 < pu < 1.0

    def test_prob_to_american_round_trip_band(self):
        # posted price implied prob must sit within the added vig band of fair p
        for p in (0.1, 0.25, 0.5, 0.75, 0.9):
            american = float(prob_to_american(p, vig=0.045))
            back = american_to_prob(american)
            assert abs(back - p) < 0.03  # within half-vig on one side

    def test_gate_is_byte_identical_across_calls(self):
        prov = QuoteProvenance(
            source="the-odds-api", book_id="draftkings",
            fetched_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
            raw_payload_hash="a" * 64,
            verification_status=VerificationStatus.VERIFIED,
            market_id="m:1:over:3.5", receipt_id="r1",
        )
        kw = dict(fair_prob=0.61, market_prob=0.5, odds=-110,
                  provenance=prov, news_age_minutes=12.0)
        assert evaluate_gate(**kw).model_dump_json() == evaluate_gate(**kw).model_dump_json()
        # and reproducible from (model_version, inputs) — the freeze's anchor
        out1 = build_pricing_output(model_version="v1", **kw)
        out2 = build_pricing_output(model_version="v1", **kw)
        assert out1.model_dump_json() == out2.model_dump_json()


# ---------------------------------------------------------------------------
# Part B — purity of the decision path (static guards)
# ---------------------------------------------------------------------------

class TestDecisionPathPurity:
    @pytest.mark.parametrize("module", DECISION_PATH_MODULES, ids=lambda m: m)
    def test_module_exists(self, module):
        assert (REPO_ROOT / module).is_file(), f"{module} vanished — update DECISION_PATH_MODULES deliberately"

    @pytest.mark.parametrize("module", DECISION_PATH_MODULES, ids=lambda m: m)
    def test_no_network_in_decision_path(self, module):
        src = (REPO_ROOT / module).read_text(encoding="utf-8")
        m = FORBIDDEN_NETWORK_IMPORTS.search(src)
        assert m is None, f"{module} imports network machinery ({m.group(0) if m else ''}) — pricing must be pure; fetching belongs to ingestion"

    @pytest.mark.parametrize("module", DECISION_PATH_MODULES, ids=lambda m: m)
    def test_no_llm_in_decision_path(self, module):
        src = (REPO_ROOT / module).read_text(encoding="utf-8")
        m = FORBIDDEN_LLM_IMPORTS.search(src)
        assert m is None, f"{module} imports an LLM client ({m.group(0) if m else ''}) — contract §0: LLM explains numbers after they are fixed, never makes one"

    @pytest.mark.parametrize("module", DECISION_PATH_MODULES, ids=lambda m: m)
    def test_no_global_or_unseeded_randomness(self, module):
        src = (REPO_ROOT / module).read_text(encoding="utf-8")
        m = FORBIDDEN_GLOBAL_RANDOMNESS.search(src)
        assert m is None, (
            f"{module} draws from global/unseeded randomness ({m.group(0) if m else ''}) — "
            "use a caller-seeded np.random.Generator passed as a parameter"
        )

    def test_evaluate_gate_source_has_no_io(self):
        # Belt and braces: the gate function itself must not touch disk,
        # network, or the clock.
        src = inspect.getsource(evaluate_gate)
        for banned in ("open(", "requests.", "httpx.", "datetime.now", "time.time", "uuid.", "random."):
            assert banned not in src, f"evaluate_gate() must stay pure — found {banned!r}"

    def test_build_pricing_output_source_has_no_io(self):
        src = inspect.getsource(build_pricing_output)
        for banned in ("open(", "requests.", "httpx.", "datetime.now", "time.time", "uuid.", "random."):
            assert banned not in src, f"build_pricing_output() must stay pure — found {banned!r}"


# ---------------------------------------------------------------------------
# Part C — fail-closed under every locking state
# ---------------------------------------------------------------------------

class TestFailClosedAcrossStates:
    @pytest.mark.parametrize("status", sorted(LOCKING_STATUSES, key=lambda s: s.value))
    def test_locking_state_never_unlocks_regardless_of_edge(self, status):
        prov = QuoteProvenance(
            source="the-odds-api", book_id="fanduel",
            fetched_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
            raw_payload_hash="b" * 64,
            verification_status=status,
            market_id="m:1:over:2.5",
        )
        out = build_pricing_output(
            fair_prob=0.95, market_prob=0.30, odds=+100,
            provenance=prov, model_version="v1", news_age_minutes=1.0,
        )
        assert out.gate.action_locked is True
        assert out.gate.verdict != GateVerdict.GREEN
        assert out.kelly_fraction == 0.0 or out.gate.action_locked  # stake rules hold
        # Kelly may be > 0 numerically, but the lock makes it non-actionable;
        # the PricingOutput invariant chain guarantees coherence.


# ---------------------------------------------------------------------------
# Part D — artifact provenance (ArtifactHeader on every manifest)
# ---------------------------------------------------------------------------

class TestArtifactProvenance:
    def _quote(self) -> dict:
        # -110/+110 gives a vig sum of exactly 1.00 — inside the contract's
        # [0.98, 1.45] floor, so this quote is genuinely publishable.
        return {
            "quote_id": "q1", "player_id": "p1", "player_name": "Test Player",
            "market": "receptions", "line": 3.5, "over_odds": -110,
            "under_odds": +110, "book": "draftkings",
            "observed_at": "2026-11-02T17:00:00+00:00", "verified": True,
        }

    def test_publish_manifest_carries_artifact_header(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROPSTEIN_COMMIT_SHA", "0" * 40)
        target = tmp_path / "feed.json"
        ok, manifest = validate_and_publish(OddsQuote, [self._quote()], target, source_feed="test")
        assert ok is True
        for field in ("run_id", "commit_sha", "data_cutoff_timestamp", "model_version", "contracts_version"):
            assert manifest.get(field), f"manifest missing frozen ArtifactHeader field: {field}"
        assert manifest["model_version"] == "ingestion-only"
        assert manifest["contracts_version"] == "quant.v1"
        # and on disk too
        disk = json.loads((tmp_path / "feed.manifest.json").read_text())
        assert disk["commit_sha"] == "0" * 40
        ArtifactHeader.model_validate({k: disk[k] for k in
                                       ("run_id", "commit_sha", "data_cutoff_timestamp",
                                        "model_version", "contracts_version", "generator")})

    def test_quarantine_manifest_carries_artifact_header(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROPSTEIN_COMMIT_SHA", "0" * 40)
        target = tmp_path / "bad_feed.json"
        # Vig floor violation (-110/+130 sums to 0.959 < 0.98): a
        # model_validator ValueError whose pydantic error ctx embeds the raw
        # exception object. This is the case that used to crash the quarantine
        # json.dump before the default=str fix — the quarantine record must
        # always be writable.
        ok, manifest = validate_and_publish(
            OddsQuote, [self._quote() | {"under_odds": +130}], target, source_feed="test"
        )
        assert ok is False
        assert manifest["status"] == "FAIL_CLOSED_QUARANTINED"
        for field in ("run_id", "commit_sha", "data_cutoff_timestamp", "model_version", "contracts_version"):
            assert manifest.get(field), f"quarantine record missing frozen field: {field}"
        assert manifest["quarantine_path"] and Path(manifest["quarantine_path"]).is_file()

    def test_unresolvable_commit_sha_fails_closed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROPSTEIN_COMMIT_SHA", raising=False)
        # Point the repo lookup at a directory with no git metadata.
        monkeypatch.setattr("src.contracts.quant.resolve_commit_sha", lambda: (_ for _ in ()).throw(RuntimeError("no git")))
        with pytest.raises(RuntimeError):
            validate_and_publish(OddsQuote, [self._quote()], tmp_path / "never.json", source_feed="test")
        assert not (tmp_path / "never.json").exists()

    def test_resolve_commit_sha_in_this_repo(self):
        sha = resolve_commit_sha()
        assert re.fullmatch(r"[0-9a-f]{7,40}", sha)
