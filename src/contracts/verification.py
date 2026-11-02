"""
PropStein Verification Layer — the trust spine engine (CONTRACTS_VERSION=verification.v1)

Phase 2 of the institutional terminal build. Phase 1 (quant.v1) froze the
DECISION contracts: QuoteProvenance carries a verification_status, and
evaluate_gate() consumes it. This module is the deterministic engine that
ASSIGNS that status. Nothing downstream may compute a verification status any
other way (single source of truth, same rule as evaluate_gate()).

Status vocabulary (closed — reuses quant.v1's VerificationStatus, never
redefines it):
  VERIFIED — receipt-matched, fresh under the time-to-kickoff-aware staleness
             regime, and sharp-book divergence within threshold. The only
             state that can ever unlock an action field.
  STALE    — quote age beyond the configured staleness limit. Takes precedence
             over every other finding: staleness is intrinsic to the quote
             itself and makes every downstream comparison unreliable.
  CONFLICT — fresh sharp books diverge beyond `conflict_divergence_pct` no-vig
             percentage points. Must be surfaced (the snapshot carries the
             divergent books and their no-vig probabilities), never folded
             into a milder label.
  OBSERVED — seen on a book, but either the receipt does not match, or the
             conflict check could not be run (fewer than `min_sharp_books`
             usable sharp quotes). Unknown is not verified: fail closed.
  UNVERIFIED — no verification machinery has run (the default of the universe;
             produced only by direct construction, never by verify_quote()).

Clause set (frozen; the terminal always renders these):
  V1_receipt   : raw payload hash matched in the receipt log for this
                 (market_id, book_id). No receipts supplied -> FAIL.
  V2_staleness : quote age <= staleness limit, where the limit is
                 time-to-kickoff aware:
                   kickoff unknown or > near_kickoff_window away -> pregame
                   0 <= time-to-kickoff <= window               -> near-kickoff
                   game already started                          -> in-game
  V3_conflict  : no-vig probability spread across usable sharp books
                 (fresh, same market; the observed book itself counts when it
                 is sharp and two-sided) <= conflict_divergence_pct.
                 Fewer than min_sharp_books usable quotes -> FAIL with
                 actual=None (conflict UNKNOWN, not absent).

Status precedence: STALE > CONFLICT > OBSERVED > VERIFIED. Rationale is in
the docstring of verify_quote(); changing it is a contract amendment.

Purity: verify_quote() performs no I/O, touches no clock (now is an explicit
parameter), uses no randomness, and calls no LLM. Identical inputs —
including `now` — produce byte-identical decisions. Enforced by
tests/test_verification_layer.py and the DECISION_PATH purity guards in
tests/test_leakage.py.

Context freshness (injuries / news / lineups are first-class): the
ContextFreshness contracts give each context feed its own configurable
staleness with fail-closed semantics — a feed whose last check time is
unknown or future-dated is NOT fresh, because unknown does not mean fresh.

FROZEN means additive changes only, exactly like quant.v1. Enforced by
tests/test_verification_layer.py::TestContractSurfaceFrozen.

Layering note (module boundary preserved): src/agents/stale_kill_switch.py
is the real-time agent cadence gate (seconds-scale, feed-level) and is
untouched. This module is the quote-level trust spine (minutes-scale,
quote-level). They compose; they do not replace each other.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.contracts.quant import GateClause, QuoteProvenance, VerificationStatus

VERIFICATION_CONTRACTS_VERSION = "verification.v1"

#: The frozen clause ids of the verification decision.
VERIFICATION_CLAUSE_IDS = frozenset({"V1_receipt", "V2_staleness", "V3_conflict"})

_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_utc(v: datetime, name: str) -> datetime:
    if v.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware UTC; naive datetimes are ambiguous")
    return v.astimezone(timezone.utc)


def _sha256_hex(v: str) -> str:
    v = v.strip().lower()
    if not _HASH64_RE.fullmatch(v):
        raise ValueError("must be a 64-char lowercase sha256 hex digest")
    return v


def _non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


# ---------------------------------------------------------------------------
# Configuration — thresholds ride in config objects, never call sites
# ---------------------------------------------------------------------------

class VerificationConfig(BaseModel):
    """Quote-level verification thresholds.

    Defaults mirror the frozen constants as of Phase 2:
      * sharp_books mirrors src/odds.py SHARP_BOOKS — books whose prices carry
        information. Recreational books are bet-into, not trusted.
      * staleness_pregame_minutes / staleness_near_kickoff_minutes match
        quant.v1 GateConfig (90 / 15).
      * conflict_divergence_pct matches GateConfig.conflict_divergence_pct (5.0
        no-vig percentage points).
    Change behavior by constructing a config, never by editing call sites
    (master prompt: staleness thresholds are config-driven).
    """

    model_config = ConfigDict(extra="forbid")

    sharp_books: list[str] = Field(
        default_factory=lambda: ["pinnacle", "betonlineag", "lowvig", "circasports"],
        description="Book ids whose prices carry information (mirrors src/odds.py SHARP_BOOKS)",
    )
    min_sharp_books: int = Field(
        default=2, ge=2,
        description="Usable sharp quotes required to run the conflict check; a conflict check needs at least two independent sharp quotes",
    )
    conflict_divergence_pct: float = Field(
        default=5.0,
        description="No-vig probability spread (PERCENTAGE POINTS) across sharp books that trips CONFLICT",
    )
    staleness_pregame_minutes: float = Field(
        default=90.0, description="Max quote age when kickoff is unknown or > near_kickoff_window away",
    )
    staleness_near_kickoff_minutes: float = Field(
        default=15.0, description="Max quote age inside the near-kickoff window",
    )
    staleness_in_game_minutes: float = Field(
        default=2.0,
        description="Max quote age once the game has started; in-game prop odds move every play",
    )
    near_kickoff_window_minutes: float = Field(
        default=30.0, description="Time-to-kickoff at which the tighter staleness regime begins",
    )

    @field_validator("sharp_books")
    @classmethod
    def _sharp_books_shape(cls, v: list[str]) -> list[str]:
        cleaned = [_non_blank(b).lower() for b in v]
        if not cleaned:
            raise ValueError("sharp_books must not be empty — a verification config that trusts no book cannot run a conflict check")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("sharp_books must be unique")
        return cleaned

    @field_validator(
        "conflict_divergence_pct", "staleness_pregame_minutes",
        "staleness_near_kickoff_minutes", "staleness_in_game_minutes",
        "near_kickoff_window_minutes",
    )
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("verification thresholds must be positive")
        return v

    @model_validator(mode="after")
    def _staleness_ordering(self) -> "VerificationConfig":
        if self.staleness_near_kickoff_minutes > self.staleness_pregame_minutes:
            raise ValueError("near-kickoff staleness must be <= pregame staleness")
        if self.staleness_in_game_minutes > self.staleness_near_kickoff_minutes:
            raise ValueError("in-game staleness must be <= near-kickoff staleness")
        return self


# ---------------------------------------------------------------------------
# Inputs — the observation under test, its receipts, and its peers
# ---------------------------------------------------------------------------

class QuoteObservation(BaseModel):
    """A raw quote observation as captured by ingestion. This is the INPUT to
    verification; QuoteProvenance (quant.v1) is the OUTPUT that pricing
    carries. Keeping them separate keeps the trust spine auditable: inputs are
    what the feed saw, outputs are what we certified.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Feed/vendor id, e.g. 'the-odds-api'")
    book_id: str = Field(..., min_length=1, description="Canonical book slug, e.g. 'draftkings'")
    market_id: str = Field(..., min_length=1, description="Stable market key, e.g. 'player_reception_yds:player-123:over:3.5'")
    fetched_at: datetime = Field(..., description="UTC capture time of the raw payload")
    raw_payload_hash: str = Field(..., description="sha256 hex of the raw payload bytes")

    side: str = Field(default="over", description="Priced side this observation refers to")
    over_odds: int = Field(..., description="American odds of the over side")
    under_odds: Optional[int] = Field(default=None, description="American odds of the under side; required for the observation to join the sharp comparison")
    book_line: Optional[float] = Field(default=None, description="Line as posted, for context")

    @field_validator("source", "book_id", "market_id")
    @classmethod
    def _non_blank_fields(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("raw_payload_hash")
    @classmethod
    def _hash_fields(cls, v: str) -> str:
        return _sha256_hex(v)

    @field_validator("side")
    @classmethod
    def _side_vocab(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("over", "under"):
            raise ValueError("side must be 'over' or 'under'")
        return v

    @field_validator("over_odds", "under_odds")
    @classmethod
    def _american(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v == 0 or abs(v) < 100 or abs(v) > 50000:
            raise ValueError(f"American odds must satisfy 100 <= |odds| <= 50000, got {v}")
        return v

    @field_validator("fetched_at")
    @classmethod
    def _utc_fields(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware (UTC); naive datetimes are ambiguous")
        return v.astimezone(timezone.utc)


class ReceiptRecord(BaseModel):
    """One entry of the append-only odds receipt log (docs/ODDS_RECEIPTS.md).
    A receipt is the durable evidence that a provider response existed and had
    exactly the hashed content. Verification matches on
    (market_id, book_id, raw_payload_hash); a receipt for another market or
    book is not evidence for this quote.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(..., min_length=1)
    market_id: str = Field(..., min_length=1)
    book_id: str = Field(..., min_length=1)
    raw_payload_hash: str = Field(..., description="sha256 hex of the raw payload bytes")
    captured_at: datetime = Field(..., description="UTC time the receipt was written")

    @field_validator("receipt_id", "market_id", "book_id")
    @classmethod
    def _non_blank_fields(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("raw_payload_hash")
    @classmethod
    def _hash_fields(cls, v: str) -> str:
        return _sha256_hex(v)

    @field_validator("captured_at")
    @classmethod
    def _utc_fields(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware (UTC)")
        return v.astimezone(timezone.utc)


class PeerQuote(BaseModel):
    """A cross-book quote used for the sharp-divergence check.

    no_vig_prob is the de-vigged probability OF THE SAME SIDE as the
    observation under test (side alignment is the caller's responsibility —
    ingestion normalizes sides before building peers). Peers carry their own
    fetched_at; stale or future-dated peers are excluded from the conflict
    check and counted, never silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(..., min_length=1)
    market_id: str = Field(..., min_length=1)
    no_vig_prob: float = Field(..., ge=0.0, le=1.0)
    fetched_at: datetime = Field(..., description="UTC capture time of this peer quote")

    @field_validator("book_id", "market_id")
    @classmethod
    def _non_blank_fields(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("fetched_at")
    @classmethod
    def _utc_fields(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware (UTC)")
        return v.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Outputs — the decision and the conflict evidence
# ---------------------------------------------------------------------------

class ConflictSnapshot(BaseModel):
    """The evidence behind a V3_conflict clause: which sharp books were
    compared, their no-vig probabilities for the same side, and the spread.
    CONFLICT must be presented, never summarized away — this object is what
    the terminal renders next to a red badge.
    """

    model_config = ConfigDict(extra="forbid")

    books: list[str] = Field(..., min_length=1, description="Sharp book ids included, sorted")
    no_vig_probs: list[float] = Field(..., min_length=1, description="No-vig probability per book, aligned with books")
    spread_pct: float = Field(..., ge=0.0, description="100 * (max - min) of no_vig_probs, percentage points")
    excluded_stale: int = Field(default=0, ge=0, description="Sharp peers excluded for staleness or invalid timestamps")
    included_self: bool = Field(default=False, description="Whether the observed quote itself joined the comparison")

    @model_validator(mode="after")
    def _aligned(self) -> "ConflictSnapshot":
        if len(self.books) != len(self.no_vig_probs):
            raise ValueError("books and no_vig_probs must be aligned (same length)")
        if len(set(self.books)) != len(self.books):
            raise ValueError("books must be unique")
        if self.books != sorted(self.books):
            raise ValueError("books must be sorted — determinism is part of the contract")
        return self


class VerificationDecision(BaseModel):
    """The verdict of the trust spine, with the complete reasoning trail.

    Carries no timestamps and no run identifiers — same rule as quant.v1's
    GateDecision: identical inputs (including the explicit `now` passed to
    verify_quote()) yield byte-identical decisions. The capture time lives in
    the caller's envelope, not in the decision.
    """

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus = Field(..., description="Assigned trust status; anything but VERIFIED locks action downstream")
    receipt_id: Optional[str] = Field(default=None, description="Matched receipt id, present only when V1 passed")
    clauses: list[GateClause] = Field(..., min_length=3, description="V1_receipt / V2_staleness / V3_conflict, each with actual values")
    conflict: Optional[ConflictSnapshot] = Field(default=None, description="Divergence evidence; None when no sharp quotes were usable at all")
    config_snapshot: dict = Field(..., description="Echo of the VerificationConfig used — the audit trail for 'why this status'")

    def reasoning(self) -> list[str]:
        return [c.render() for c in self.clauses]

    @model_validator(mode="after")
    def _fail_closed_invariants(self) -> "VerificationDecision":
        ids = {c.clause_id for c in self.clauses}
        if ids != set(VERIFICATION_CLAUSE_IDS):
            raise ValueError(
                "verification clause set is frozen: exactly V1_receipt, V2_staleness, V3_conflict; "
                "amending the clause set requires a written migration plan and a version bump"
            )
        if self.status == VerificationStatus.VERIFIED:
            if not self.receipt_id:
                raise ValueError("VERIFIED requires a receipt_id — verified-without-receipt is how fake trust ships")
            if not all(c.passed for c in self.clauses):
                raise ValueError("VERIFIED requires every clause to pass — silent partial verification is forbidden")
            if self.conflict is None:
                raise ValueError("VERIFIED requires a conflict snapshot — an unchecked conflict is an unknown conflict")
        return self


# ---------------------------------------------------------------------------
# Staleness regime — time-to-kickoff aware, config-driven
# ---------------------------------------------------------------------------

def staleness_limit_minutes(
    *,
    now: datetime,
    kickoff: Optional[datetime],
    config: Optional[VerificationConfig] = None,
) -> float:
    """The staleness limit in effect at `now` for a game with this `kickoff`.

    Pure function of its arguments. kickoff=None means the kickoff time is
    unknown -> the pregame default applies (the honest, conservative regime
    when the schedule is not pinned).
    """
    cfg = config or VerificationConfig()
    now = _require_utc(now, "now")
    if kickoff is None:
        return cfg.staleness_pregame_minutes
    kickoff = _require_utc(kickoff, "kickoff")
    minutes_to_kickoff = (kickoff - now).total_seconds() / 60.0
    if minutes_to_kickoff < 0.0:
        return cfg.staleness_in_game_minutes
    if minutes_to_kickoff <= cfg.near_kickoff_window_minutes:
        return cfg.staleness_near_kickoff_minutes
    return cfg.staleness_pregame_minutes


# ---------------------------------------------------------------------------
# The engine — pure, deterministic, the only status assigner
# ---------------------------------------------------------------------------

def verify_quote(
    *,
    observation: QuoteObservation,
    now: datetime,
    kickoff: Optional[datetime] = None,
    config: Optional[VerificationConfig] = None,
    receipts: Sequence[ReceiptRecord] = (),
    peers: Sequence[PeerQuote] = (),
) -> VerificationDecision:
    """Assign a VerificationStatus to a quote observation.

    Deterministic in ALL arguments including `now` (the clock is an input,
    never consulted). No I/O, no randomness, no LLM. Identical inputs ->
    byte-identical decision, enforced by tests.

    Fail-closed rules baked in:
      * future-dated observations are rejected outright (ValueError) — a
        quote from the future is a data integrity violation, not a state to
        label (docs/ODDS_RECEIPTS.md: future timestamps are rejected);
      * receipts captured after `now` are not evidence yet;
      * fewer than min_sharp_books usable sharp quotes -> V3 FAILS with
        actual=None (conflict UNKNOWN), so the quote can never be VERIFIED on
        an uncheckable market;
      * no receipts supplied -> V1 FAILS (absence of evidence is not
        evidence).

    Status precedence (worst news first, and why):
      STALE    > CONFLICT > OBSERVED > VERIFIED
      Staleness dominates because it corrupts every other comparison — a
      stale quote's divergence math and even its receipt match describe the
      past, not the present. Conflict beats OBSERVED because a measured
      divergence is a positive finding the terminal must surface (master
      prompt: conflict -> block AND present), while OBSERVED covers the
      'cannot certify' cases (receipt missing, conflict uncheckable).
    """
    cfg = config or VerificationConfig()
    now = _require_utc(now, "now")
    if kickoff is not None:
        kickoff = _require_utc(kickoff, "kickoff")

    if observation.fetched_at > now:
        raise ValueError(
            f"observation fetched_at ({observation.fetched_at.isoformat()}) is in the future "
            f"relative to now ({now.isoformat()}) — future-dated quotes are rejected outright, not labeled"
        )

    # --- V1: receipt match -------------------------------------------------
    usable_receipts = [r for r in receipts if r.captured_at <= now]
    matching = [
        r for r in usable_receipts
        if r.market_id == observation.market_id
        and r.book_id == observation.book_id
        and r.raw_payload_hash == observation.raw_payload_hash
    ]
    receipt = max(matching, key=lambda r: (r.captured_at, r.receipt_id)) if matching else None

    # --- V2: staleness -----------------------------------------------------
    age_minutes = (now - observation.fetched_at).total_seconds() / 60.0
    limit_minutes = staleness_limit_minutes(now=now, kickoff=kickoff, config=cfg)
    fresh = age_minutes <= limit_minutes

    # --- V3: sharp-book divergence ------------------------------------------
    limit_seconds = limit_minutes * 60.0
    included: list[tuple[str, float]] = []
    excluded_stale = 0
    for p in peers:
        if p.market_id != observation.market_id or p.book_id not in cfg.sharp_books:
            continue
        if p.fetched_at > now or (now - p.fetched_at).total_seconds() > limit_seconds:
            excluded_stale += 1
            continue
        included.append((p.book_id, round(float(p.no_vig_prob), 6)))

    included_self = False
    if (
        observation.book_id in cfg.sharp_books
        and observation.under_odds is not None
        and observation.over_odds is not None
    ):
        from src.model import devig_two_way

        p_over, p_under = devig_two_way(observation.over_odds, observation.under_odds)
        own = p_over if observation.side == "over" else p_under
        included.append((observation.book_id, round(float(own), 6)))
        included_self = True

    included.sort(key=lambda kv: kv[0])
    conflict: Optional[ConflictSnapshot] = None
    if included:
        probs = [prob for _, prob in included]
        spread_pct = round(100.0 * (max(probs) - min(probs)), 4)
        conflict = ConflictSnapshot(
            books=[b for b, _ in included],
            no_vig_probs=probs,
            spread_pct=spread_pct,
            excluded_stale=excluded_stale,
            included_self=included_self,
        )

    conflict_checkable = len(included) >= cfg.min_sharp_books
    if conflict_checkable:
        conflict_actual: Optional[float] = conflict.spread_pct if conflict else None
        conflict_passed = conflict is not None and conflict.spread_pct <= cfg.conflict_divergence_pct
    else:
        conflict_actual = None  # UNKNOWN, not zero
        conflict_passed = False

    clauses = [
        GateClause(
            clause_id="V1_receipt",
            description="receipt log match for (market, book, payload hash)",
            operator="==",
            actual="receipt_found" if receipt is not None else "receipt_missing",
            threshold="receipt_found",
            passed=receipt is not None,
        ),
        GateClause(
            clause_id="V2_staleness",
            description="quote age vs time-to-kickoff-aware staleness limit (minutes)",
            operator="<=",
            actual=round(age_minutes, 3),
            threshold=round(limit_minutes, 3),
            passed=fresh,
        ),
        GateClause(
            clause_id="V3_conflict",
            description="sharp-book no-vig divergence (percentage points); None = uncheckable (fewer sharp quotes than min_sharp_books)",
            operator="<=",
            actual=conflict_actual,
            threshold=cfg.conflict_divergence_pct,
            passed=conflict_passed,
        ),
    ]

    # --- status precedence: STALE > CONFLICT > OBSERVED > VERIFIED ---------
    if not fresh:
        status = VerificationStatus.STALE
    elif not conflict_passed and conflict_actual is not None:
        status = VerificationStatus.CONFLICT
    elif all(c.passed for c in clauses):
        status = VerificationStatus.VERIFIED
    else:
        status = VerificationStatus.OBSERVED

    return VerificationDecision(
        status=status,
        receipt_id=receipt.receipt_id if receipt is not None else None,
        clauses=clauses,
        conflict=conflict,
        config_snapshot=cfg.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Bridge to quant.v1 — the only sanctioned way a decision becomes provenance
# ---------------------------------------------------------------------------

def to_provenance(
    decision: VerificationDecision,
    observation: QuoteObservation,
    *,
    source_url: Optional[str] = None,
) -> QuoteProvenance:
    """Build the quant.v1 QuoteProvenance that pricing carries, from a
    verification decision and the observation it was rendered on. Pricing
    surfaces (Phase 3/4) consume the trust spine through this bridge so the
    status they display can never disagree with the engine's assignment.
    """
    book_odds = observation.over_odds if observation.side == "over" else observation.under_odds
    return QuoteProvenance(
        source=observation.source,
        book_id=observation.book_id,
        fetched_at=observation.fetched_at,
        raw_payload_hash=observation.raw_payload_hash,
        verification_status=decision.status,
        market_id=observation.market_id,
        receipt_id=decision.receipt_id,
        source_url=source_url,
        book_line=observation.book_line,
        book_odds=book_odds,
    )


# ---------------------------------------------------------------------------
# Context freshness — injuries / news / lineups are first-class
# ---------------------------------------------------------------------------

class ContextFeedKind(str, Enum):
    INJURY = "injury"
    LINEUP = "lineup"
    NEWS = "news"


class ContextFreshnessConfig(BaseModel):
    """Per-feed context staleness, in minutes. These are PRESENTATION-layer
    thresholds (minutes-scale); the real-time agent cadence gates
    (seconds-scale) live in src/agents/stale_kill_switch.py and are untouched.
    news_max_age_minutes matches quant.v1 GateConfig.news_max_age_minutes so
    the gate's C6 clause and the terminal's freshness panel agree.
    """

    model_config = ConfigDict(extra="forbid")

    injury_max_age_minutes: float = Field(default=45.0)
    lineup_max_age_minutes: float = Field(default=30.0)
    news_max_age_minutes: float = Field(default=45.0)

    @field_validator("injury_max_age_minutes", "lineup_max_age_minutes", "news_max_age_minutes")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("context freshness thresholds must be positive")
        return v


class ContextFreshness(BaseModel):
    """Freshness verdict for one context feed. fail_closed=True means the
    age could not be established (never checked, or future-dated) — and
    fail-closed is never fresh, because unknown does not mean fresh.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ContextFeedKind
    age_minutes: Optional[float] = Field(default=None, description="Minutes since last check; None when unknown")
    threshold_minutes: float
    is_fresh: bool
    fail_closed: bool = Field(default=False, description="True when age is unknown or invalid")

    @model_validator(mode="after")
    def _coherence(self) -> "ContextFreshness":
        if self.fail_closed and (self.age_minutes is not None or self.is_fresh):
            raise ValueError("fail_closed context freshness must have unknown age and is_fresh=False")
        if self.is_fresh and self.age_minutes is None:
            raise ValueError("is_fresh requires a known age")
        if self.age_minutes is not None and self.age_minutes > self.threshold_minutes and self.is_fresh:
            raise ValueError("age above threshold cannot be fresh")
        return self


def evaluate_context_freshness(
    *,
    kind: ContextFeedKind,
    last_checked_at: Optional[datetime],
    now: datetime,
    config: Optional[ContextFreshnessConfig] = None,
) -> ContextFreshness:
    """Evaluate one context feed's freshness. Pure; `now` is an explicit input.

    Fail-closed: last_checked_at None (never checked) or in the future
    (invalid data) both yield fail_closed=True, is_fresh=False.
    """
    cfg = config or ContextFreshnessConfig()
    now = _require_utc(now, "now")
    thresholds = {
        ContextFeedKind.INJURY: cfg.injury_max_age_minutes,
        ContextFeedKind.LINEUP: cfg.lineup_max_age_minutes,
        ContextFeedKind.NEWS: cfg.news_max_age_minutes,
    }
    threshold = thresholds[kind]

    if last_checked_at is None:
        return ContextFreshness(
            kind=kind, age_minutes=None, threshold_minutes=threshold,
            is_fresh=False, fail_closed=True,
        )
    checked = _require_utc(last_checked_at, "last_checked_at")
    if checked > now:
        return ContextFreshness(
            kind=kind, age_minutes=None, threshold_minutes=threshold,
            is_fresh=False, fail_closed=True,
        )
    age = (now - checked).total_seconds() / 60.0
    return ContextFreshness(
        kind=kind, age_minutes=round(age, 3), threshold_minutes=threshold,
        is_fresh=age <= threshold, fail_closed=False,
    )


__all__ = [
    "VERIFICATION_CONTRACTS_VERSION",
    "VERIFICATION_CLAUSE_IDS",
    "VerificationConfig",
    "QuoteObservation",
    "ReceiptRecord",
    "PeerQuote",
    "ConflictSnapshot",
    "VerificationDecision",
    "ContextFeedKind",
    "ContextFreshnessConfig",
    "ContextFreshness",
    "staleness_limit_minutes",
    "verify_quote",
    "to_provenance",
    "evaluate_context_freshness",
]
