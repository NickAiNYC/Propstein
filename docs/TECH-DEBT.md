# Technical Debt — Improve Code Quality Plan (living tracker)

> Started 2026-10-27. PropWire is a static quantitative sports research
> terminal on Vercel with a FastAPI control/data service designed for Railway.
> Worst failure: presenting stale, fabricated, unauthorized, or mutable data
> as actionable. Starting module: the guarded execution path in
> `viewer/app.js`. Production load is not yet evidenced — scale work stays
> requirements-driven.

## Debt Ledger

| Item | Location | Type | Risk | Effort | Priority | Status |
|---|---|---|---|---|---|---|
| Signed user session and subject-bound entitlement | `api/main.py` | security | Critical | Medium | P0 | Open |
| Durable transactional ledger | API/ledger | data integrity | Critical | Large | P0 | Open |
| Production error and feed-age monitoring | frontend/API | operability | High | Medium | P0 | Open |
| Python dependency lock and CI test job | `requirements.txt`, CI | reproducibility | High | Medium | P1 | **Closed 2026-11-02** (`requirements.lock` + lock-consistency tests in the suite; CI installs the lock) |
| Browser E2E/accessibility regression suite | viewer | quality | Medium | Medium | P1 | Open |
| Duplicate root/public/viewer assets | repository | maintainability | Medium | Medium | P1 | Open |
| Monolithic browser application | `viewer/app.js` | maintainability | Medium | Large | P2 | In progress (phase-2 pass 1 done; **phase-3 pass 1 done 2026-11-02: §22 quant math extracted to `viewer/js/quant-math.js` behind golden characterization tests**; T1–T8 queued) |

## Smell Inventory

| Smell | Location | Refactoring | Status |
|---|---|---|---|
| Multiple divergent deployment copies | root, `public/`, `viewer/` | Establish Single Source of Truth | Ticketed |
| Large IIFE mixing state, rendering, and policy | `viewer/app.js` | Extract Module behind characterization tests | Ticketed — navigability mitigated by MODULE MAP (§-banners) pending structural extraction |

## Sprout / Wrap Register

Commercial readiness assertions were added beside the legacy suite in `test/commercial-readiness.test.mjs`; fold them into a dedicated deployment integration layer when browser/API integration tests exist.

## Phase status

| Phase | Skill | Status | Artifact | Date |
|---|---|---|---|---|
| 1 — Build the safety net | working-with-legacy-code | done (re-materialized) | docs/TESTING.md + this file | 2026-10-27 |
| 2 — Make the code readable | clean-code | **done (pass 1)** | this file, app.js MODULE MAP | 2026-10-27 |
| 3 — Apply named refactorings | refactoring-patterns | pending | this file | |
| 4 — Reduce complexity | software-design-philosophy | pending | this file | |
| 5 — Draw the architecture boundary | clean-architecture | awaiting-evidence | ARCHITECTURE.md | 2026-10-27 |
| 6 — Lock in the habits | pragmatic-programmer | pending | this file | |
| 7 — Make it survive production | release-it | in-progress | docs/RELIABILITY.md | 2026-10-27 |
| 8 — Size for real load | system-design | deferred: no measured production load | ARCHITECTURE.md + docs/RELIABILITY.md | 2026-10-27 |
| 9 — Get the data layer right | ddia-systems | deferred: durable system of record not selected | ARCHITECTURE.md | 2026-10-27 |
| Optional — Domain language | domain-driven-design | pending | ARCHITECTURE.md | |

Artifact provenance: `docs/RELIABILITY.md` and the `docs/` plan set
(CUSTOMER/DESIGN/EXPERIMENTS/IMPROVE-*-PLAN) landed with PR #13 (thin
originals — expand on next touch). `ARCHITECTURE.md` content from the
2026-10-27 planning session still never landed anywhere — re-materialize on
next touch of phases 5/8/9. Root-level `TESTING.md`/`TECH-DEBT.md` were
consolidated into this `docs/` set with the phase-2 PR (root copies removed).

## Key decisions

