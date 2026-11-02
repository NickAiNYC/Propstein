# Verification Layer (verification.v1) — the trust spine

Phase 2 of the institutional terminal build. `src/contracts/verification.py` is the
**only** sanctioned implementation that assigns a `VerificationStatus` to a quote.
Downstream surfaces (Slate Overview in Phase 3, Prop Board / Line Tool in Phase 4)
consume it through `to_provenance()`; they may never compute a status themselves,
same rule as `evaluate_gate()` for the gate.

## The engine

```python
from src.contracts.verification import (
    QuoteObservation, ReceiptRecord, PeerQuote, VerificationConfig,
    verify_quote, to_provenance, staleness_limit_minutes,
    ContextFeedKind, evaluate_context_freshness,
)

decision = verify_quote(
    observation=obs,          # what the feed saw
    now=now,                  # explicit clock — purity requires it as an input
    kickoff=kickoff,          # drives the staleness regime
    receipts=[...],           # append-only receipt log entries
    peers=[...],              # cross-book quotes (side-aligned no-vig probs)
)                              # -> VerificationDecision

provenance = to_provenance(decision, obs)   # -> quant.v1 QuoteProvenance
```

Pure and deterministic in all arguments **including `now`**: identical inputs
produce byte-identical decisions. No I/O, no clock reads, no randomness, no LLM
(enforced by `tests/test_leakage.py` decision-path guards and
`tests/test_verification_layer.py`).

## Clause set (frozen)

| Clause | Checks | Fails when |
|---|---|---|
| `V1_receipt` | `(market_id, book_id, raw_payload_hash)` matches a receipt captured at/before `now` | no receipts supplied, hash mismatch, other market/book, future-dated receipt |
| `V2_staleness` | quote age ≤ time-to-kickoff-aware limit | pregame > 90 min; inside 30-min kickoff window > 15 min; in-game > 2 min (all config-driven) |
| `V3_conflict` | no-vig spread across usable sharp books ≤ 5.0 pp | spread above threshold (CONFLICT), or fewer than `min_sharp_books=2` usable sharp quotes (UNKNOWN → fail) |

Every clause renders as `{clause_id}: {actual} {operator} {threshold} -> PASS|FAIL`
with real values — the terminal always shows these strings.

## Status precedence: STALE > CONFLICT > OBSERVED > VERIFIED

- **STALE** dominates: a stale quote's divergence math and receipt match describe
  the past, not the present.
- **CONFLICT** beats OBSERVED: a measured divergence is a positive finding the
  terminal must surface (`ConflictSnapshot` carries the books and no-vig probs).
- **OBSERVED** covers the cannot-certify cases: receipt missing, or conflict
  uncheckable. Unknown is not verified.
- **VERIFIED** requires all three clauses to pass — the only state that can ever
  unlock an action field (enforced again inside quant.v1 `PricingOutput`).

Future-dated observations are **rejected outright** (ValueError → HTTP 422), not
labeled. Naive datetimes are rejected everywhere (ambiguous input is fail-closed).

## First-class context freshness

Injuries / lineups / news carry their own configurable staleness
(`ContextFreshnessConfig`, minutes-scale). Unknown or future-dated last-check
times fail closed: `is_fresh=False, fail_closed=True`. The news threshold (45 min)
matches `GateConfig.news_max_age_minutes` so the C6 gate clause and the freshness
panel agree.

## API surface

- `POST /api/v1/verify-quote` — deterministic verification of one observation.
  Pin `now` for reproducible results. 422 on integrity violations; never a
  silently downgraded status; no demo fallback.
- `POST /api/v1/context-freshness` — context feed freshness verdict.
- `POST /api/v1/verify-receipt` — Phase 2 **removed the demo fallback** that
  fabricated a "CRYPTOGRAPHICALLY_PROVEN" lifecycle for unknown hashes; it now
  fails closed: unknown hash → 404, report missing → 503.

## Layering (module boundaries preserved)

- `src/agents/stale_kill_switch.py` — real-time agent cadence gate (seconds-scale,
  feed-level). Untouched; composes with, not replaced by, this layer.
- `src/odds_adapter.py` — ingestion and its provider receipts. Untouched in
  Phase 2; Phase 3/4 wires ingestion output through `verify_quote()`.
- `src/contracts/quant.py` (quant.v1) — decision contracts, unchanged.
