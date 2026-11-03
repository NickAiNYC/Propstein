# Experiments

## Experiment Cards

### EXP-001 — Trusted execution boundary

- Hypothesis: We believe users will complete more valid review-to-ledger actions with fewer invalid attempts if every price-dependent control is governed by one fail-closed trust boundary because the interface and mutation path will communicate the same rules.
- Type: instrumented usability test
- Primary metric & threshold (pre-committed): 100% of stored live ledger entries have a verified receipt, complete book/line/odds, a fresh timestamp, and an actionable gate decision.
- Guardrail metric: zero fabricated quote mutations and zero client-side entitlement escalations.
- Decision rule (pivot / persevere / iterate): Persevere when all trust invariants pass automated tests and 5/5 task-test participants correctly identify why a blocked row cannot proceed; iterate on copy or hierarchy if invariants pass but comprehension falls below 5/5; stop release if any invariant fails.
- Result & verdict: Pending.

### EXP-002 — Historical-mode fallback

- Hypothesis: We believe users will retain confidence during feed outages if stale data visibly transitions to research mode and preserves the last trusted snapshot because the product will no longer imply that old prices are actionable.
- Type: scenario usability test
- Primary metric & threshold (pre-committed): 5/5 participants identify the feed as stale and do not attempt a live execution from historical mode.
- Guardrail metric: projections and audit history remain usable; recovery does not discard the last trusted snapshot.
- Decision rule (pivot / persevere / iterate): Persevere at 5/5 correct interpretation; iterate below 5/5; block release if any live action remains enabled in stale mode.
- Result & verdict: Pending.

## Experiment Backlog

| Idea | ICE (impact/confidence/ease) | Status |
|---|---|---|
| Centralize verification, freshness, entitlement, quote completeness, gate, closure, and volatility into one execution decision | 10 / 9 / 7 | accepted — P0 |
| Remove static-feed mutation and false “verified” refresh copy | 10 / 10 / 9 | accepted — P0 |
| Replace client tier switching with server-validated entitlements | 10 / 10 / 5 | accepted — P0 |
| Add explicit historical/research mode with last-trusted timestamp | 9 / 9 / 7 | accepted — P0 |
| Add a focused execution review slip | 9 / 8 / 6 | implemented — measurement pending |
| Add inline refresh progress, failure cause, and retry feedback | 8 / 9 / 8 | accepted — P1 |
| Replace hover-only help with accessible popovers | 6 / 10 / 9 | implemented for model-only rows — P2 |
| Progressively render or virtualize the 390-row research slate | 6 / 8 / 6 | accepted — P2 |
| Replace volatility override confirmation with an enforced halt and research-only path | 10 / 10 / 9 | accepted — P0 |
| Require explicit external-wager confirmation before ledger creation | 9 / 9 / 7 | implemented — measurement pending |
