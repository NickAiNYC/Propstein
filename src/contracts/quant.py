"""
PropStein Foundation Freeze — Quant Decision Contracts (CONTRACTS_VERSION=quant.v1)

The single source of truth for anything the terminal is allowed to present as
a number a user can act on:

  * QuoteProvenance  — the trust spine for every quoted price
                       (source, book_id, fetched_at, raw_payload_hash,
                       verification_status, market_id)
  * GateClause / GateDecision — full-reasoning deterministic gating
  * PricingOutput    — fair_prob / fair_line / edge_pct / EV_per_unit /
                       Kelly_fraction + gate + provenance
  * ArtifactHeader   — run_id / commit_sha / data_cutoff_timestamp /
                       model_version on every artifact write
  * GateConfig       — thresholds (config object, never hardcoded at sites)
  * evaluate_gate()  — the ONLY gate implementation. Pure, deterministic,
                       no I/O, no LLM, no clock. (Contract §0: an LLM may
                       explain numbers after they are fixed; it may never
                       make one.)
  * build_pricing_output() — the sanctioned constructor for PricingOutput;
                       composes src/model.py math with evaluate_gate() so the
                       numbers and the gate can never disagree.

FROZEN means: additive changes only (new optional fields with defaults).
Removing or retyping a field, or changing a unit convention, requires a
written migration plan plus a CONTRACTS_VERSION bump. Enforced by
tests/test_contracts_quant.py::test_contract_surface_frozen.

Unit conventions (fixed for the life of quant.v1 — do not reinterpret):
  * fair_prob, kelly_fraction, EV_per_unit — fractions of 1 (0.052 == 5.2%)
  * edge_pct — PERCENTAGE POINTS (2.5 means 2.5%) because the field name
    says pct; it is 100 * (fair_prob - market_no_vig_prob)
  * American odds — integers with |odds| >= 100

Determinism: GateDecision and PricingOutput deliberately carry NO timestamps
and NO run identifiers. Reproducibility is anchored outside the object, in
ArtifactHeader (run-level) and the (commit_sha, data_cutoff) pair (system
contract §1). Two evaluations of the same inputs must be byte-identical.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACTS_VERSION = "quant.v1"

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Enumerations — the verification vocabulary is closed on purpose.
# ---------------------------------------------------------------------------

class VerificationStatus(str, Enum):
    """Closed vocabulary for quote verification (master prompt §2).

    VERIFIED — receipt-checked, hash-pinned, fresh: the only state that can
               ever unlock an action field.
    OBSERVED — seen on a book but not receipt-verified: locks action.
    STALE    — age beyond the configured staleness threshold: locks action.
    CONFLICT — sharp books diverge beyond threshold: locks action and must
               surface the divergence.
    UNVERIFIED — no receipt machinery has run yet (new/unknown feed): locks
               action. This is the default state of the universe; trust is
               earned, not assumed.
    """

    VERIFIED = "VERIFIED"
    OBSERVED = "OBSERVED"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    UNVERIFIED = "UNVERIFIED"


class GateVerdict(str, Enum):
    GREEN = "GREEN"    # qualified: edge >= threshold, EV > 0, Kelly > 0,
                       # VERIFIED, no conflict, news fresh
    YELLOW = "YELLOW"  # positive edge below gate — watch only, no action
    RED = "RED"        # negative edge / conflict / stale / unconfirmed


#: The states that lock the action field. VERIFIED is the ONLY unlock state.
LOCKING_STATUSES = frozenset(
    {VerificationStatus.OBSERVED, VerificationStatus.STALE,
     VerificationStatus.CONFLICT, VerificationStatus.UNVERIFIED}
)


# ---------------------------------------------------------------------------
# Provenance — the trust spine
# ---------------------------------------------------------------------------

class QuoteProvenance(BaseModel):
    """Every displayed quote carries this, in full, next to the number."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Feed/vendor id, e.g. 'the-odds-api'")
    book_id: str = Field(..., min_length=1, description="Sportsbook id, e.g. 'draftkings'")
    fetched_at: datetime = Field(..., description="UTC capture time of the raw payload")
    raw_payload_hash: str = Field(..., description="sha256 hex of the raw payload bytes")
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Receipt-verification state; anything but VERIFIED locks action",
    )
    market_id: str = Field(..., min_length=1, description="Stable market key, e.g. 'player_reception_yds:player-123:over:3.5'")

    receipt_id: Optional[str] = Field(default=None, description="Receipt log id when VERIFIED")
    source_url: Optional[str] = Field(default=None)
    book_line: Optional[float] = Field(default=None, description="Line as posted, for context")
    book_odds: Optional[int] = Field(default=None, description="American odds as posted")

    @field_validator("source", "book_id", "market_id")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("raw_payload_hash")
    @classmethod
    def _sha256_hex(cls, v: str) -> str:
        v = v.strip().lower()
        if not _HASH64_RE.fullmatch(v):
            raise ValueError("raw_payload_hash must be a 64-char lowercase sha256 hex digest")
        return v

    @field_validator("fetched_at")
    @classmethod
    def _utc_required(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware (UTC); naive datetimes are ambiguous")
        return v.astimezone(timezone.utc)

    @field_validator("book_odds")
    @classmethod
    def _american_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v == 0 or abs(v) < 100 or abs(v) > 50000:
            raise ValueError(f"American odds must satisfy 100 <= |odds| <= 50000, got {v}")
        return v

    @model_validator(mode="after")
    def _receipt_coherence(self) -> "QuoteProvenance":
        if self.verification_status == VerificationStatus.VERIFIED and not self.receipt_id:
            raise ValueError("VERIFIED quotes must carry a receipt_id — verified-without-receipt is how fake trust ships")
        return self


# ---------------------------------------------------------------------------
# Gating — full-reasoning, deterministic
# ---------------------------------------------------------------------------

class GateClause(BaseModel):
    """One machine-checkable clause of the gate, with the exact numbers.

    Rendered as: `{clause_id}: {actual} {operator} {threshold} -> PASS|FAIL`
    The terminal must always be able to show this string. No exceptions.
    """

    model_config = ConfigDict(extra="forbid")

    clause_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    operator: str = Field(..., min_length=1)          # ">=", ">", "==", "!=", "<="
    actual: object = Field(..., description="The measured value")
    threshold: object = Field(..., description="The configured bound")
    passed: bool

    def render(self) -> str:
        sym = "PASS" if self.passed else "FAIL"
        return f"{self.clause_id}: {self.actual} {self.operator} {self.threshold} -> {sym}"


class GateConfig(BaseModel):
    """Thresholds ride in a config object — never hardcoded at call sites
    (master prompt §2: 'Staleness thresholds config-driven').

    Defaults match production constants as of the freeze:
    src/agent.py MIN_EDGE=0.03, KELLY_CAP=0.015; staleness default 90 min
    pregame per the system contract.
    """

    model_config = ConfigDict(extra="forbid")

    edge_min_pct: float = Field(default=3.0, description="Minimum edge in PERCENTAGE POINTS (3.0 == 3%)")
    kelly_hard_cap: float = Field(default=0.015, description="Hard cap on Kelly fraction (1.5% of bankroll)")
    staleness_pregame_minutes: float = Field(default=90.0)
    staleness_near_kickoff_minutes: float = Field(default=15.0)
    news_max_age_minutes: float = Field(default=45.0)
    conflict_divergence_pct: float = Field(default=5.0, description="Sharp-book no-vig probability divergence in percentage points that trips CONFLICT")

    @field_validator(
        "edge_min_pct", "kelly_hard_cap", "staleness_pregame_minutes",
        "staleness_near_kickoff_minutes", "news_max_age_minutes",
        "conflict_divergence_pct",
    )
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("gate thresholds must be positive")
        return v

    @model_validator(mode="after")
    def _kickoff_tighter_than_pregame(self) -> "GateConfig":
        if self.staleness_near_kickoff_minutes > self.staleness_pregame_minutes:
            raise ValueError("near-kickoff staleness must be <= pregame staleness")
        return self


class GateDecision(BaseModel):
    """The verdict, the lock, and the complete reasoning trail.

    No timestamps, no run ids: byte-identical for identical inputs.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: GateVerdict
    action_locked: bool
    clauses: list[GateClause] = Field(..., min_length=1)
    config_snapshot: dict = Field(..., description="Echo of GateConfig used — the audit trail for 'why did the gate say that'")

    def reasoning(self) -> list[str]:
        return [c.render() for c in self.clauses]

    @model_validator(mode="after")
    def _lock_coherence(self) -> "GateDecision":
        if self.verdict == GateVerdict.RED and not self.action_locked:
            raise ValueError("RED verdict must lock the action field — fail closed, always")
        if self.verdict != GateVerdict.GREEN and not self.action_locked:
            raise ValueError("only GREEN may leave the action field unlocked")
        if self.verdict != GateVerdict.GREEN and not any(not c.passed for c in self.clauses):
            raise ValueError("a non-GREEN verdict must show at least one failed clause — silent gating is forbidden")
        return self


# ---------------------------------------------------------------------------
# Pricing output — the frozen quote surface
# ---------------------------------------------------------------------------

class PricingOutput(BaseModel):
    """Everything required on every quote (master prompt §2), plus the
    provenance and the gate that produced it. Construct via
    build_pricing_output() unless you are deliberately testing edge cases;
    the validators below are the backstop either way.
    """

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(..., min_length=1)
    fair_prob: float = Field(..., ge=0.0, le=1.0)
    fair_line: Optional[float] = Field(
        default=None,
        description="Model fair line for over/under markets; None ONLY for pure binary (h2h) markets",
    )
    edge_pct: float = Field(..., ge=-100.0, le=100.0, description="100*(fair_prob - market_no_vig_prob), PERCENTAGE POINTS")
    ev_per_unit: float = Field(..., description="Expected value per 1 unit staked, fraction (0.052 == 5.2%)")
    kelly_fraction: float = Field(..., ge=0.0, le=1.0, description="Capped Kelly as bankroll fraction")

    market_prob: float = Field(..., ge=0.0, le=1.0, description="No-vig market probability this edge was measured against")
    odds: int = Field(..., description="American odds of the priced side")

    provenance: QuoteProvenance
    gate: GateDecision
    model_version: str = Field(..., min_length=1)

    @field_validator("odds")
    @classmethod
    def _american(cls, v: int) -> int:
        if v == 0 or abs(v) < 100 or abs(v) > 50000:
            raise ValueError(f"American odds must satisfy 100 <= |odds| <= 50000, got {v}")
        return v

    @model_validator(mode="after")
    def _fail_closed_invariants(self) -> "PricingOutput":
        # 1. No stake on non-positive EV — the core fail-closed money rule.
        if self.ev_per_unit <= 0.0 and self.kelly_fraction != 0.0:
            raise ValueError("kelly_fraction must be 0 when EV <= 0 — the model never sizes a non-positive-EV bet")
        # 2. No stake on non-positive edge (edge <= 0 implies EV < 0 under vig).
        if self.edge_pct <= 0.0 and self.kelly_fraction != 0.0:
            raise ValueError("kelly_fraction must be 0 when edge_pct <= 0")
        # 3. Kelly > 0 requires positive EV.
        if self.kelly_fraction > 0.0 and self.ev_per_unit <= 0.0:
            raise ValueError("kelly_fraction > 0 requires ev_per_unit > 0")
        # 4. The unlock requires the full GREEN stack, VERIFIED included.
        if not self.gate.action_locked:
            if self.provenance.verification_status != VerificationStatus.VERIFIED:
                raise ValueError("unlocked action requires VERIFIED provenance — OBSERVED/STALE/CONFLICT/UNVERIFIED lock by definition")
            if self.gate.verdict != GateVerdict.GREEN:
                raise ValueError("unlocked action requires a GREEN verdict")
            if self.ev_per_unit <= 0.0 or self.kelly_fraction <= 0.0:
                raise ValueError("unlocked action requires ev_per_unit > 0 and kelly_fraction > 0")
        # 5. Provenance market must agree with the priced market.
        if self.provenance.market_id != self.market_id:
            raise ValueError("provenance.market_id must equal market_id — a quote priced against another market's receipt is fabrication")
        return self


# ---------------------------------------------------------------------------
# Artifact header — provenance for every artifact write
# ---------------------------------------------------------------------------

class ArtifactHeader(BaseModel):
    """System contract §1: every artifact write includes run_id, commit_sha,
    data_cutoff_timestamp, model_version. Files are the interface; this header
    is how a file says which code and which data produced it.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=1)
    commit_sha: str = Field(..., description="git commit of the producing code (7-40 hex)")
    data_cutoff_timestamp: datetime = Field(..., description="UTC instant after which no input data may be used (leakage boundary)")
    model_version: str = Field(..., min_length=1)
    contracts_version: str = Field(default=CONTRACTS_VERSION)
    generator: Optional[str] = Field(default=None, description="Producing module/script id")

    @field_validator("commit_sha")
    @classmethod
    def _sha(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SHA_RE.fullmatch(v):
            raise ValueError("commit_sha must be 7-40 hex chars (git SHA); set PROPSTEIN_COMMIT_SHA in deploy environments without git")
        return v

    @field_validator("data_cutoff_timestamp")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("data_cutoff_timestamp must be timezone-aware UTC")
        return v.astimezone(timezone.utc)


def resolve_commit_sha() -> str:
    """Resolve the producing code's commit SHA. Order: PROPSTEIN_COMMIT_SHA
    env, then `git rev-parse HEAD` in the repo root. Raises if neither
    resolves: an artifact that cannot name its code fails closed rather than
    shipping anonymous provenance (contract §1).
    """
    env_sha = os.environ.get("PROPSTEIN_COMMIT_SHA", "").strip().lower()
    if _SHA_RE.fullmatch(env_sha):
        return env_sha
    repo_root = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
            check=True,
        )
        sha = out.stdout.strip().lower()
        if _SHA_RE.fullmatch(sha):
            return sha
    except (subprocess.SubprocessError, OSError):
        pass
    raise RuntimeError(
        "cannot resolve commit_sha: git unavailable and PROPSTEIN_COMMIT_SHA unset. "
        "Refusing to write an artifact with anonymous provenance — set PROPSTEIN_COMMIT_SHA "
        "in the deploy environment."
    )


