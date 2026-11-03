# Institutional terminal phase gate

This document records what the repository can prove before expanding the operator terminal. The Python model remains the pricing authority. The `terminal/` Next.js workspace is a separate, unpublished viewer; the Vercel production site still serves `viewer/`.

## Current gate: Phase 1 is incomplete

The repository has Pydantic `quant.v1` and `verification.v1` contracts, request ID logging, and a blocking CI job for their focused suites. That is useful groundwork, but it does not meet the master brief's Phase 1 done criteria:

1. `api/main.py` still has routes that parse arbitrary request JSON and return untyped dictionaries or `JSONResponse`. These routes lack a complete, generated request and response contract and uniform failure schema.
2. `tests/test_leakage.py` checks deterministic math and forbidden imports, but its own scope note says it does not prove feature-time cutoffs. `src/features.py` joins game lines and weather without a source observation timestamp. It also uses position medians computed across the whole loaded panel. Neither source can currently prove what was known at a particular pricing cutoff.
3. The live odds feed does not include the independent receipt and full Python gate decision required to promote a quote to `VERIFIED`.

Do not present Phase 1 or Phase 2 as complete or enable execution from the terminal until these conditions are resolved and tested in CI. Historical calibration and a manifest hash are not independent quote verification.

## Trust correction applied to the existing Slate Overview

- The terminal now checks the SHA-256 manifest against the exact feed bytes before rendering its quotes. A missing or mismatched manifest yields an empty, stale board.
- Synthetic quotes are excluded from the real route.
- The legacy `verified` boolean cannot produce a `VERIFIED` badge. Without a receipt-backed Python verification decision and gate clauses, the action remains locked.
- The terminal no longer calculates de-vig probability, Kelly, gate outcomes, or conflicts from raw prices. It displays a fair probability or Kelly fraction only if a frozen Python artifact supplies that value. Missing values display as unavailable.
- Invalid and future-dated observation timestamps are treated as unknown age, never fresh.

This is a fail-closed research surface. It does not by itself establish that the live data is verified or that the model has positive live edge.

## Required next work, in order

1. **Complete Phase 1:** define typed request, response, and error contracts for every FastAPI route. Add source observation timestamps to pregame context, build cutoff-aware features, and make a feature-time leakage test block CI. Preserve frozen research artifacts; any refit requires its own contract and evidence review.
2. **Complete Phase 2:** publish a receipt-backed Python `verification.v1` decision and full Python `quant.v1` gate clauses with each quote. Verify the feed manifest before the terminal reads it. Reject unverified, stale, or incomplete decisions.
3. **Reassess Phase 3:** integrate the new artifacts into the Slate Overview. Test the actual production data route and feed failure states. Add the terminal workspace to required CI before deployment.
4. **Proceed to Phase 4 and later only after the preceding gates pass:** build the board and line tool, append-only CLV ledger, risk surface, diagnostics, and hardening as separate verified phases.

## Local checks for the trust correction

From `terminal/`, run:

```bash
npm ci
npm run typecheck
npm exec -- next build --webpack
npm run verify:slate
```

The webpack flag avoids a Turbopack worker limitation observed in the local sandbox. It is not evidence of the default Vercel build time or deployment readiness.
