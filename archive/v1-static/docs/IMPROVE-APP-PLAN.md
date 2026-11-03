# Improve App Plan

## Context

- Started: 2026-10-24
- Product: PROP·WIRE, a responsive web terminal for quantitative player-prop research and execution.
- Core job: When a bettor finds a possible market edge before a line moves, they want to verify that the price is current and understand the recommended exposure, so they can act quickly without taking an untrusted or stale bet.
- Roughest flow: Find edge → verify price → place bet.
- First delivery target: execution slip, cross-book comparison, stale-line guard, and mobile-safe row detail.
- Evidence available: competitive analysis, current UI audits, and repository behavior; no customer interviews, recordings, or funnel analytics yet.
- Monetization surfaces: existing membership tiers. New performance guarantees, invented scarcity, and unsupported proof claims are out of scope.
- Primary platform: responsive web.

## Phase Status

| Phase | Skill | Status | Artifact | Date |
|---|---|---|---|---|
| 1 | jobs-to-be-done | done | CUSTOMER.md | 2026-10-24 |
| 2 | ux-heuristics | done | DESIGN.md, EXPERIMENTS.md | 2026-10-24 |
| 3 | design-everyday-things | done | DESIGN.md, EXPERIMENTS.md | 2026-10-24 |
| 4 | refactoring-ui | pending | DESIGN.md, EXPERIMENTS.md | |
| 5 | microinteractions | pending | DESIGN.md, EXPERIMENTS.md | |
| 6 | made-to-stick | pending | POSITIONING.md, EXPERIMENTS.md | |
| 7 | influence-psychology | pending | POSITIONING.md, EXPERIMENTS.md | |
| 8 | high-perf-browser | pending | DESIGN.md, EXPERIMENTS.md | |
| 9 | steve-jobs-design-review | pending | PRODUCT.md, DESIGN.md, EXPERIMENTS.md | |

Statuses: pending · in-progress · awaiting-evidence · done · deferred: &lt;reason&gt; · skipped: &lt;reason&gt;

## Key Decisions

| Date | Phase | Decision | Rationale |
|---|---|---|---|
| 2026-10-24 | Intake | Prioritize the repeated daily execution flow | The user confirmed the recommended “find edge → verify price → place bet” entry point. |
| 2026-10-24 | Intake | Treat responsive web as the primary platform | The current product and preview are browser-based. |
| 2026-10-24 | Intake | Do not add unsupported performance claims | Trust is part of the core job and the existing evidence does not support new guarantees. |
| 2026-10-24 | 1 | Treat the Little Hire as the primary leak | Daily price verification and action friction recur on every use, after signup. |
| 2026-10-24 | 1 | Functional trust is the worst underdelivery | Unverified or stale pricing prevents action and undermines confidence in every downstream control. |
| 2026-10-24 | 2 | Fix all severity-4 trust failures before building execution UX | The user confirmed that no execution slip should be built on a leaky trust boundary. |
| 2026-10-24 | 2 | Treat stale live data as historical research | Old or unverified prices must remain inspectable without appearing executable. |
| 2026-10-24 | 3 | Replace warnings with constraints for every trust-boundary failure | The user confirmed that stale, unverified, closed, unauthorized, incomplete, below-gate, and volatility-halted states must be impossible to log as wagers. |
| 2026-10-24 | 3 | Confirmation creates a wager record; undo handles reversible organization | External sportsbook activity cannot be undone by PROP·WIRE, while watchlist and ledger-removal actions can. |

## Next Actions

- [x] Confirm the Phase 1 job statement, worst underdelivered dimension, and Little Hire diagnosis (owner: product, completed: 2026-10-24).
- [x] Record Phase 1 findings in `CUSTOMER.md` after sign-off (owner: Codex, completed: 2026-10-24).
- [x] Audit the current execution flow against usability heuristics (owner: Codex, completed: 2026-10-24).
- [x] Confirm where constraints replace warnings and where undo replaces confirmation (owner: product, completed: 2026-10-24).
- [x] Implement and test the P0 client trust boundary (owner: Codex, completed: 2026-10-24).
- [ ] Connect paid entitlement to an authenticated server session; static viewer remains fail-closed until then (owner: backend, due: before paid launch).
- [x] Ship the smallest trustworthy execution slice and attach a pre-committed experiment metric (owner: Codex, completed: 2026-10-27).