def new_run_id() -> str:
    """Run id in the established `run_<12hex>` format (matches contracts/gate.py)."""
    return f"run_{uuid.uuid4().hex[:12]}"


def artifact_header(
    *,
    model_version: str,
    data_cutoff: Optional[datetime] = None,
    commit_sha: Optional[str] = None,
    run_id: Optional[str] = None,
    generator: Optional[str] = None,
) -> ArtifactHeader:
    """Sanctioned constructor for ArtifactHeader.

    data_cutoff defaults to 'now' at call time — correct for ingestion
    artifacts whose cutoff IS the capture instant; model/backtest writers
    must pass their true cutoff explicitly.
    """
    return ArtifactHeader(
        run_id=run_id or new_run_id(),
        commit_sha=commit_sha or resolve_commit_sha(),
        data_cutoff_timestamp=data_cutoff or datetime.now(timezone.utc),
        model_version=model_version,
        generator=generator,
    )


# ---------------------------------------------------------------------------
# The gate — deterministic, pure, the only implementation
# ---------------------------------------------------------------------------

def evaluate_gate(
    *,
    fair_prob: float,
    market_prob: float,
    odds: int,
    provenance: QuoteProvenance,
    config: Optional[GateConfig] = None,
    news_age_minutes: Optional[float] = None,
    p_push: float = 0.0,
) -> GateDecision:
    """Evaluate the qualification gate. Pure function: no I/O, no clock, no
    randomness, no LLM. Identical inputs -> byte-identical decision.

    Clause set (master prompt §2):
      C1 edge        : edge_pct >= config.edge_min_pct
      C2 ev          : ev_per_unit > 0
      C3 kelly       : kelly_fraction > 0 (after the hard cap)
      C4 verification: verification_status == VERIFIED
      C5 conflict    : verification_status != CONFLICT
      C6 news        : news_age_minutes <= config.news_max_age_minutes
                       (None = freshness unknown -> FAIL, fail closed)

    Verdict: GREEN iff every clause passes. RED if edge <= 0 or the quote is
    CONFLICT/STALE/UNVERIFIED or verification failed. YELLOW otherwise
    (positive edge that did not clear the full gate — watch only).
    action_locked = verdict != GREEN.
    """
    cfg = config or GateConfig()
    # Math imported lazily so importing the contract stays dependency-light;
    # src.model is pure and deterministic (enforced by tests/test_leakage.py).
    from src.model import ev_per_unit as _ev, kelly_fraction as _kelly

    if not 0.0 <= fair_prob <= 1.0:
        raise ValueError("fair_prob must be in [0, 1]")
    if not 0.0 <= market_prob <= 1.0:
        raise ValueError("market_prob must be in [0, 1]")
    if not 0.0 <= p_push < 1.0:
        raise ValueError("p_push must be in [0, 1)")

    edge_pct = 100.0 * (fair_prob - market_prob)
    ev = _ev(fair_prob, odds, p_push)
    kelly = _kelly(fair_prob, odds, p_push, cap=cfg.kelly_hard_cap)
    status = provenance.verification_status

    clauses = [
        GateClause(
            clause_id="C1_edge",
            description="model edge over no-vig market probability",
            operator=">=",
            actual=round(edge_pct, 4),
            threshold=cfg.edge_min_pct,
            passed=edge_pct >= cfg.edge_min_pct,
        ),
        GateClause(
            clause_id="C2_ev",
            description="expected value per unit staked",
            operator=">",
            actual=round(ev, 6),
            threshold=0.0,
            passed=ev > 0.0,
        ),
        GateClause(
            clause_id="C3_kelly",
            description="capped Kelly fraction (bankroll)",
            operator=">",
            actual=round(kelly, 6),
            threshold=0.0,
            passed=kelly > 0.0,
        ),
        GateClause(
            clause_id="C4_verification",
            description="quote verification status",
            operator="==",
            actual=status.value,
            threshold=VerificationStatus.VERIFIED.value,
            passed=status == VerificationStatus.VERIFIED,
        ),
        GateClause(
            clause_id="C5_conflict",
            description="sharp-book conflict state",
            operator="!=",
            actual=status.value,
            threshold=VerificationStatus.CONFLICT.value,
            passed=status != VerificationStatus.CONFLICT,
        ),
        GateClause(
            clause_id="C6_news",
            description="injury/news/lineup freshness (minutes since last check)",
            operator="<=",
            actual=None if news_age_minutes is None else round(news_age_minutes, 1),
            threshold=cfg.news_max_age_minutes,
            passed=news_age_minutes is not None and news_age_minutes <= cfg.news_max_age_minutes,
        ),
    ]

    hard_red = (
        edge_pct <= 0.0
        or status in (VerificationStatus.CONFLICT, VerificationStatus.STALE, VerificationStatus.UNVERIFIED)
        or status != VerificationStatus.VERIFIED  # OBSERVED lands here too
    )
    all_pass = all(c.passed for c in clauses)
    if all_pass:
        verdict = GateVerdict.GREEN
    elif hard_red:
        verdict = GateVerdict.RED
    else:
        verdict = GateVerdict.YELLOW

    return GateDecision(
        verdict=verdict,
        action_locked=verdict != GateVerdict.GREEN,
        clauses=clauses,
        config_snapshot=cfg.model_dump(mode="json"),
    )


