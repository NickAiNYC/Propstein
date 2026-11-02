# Phase 3 — Slate Overview (operator surface)

Branch: `feat/phase3-slate-overview` (off `origin/main`).
Status: landed as a self-contained Next.js App Router workspace under `terminal/`.

## Why a separate workspace (contract note)

The root `app/` directory is paid-tier scaffolding (billing, legal, Stripe,
Prisma, next-auth) that has never been buildable — its imports were never
installed, consistent with the paid freeze. Extending it would have required
reviving those routes with stubs or full implementations, both of which
violate the no-placeholder rule on paid-reachable routes. Phase 3 therefore
introduces the operator terminal as `terminal/`:

- Root `package.json`, `vercel.json`, and the static viewer deployment are
  untouched — zero risk to the live propwire/propstein sites.
- The workspace reads the versioned Python model artifacts under `viewer/`
  (files-as-interface contract). It never recomputes pricing.
- When the paid tier unfreezes, consolidation with the root `app/` scaffold
  happens under a written migration plan, per the module-boundary contract.

## What landed

| File | Role |
|---|---|
| `terminal/lib/types/slate.ts` | Typed contracts: `GateClause` (hard/soft severity), `FeedSourceHealth` (primary/secondary tier), `QualifiedPlaySummary`, `SlateOverview`, `CardState = QUALIFIED / WATCH / BLOCKED_DATA / BLOCKED_GATE`, `deriveCardState`, `firstFailingHardClause` |
| `terminal/components/slate/top-qualified-play.tsx` | Dominant-number card: 48px edge (or BLOCKED), secondary metrics right-stacked, gate chips with hard-fail emphasis, state-colored border |
| `terminal/components/slate/feed-health-panel.tsx` | Primary sources in a full table; secondary sources collapsed to one line labeled "context only — not used for action"; a missing hash audit on a primary escalates |
| `terminal/components/slate/plays-table.tsx` | The full board: every quote with edge, fair line, state chip, trust badge |
| `terminal/components/primitives/*` | `VerificationBadge` (distinct aria-labels per status — never just "unverified"), `TabularNumber` |
| `terminal/lib/data/slate-overview.ts` | Deterministic data layer over `viewer/live_odds_feed.json`, `news_watcher_state.json`, and the config artifacts; FAIL CLOSED on unreadable inputs; `?__mock=` fixtures gated to the test environment only |
| `terminal/app/slate/page.tsx` | The `/slate` route: persistent CONFLICT banner (role=alert, source + last good timestamp), top play, feed health, board |
| `terminal/tests/slate-overview-failure-modes.spec.ts` | Playwright failure-mode spec (6 cases: conflict banner, distinct badges, edge-positive-but-OBSERVED, hard-gate fail with named clause, soft-gate WATCH, primary/secondary hierarchy) |
| `terminal/scripts/verify_slate_failure_modes.mjs` | Browserless HTML verification of the same 6 cases — runs anywhere Node runs |

## BLOCKED_DATA vs BLOCKED_GATE

Transient (data trust: STALE / CONFLICT / OBSERVED) → `BLOCKED_DATA` —
"wait and refresh", resolves when the feed recovers. Structural (a hard gate
clause failed) → `BLOCKED_GATE` — "the model said no, walk away." Same visual
weight, different copy, different operator verb. Only VERIFIED is actionable;
fail closed everywhere else.

## Determinism and config provenance

- Edge gate: `viewer/top_picks.json` `gate_edge` (0.1 → 10.0 pp), season/week for the slate id.
- Staleness: `viewer/circuit_breaker_config.json` `sports.nfl.thresholds.odds_stale_max_age_seconds` (21600s).
- Drift/conflict: per-market `drift_hurdle` from the same breaker config — same player + market quoted across books beyond the hurdle = CONFLICT.
- News freshness soft clause: 300s, pinned by the breaker messaging copy ("stale >5m").
- EV: `evaluation.expected_return`; edge: `evaluation.prob_edge`; fair line: quote `fair_line` — all straight from the frozen artifacts.
- Fair probability (display) = de-vigged market probability of the best side + the artifact's `prob_edge`. Kelly (display) = standard formula on that fair probability and the book price. The model's `actionable_stake` remains the authoritative stake.

## Verification

```bash
cd terminal
npm install
npm run typecheck     # tsc --noEmit
npm run build         # next build (production)
npm run verify:slate  # boots next start with PLAYWRIGHT=1, asserts the 6 failure modes on rendered HTML
npm run test:e2e      # Playwright (requires: npx playwright install chromium)
```

## What remains (not in this pass)

- Ambient risk context (exposure, cap remaining, gate thresholds as a persistent shell) — next up; a top bar or right rail, not a Slate Overview element.
- Table virtualization / density toggle — deferred until the Prop Board (Phase 4).
- Limit-likelihood flags / best-price routing — deferred until the soft-book routing model exists.
- CI wiring for the terminal workspace (Next install + build + Playwright with browser cache) — Phase 8 hardening.
- Deployment wiring (own Vercel project) — when the surface is production-ready.
- Phase 1 (`feat/phase1-foundation-freeze`) and Phase 2 (`feat/phase2-verification-layer`) branches still need rebase onto current main + push — queued separately.
