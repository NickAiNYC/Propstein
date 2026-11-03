# Improve Code Quality Plan

## Context

Started 2026-10-27. PropWire is a static quantitative sports research terminal on Vercel with a FastAPI control/data service designed for Railway. The worst failure is presenting stale, fabricated, unauthorized, or mutable data as actionable. The guarded execution path in `viewer/app.js` is the starting module. The current Node safety net is green; Python dependencies are not installed in this workspace. Production load is not yet evidenced, so scale work remains requirements-driven.

## Phase Status

| Phase | Skill | Status | Artifact | Date |
|---|---|---|---|---|
| 1 — Build the safety net | working-with-legacy-code | done | TESTING.md + TECH-DEBT.md (GATE) | 2026-10-27 |
| 2 — Make the code readable | clean-code | pending | TECH-DEBT.md | |
| 3 — Apply named refactorings | refactoring-patterns | pending | TECH-DEBT.md | |
| 4 — Reduce complexity | software-design-philosophy | pending | TECH-DEBT.md | |
| 5 — Draw the architecture boundary | clean-architecture | awaiting-evidence | ARCHITECTURE.md | 2026-10-27 |
| 6 — Lock in the habits | pragmatic-programmer | pending | TECH-DEBT.md | |
| 7 — Make it survive production | release-it | in-progress | RELIABILITY.md | 2026-10-27 |
| 8 — Size for real load | system-design | deferred: no measured production load | ARCHITECTURE.md + RELIABILITY.md | 2026-10-27 |
| 9 — Get the data layer right | ddia-systems | deferred: durable system of record not selected | ARCHITECTURE.md | 2026-10-27 |
| Optional — Domain language | domain-driven-design | pending | ARCHITECTURE.md | |

Statuses: pending · in-progress · awaiting-evidence · done · deferred: reason · skipped: reason

## Key Decisions

| Date | Phase | Decision | Rationale |
|---|---|---|---|
| 2026-10-27 | 1 | Treat the 93-test Node suite and production-readiness assertions as the safety gate. | It pins the highest-risk quote, execution, entitlement, feed-health, cache, and deployment behavior. |
| 2026-10-27 | 7 | Live market data must never be served from the service-worker or CDN cache. | An unavailable quote is safer than a stale quote presented as current. |
| 2026-10-27 | 7 | Production entitlement fails closed when Whop configuration is absent. | Missing configuration must not grant paid access. |
| 2026-10-27 | 7 | Use explicit CORS origins and header-only admin credentials. | Wildcard credentialed CORS and query-string secrets are unacceptable in production. |

## Next Actions

- [ ] Replace membership-ID bearer input with a signed first-party session and server-side subject binding (owner: backend, P0).
- [ ] Move ledger and settlement records to a durable transactional datastore with backups and restore drills (owner: backend, P0).
- [ ] Add production error reporting, RED metrics, and symptom alerts for feed age, entitlement failures, and API latency (owner: operations, P0).
- [ ] Complete legal review: Terms, Privacy, responsible-gaming language, age/region requirements, and marketing claims (owner: business/legal, P0).
- [ ] Install locked Python dependencies in CI and run the Python test suite (owner: engineering, P1).
- [ ] Record actual traffic, latency, and storage numbers before Phase 8 (owner: operations, P1).