| Date | Phase | Decision | Rationale |
|---|---|---|---|
| 2026-10-27 | 1 | The Node suite + parity goldens are the safety gate (90 at phase-2 base; 100 post-#13). | Pins highest-risk quote, execution, entitlement, feed-health, cache, deployment behavior. |
| 2026-10-27 | strategy | Own "most trustworthy NFL player-prop decision terminal", not sport breadth (IntelliPickz benchmark). | Trust/audit moat beats breadth; adapter architecture enables later expansion. |
| 2026-10-27 | 7 | Live market data must never be served from service-worker or CDN cache. | An unavailable quote is safer than a stale quote presented as current. |
| 2026-10-27 | 7 | Production entitlement fails closed when Whop configuration is absent. | Missing configuration must not grant paid access. |
| 2026-10-27 | 7 | Explicit CORS origins; header-only admin credentials. | Wildcard credentialed CORS and query-string secrets are unacceptable in production. |
| 2026-10-27 | 2 | Cache-bump convention: user-visible viewer-asset changes bump the cache triple coherently (index `?v=` ×5, sw cache name + precache, build-hash) in the same PR; comments-only JS deltas do not require a bump. | Prevents the v134/v135-style cross-PR cache-line conflicts while still forcing client refresh for real changes. |
| 2026-10-27 | restyle | Dark-lock + baby-blue brand (FanDuel calibration): the terminal is dark-only. PR #13's light/dark toggle is removed; app.js §11 dark-locks at boot and clears stale `propwire-theme` keys. The `[data-theme="light"]` CSS hooks stay dormant — restoring light = re-add the toggle + revert §11. Brand accent lime → baby blue (`#7dd3fc` family), slate-gray surfaces unified to navy (`#0f131a` family), primary text → white; semantic emerald/amber/red untouched. Cache v143 → v144 + build-hash 2026-w7-v9 in the same PR. | One presentation removes the three-cascade palette fight (`:root` ×3) and the maintenance surface of a half-used light theme; brand vs semantic color separation is now explicit. |
| 2026-11-02 | dep-lock | `requirements.txt` is the intent spec; `requirements.lock` (clean-venv freeze, suite-validated at lock time) is what CI installs. Lock↔spec consistency and the validated quant-stack majors are pinned by `tests/test_dependency_lock.py` inside the normal pytest run. | Reproducible CI + fail-closed drift detection without giving up the documented floor ranges. |

## Phase-3 pass 1 record (2026-11-02, branch `feat/appjs-quant-math-extraction`)

Target: §22 (odds & distribution math) — NOT one of the named T1–T8 targets,
but the section with the best effort/risk profile: pure functions, no state,
no DOM, and the highest-value thing to make independently testable (it IS
the frozen model). Discipline followed (per the phase constraint):

1. **Characterize first**: fixtures generated from the live pre-extraction
   implementation (`scripts/generate_quant_goldens.mjs`), asserted with exact
   double equality — 8 golden tests green BEFORE the move, green after.
2. **Extract**: `viewer/js/quant-math.js` — `window.PropWireMath` (same
   fail-fast namespace pattern as the sport registry), `createQuantMath({
   alpha, k })` binds the adapter's model constants. Formulas byte-identical.
3. **Wire**: script tag before app.js; app.js §22 destructures the module
   surface; `targetLine` stays in app.js (reads `state` — the module must
   never see mutable state). Cache triple bumped coherently: index `?v=`
   2026_v213→v214 (style.css + app.js + new quant-math.js), sw CACHE_NAME
   v213-snapshot-age→v214-quant-math + precache entry, build-hash
   2026-w8-v31→v32.
4. **Extend the net**: +3 module tests (standalone load in a bare VM with no
   app.js/adapters; app.js binds the exact module export objects; null-model
   constants yield NaN, never a plausible probability).

Gate: 143 pass marks (132 + 11 new golden/module tests), same 7 pre-existing
extensions failures, NFL parity goldens byte-untouched. app.js shrank by
~120 lines; the model is now testable without booting the app.

## Phase-2 pass record (2026-10-27, branch `refactor/phase2-readability`)

Behavior-preserving (comments + names only at merge time); gate green
(90/90 at base 4b27731, 100/100 after rebase onto d8b1d8a); parity goldens
untouched. Changes to `viewer/app.js`:

- **MODULE MAP header** after `'use strict'`: 22 numbered sections + the three
  editing invariants (single `state` store; quote acceptance only via
  `evaluateRow` §16; live data never cached).
- **22 section banners** (`// ── §N. … ──`) at function-cluster boundaries —
  the file had 2 banners for ~130 functions / 5.25k lines.
- **Dead-code removal — superseded by merge**: at base 4b27731 the
  `initTheme()`/`toggleTheme()` stubs were empty and uncalled, so pass 1
  deleted them. PR #13 then shipped a **live** theme system (boot-dark,
  header toggle, localStorage persistence, meta theme-color); the rebase kept
  the implementation in §11 and replaced the removal comment with an accurate
  one. Superseded 2026-10-27: the dark-lock restyle removed the toggle and
  rewrote §11 (see Key decisions) — no toggle contract exists to pin.