def build_pricing_output(
    *,
    fair_prob: float,
    market_prob: float,
    odds: int,
    provenance: QuoteProvenance,
    model_version: str,
    fair_line: Optional[float] = None,
    config: Optional[GateConfig] = None,
    news_age_minutes: Optional[float] = None,
    p_push: float = 0.0,
) -> PricingOutput:
    """Sanctioned PricingOutput constructor. Computes edge/EV/Kelly through
    src/model.py and the gate through evaluate_gate(), so the numbers and the
    verdict are guaranteed coherent. Deterministic in all arguments.
    """
    cfg = config or GateConfig()
    gate = evaluate_gate(
        fair_prob=fair_prob, market_prob=market_prob, odds=odds,
        provenance=provenance, config=cfg,
        news_age_minutes=news_age_minutes, p_push=p_push,
    )
    from src.model import ev_per_unit as _ev, kelly_fraction as _kelly

    return PricingOutput(
        market_id=provenance.market_id,
        fair_prob=fair_prob,
        fair_line=fair_line,
        edge_pct=round(100.0 * (fair_prob - market_prob), 4),
        ev_per_unit=round(_ev(fair_prob, odds, p_push), 6),
        kelly_fraction=round(_kelly(fair_prob, odds, p_push, cap=cfg.kelly_hard_cap), 6),
        market_prob=market_prob,
        odds=odds,
        provenance=provenance,
        gate=gate,
        model_version=model_version,
    )


__all__ = [
    "CONTRACTS_VERSION",
    "VerificationStatus",
    "GateVerdict",
    "LOCKING_STATUSES",
    "QuoteProvenance",
    "GateClause",
    "GateConfig",
    "GateDecision",
    "PricingOutput",
    "ArtifactHeader",
    "resolve_commit_sha",
    "new_run_id",
    "artifact_header",
    "evaluate_gate",
    "build_pricing_output",
]