- **Named constant**: `CLV_ROOT_HASH_FALLBACK` replaces the inline
  `'207ba3d4c4225c1d'` literal in `updateClvFooter` (see §R1).

## Risk register (flagged for later phases)

| ID | Finding | Where | Phase | Note |
|---|---|---|---|---|
| R1 | Hardcoded CLV ledger root-hash fallback presented as data (`Root #…`) | `updateClvFooter` (§13), constant at §4 | 3 | Now named + flagged; decide whether a display fallback hash should exist at all |
| R2 | Client-side `state.userTier` defaults to `'sharp'` from localStorage | `state` (§4), `logBet` (§18) | 7 | Server-side entitlement (Whop) is the authority; UI tier is presentation only |
| R3 | One-off UI timing literals inline (600/380/240/350/800/2500/220 ms) | various §7/§10/§13/§17 | 3 | Each used once — acceptable inline; extract only if they start repeating |
| R4 | `state.bankroll` floor `100` and default `5000` inline in §4 | `state` init | 4 | Semantically load-bearing for Kelly sizing |

## Phase-3 / Phase-4 targets (named refactorings, in priority order)

Line ranges are as of the phase-2 commit; § refs are stable (see app.js MODULE MAP).

| # | Target | Size | Pattern (phase 3) → Outcome (phase 4) |
|---|---|---|---|
| T1 | `bindControls` (§9) | ~500 lines | Extract Function per control family → event-binding registry; eliminate the god-listener |
| T2 | `detailMarkup` (§21) | ~250 lines | Extract Function per card region → composed template parts |
| T3 | `openPortfolioDialog` (§19) | ~200 lines | Extract render/compute separation |
| T4 | `renderSniperModal` (§14) | ~195 lines | Extract field-group builders; config read/write split |
| T5 | `renderDetailModal` (§21) | ~180 lines | Merge with T2 composition once extracted |
| T6 | `openClvReport` (§19) | ~145 lines | Extract KPI computation from markup |
| T7 | `evaluateRow` (§16) | ~130 lines | **Do not restructure casually** — guarded core; extract only with parity tests green and each step commit-isolated |
| T8 | `propCard` (§15) | ~155 lines | Extract badge/pill builders shared with tableRow |

Constraint for all targets: gate stays green per extracted function
(`node --test` after every step); no behavior deltas, no data-shape changes.

## Competitive benchmark — IntelliPickz (owner brief, 2026-10-27)

Positioning: **do not chase 13-sport breadth**. Win one category — *the most
trustworthy NFL player-prop decision terminal* — via faster verified pricing,
clearer execution states, deeper evidence, superior auditing. Expand sports
later through the adapter architecture once retention proves the workflow.
IntelliPickz wins breadth/discoverability/packaging; the moat here is making
every recommended row auditable in under five seconds.

Owner build order:

| # | Build | Maps to |
|---|---|---|
| B1 | **Real cross-book ingestion** — per actionable row: best line+odds, book name/logo, books-compared count, quote age, consensus line, sharp reference, model fair, de-vigged edge, "price changed" state pre-confirm; freshness visible everywhere (their refresh: 15 min — beat it) | NEW **P0 — blocked on data-provider selection** (which books, delivery mechanism, licensing) |
| B2 | **Signed commercial authentication** — first-party session, server-side subject binding | Debt Ledger P0 (existing) |
| B3 | **Durable ledger** — transactional datastore, backups, restore drills | Debt Ledger P0 (existing) |
| B4 | **Public performance + player/prop pages** — indexable (`/nfl/players/<slug>/receiving-yards`, `/nfl/games/<matchup>`, `/performance/2026/week-7`): historical lines, hit rates, distributions, injury context, model limitations; live pricing stays behind auth | **P1 — BUILT, PR #14 open** (780 player-market pages, 2 market boards, /performance, /methodology, sitemap, honesty invariants pinned by test) |
| B5 | **Decision view** — two-mode terminal (Decision: player/book/line/fair/edge/status/review; Research: current depth), 3-step first-run guide (find → understand a row → review safely, dismissible), sell the repeated job not "more data" | NEW **P1** |

Evidence record over marketing ("8–0 is marketing; a versioned 500-decision
calibration record is a moat"): every recommendation timestamped pre-kickoff,
open/recommended/close prices, CLV distribution, win rate with n, calibration
by predicted-probability bucket, ROI with CI, max drawdown, splits by sport /
market / model version, losing weeks shown. The CLV ledger + audit surfaces
already exist — extend, don't rebuild.

Commercial trust layer (pre-billing blockers): B2 + B3 + monitoring P0s, plus
the legal content pack (Terms, Privacy, cookies, responsible gaming,
cancellation/refund, age & jurisdiction) — tracked in Next Actions.

Packaging direction: Observer free (delayed lines, ranges, history) / Sharp
$29 (live comparison, watchlists, alerts) / Quant $49–59 (execution review,
portfolio exposure, ledger, exports, audit). **Entitlements server-side; the
client-controlled membership switcher must not return** (aligns with risk R2).

## Debt Budget & Broken-Windows Policy

Reserve at least 15% of each release for reliability/security debt. P0 trust, auth, stale-data, or ledger defects block release. Every TODO that affects a trust claim must have an owner and priority here.

## Adopted Conventions

- Production configuration fails closed.
- Live decision data is network-only; offline mode is research-shell only.
- Secrets travel in headers, never URLs.
- Browser origins are allowlisted explicitly.
- Production source files, not historical duplicates, are syntax-checked in CI.
- Cache triple bumps are coherent and ride with the PR that changes user-visible viewer assets (see Key decisions).

## Next actions

- [ ] Replace membership-ID bearer input with a signed first-party session and server-side subject binding (owner: backend, P0).
- [ ] Move ledger and settlement records to a durable transactional datastore with backups and restore drills (owner: backend, P0).
- [ ] Add production error reporting, RED metrics, and symptom alerts for feed age, entitlement failures, and API latency (owner: operations, P0).
- [x] ~~Complete legal review: Terms, Privacy, responsible-gaming language, age/region requirements, and marketing claims (owner: business/legal, P0).~~ — boilerplate shipped 2026-10-27: generated pages at `/legal/terms/`, `/legal/privacy/`, `/legal/responsible-gaming/` (site-wide footer links, sitemap, tests). **Not legal advice** — owner must fill `[STATE]`/`[CONTACT EMAIL]`/`[HOSTING PROVIDER]` placeholders and have counsel review before relying on them.
- [x] ~~Install locked Python dependencies in CI and run the Python test suite~~ (owner: engineering, P1) — closed 2026-11-02: `requirements.lock` (68 pins, clean-venv freeze of the spec, full-suite-validated before locking), CI installs the lock in both Python jobs, `tests/test_dependency_lock.py` pins lock↔spec consistency + validated majors, `pip-audit` audits the locked set. Refresh protocol lives in the lock header + docs/TESTING.md §Dependency Lock.
- [ ] Record actual traffic, latency, and storage numbers before Phase 8 (owner: operations, P1).
- [ ] B1: real cross-book ingestion — start with a data-provider decision (owner: engineering, **P0, blocked on provider selection**). Full schema + capture cadence + API contract now speced in **docs/B1-LINE-HISTORY-SPEC.md** (decision table §2, DDL §3, rollout §7) — the spec exists so the decision can be made in one sitting and capture starts same-day; every week uncaptured is history that cannot be backfilled.
- [ ] B4 v2: game pages + per-week regeneration of the public pages (owner: engineering, P1 — after PR #14 lands); pricing page needs product input.
- [ ] B5: Decision view default mode + 3-step onboarding guide (owner: engineering, P1).
- [ ] Resolve §R1 (root-hash fallback) during Phase 3 (owner: engineering).
- [x] ~~Pin the theme toggle contract with a test~~ — closed 2026-10-27: the dark-lock restyle removed the toggle (app.js §11; Key decisions row), so the contract no longer exists.
- [ ] Re-materialize ARCHITECTURE.md and expand thin docs/RELIABILITY.md from the 2026-10-27 planning session (owner: engineering, next touch of phases 5/7).
- [x] Cache state: main @ v142; PR #16 (brand lockup v2/v3) carries coherent v143; the dark-restyle PR is stacked on #16 and carries v144 + build-hash 2026-w7-v9 — merge #16 first, then the restyle, to keep the triple coherent at every merge point.
- [x] 2026-10-27 post-merge: #16+#17 merged (main @ 7a4adad, v144 live tree), 10 merged branches deleted; owner manual checklist — Vercel Deployment Protection OFF for prod (site currently 302s behind auth wall), PAT revoke, repo settings (description/topics/branch-protection/security toggles need Administration permission the current PAT lacks).
