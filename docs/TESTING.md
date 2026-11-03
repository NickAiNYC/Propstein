# Testing

> Worst failure this app can commit: presenting **stale, fabricated, unauthorized,
> or mutable data as actionable**. The test suite exists to pin exactly those
> behaviors. If a change is behavior-visible and no test here goes red, the net
> has a hole — add the missing pin before shipping.

## Test Strategy

Node's built-in test runner provides domain, adapter, feed-health, rendering, migration, and execution-boundary coverage. `npm run check:production` is the release gate: syntax-check production browser files, run the full suite, and verify cache/security/deployment invariants. The Python suite runs in CI against the **locked** dependency set (`requirements.lock`); `tests/test_dependency_lock.py` fails the same CI run if the lock and `requirements.txt` intent spec ever drift apart.

## Gate

| Gate | Command | Status |
|---|---|---|
| Node suite | `node --test` | **100/100 green** @ 2026-10-27 (post-#13 main `d8b1d8a` and rebased `refactor/phase2-readability` @ 1f2f7d7) |
| Syntax | `node --check viewer/app.js` | part of `npm run check` |
| Python suite | `pytest test/ tests/` | **365 passed / 2 skipped** @ 2026-11-02 — CI installs `requirements.lock` (P0 closed, see Dependency Lock below) |

Rule: no behavior-visible change ships with the Node gate red. NFL parity goldens
(`test/nfl-parity.snapshot.mjs`) must stay untouched unless the diff is an
earned, documented whitelist delta.

## Safety Net Map

| Module | Pinned behaviors | Test files | Gaps |
|---|---|---|---|
| `viewer/app.js` | Quote verification, stale-feed failure, entitlement, execution confirmation, immutable ledger shape, sport rendering | `test/*.test.mjs`, `test/*.snapshot.mjs` | Browser E2E and assistive-technology flows |
| `viewer/sw.js` | Market data excluded from cache; release version matches HTML | `test/commercial-readiness.test.mjs` | Real offline-browser integration |
| `vercel.json` | Security headers and no-store data policy | `test/commercial-readiness.test.mjs` | Headers must also be probed after deployment |
| `api/main.py` | Fail-closed entitlement markers, CORS allowlist, header-only admin secret | `test/commercial-readiness.test.mjs` | FastAPI integration tests need Python dependencies |

## Dependency Lock (closed 2026-11-02)

- `requirements.txt` = intent spec (floor ranges). `requirements.lock` = the reproducible reality: a clean-venv freeze of that spec, 68 exact pins, **suite-validated before locking** (355 passed / 2 skipped at lock time — notably under pandas 3.1 / numpy 2.5, newer majors than dev used).
- CI installs the lock, never the ranges (`ci.yml`: both Python jobs). `pip-audit` audits the exact locked set.
- `tests/test_dependency_lock.py` (in the normal pytest run) pins lock↔spec consistency and the validated quant-stack majors — a range bump without a lock refresh, or a silent major rollover, fails CI.
- Refresh protocol is in the lock header: fresh venv → install spec → run the **full** suite → freeze → replace pins in the same PR.

## What the suite pins (17 files: 16 `.mjs` + `decision-gates.test.cjs`)

| Test file | Behavior pinned |
|---|---|
| `nfl-parity.snapshot.mjs` | NFL render goldens + DOM access log allowlist (audit B2) — the parity contract |
| `adapter-registry.test.mjs` | Sport adapter registration, default boot, require() guards |
| `sport-switcher.test.mjs` | Switcher chrome, per-sport boot pins (NFL 29/11/named-row), labels |
| `localstorage-migration.test.mjs` | Legacy→namespaced storage copy policy; legacy keys never deleted |
| `feed-health.test.mjs` | Feed age thresholds, health states, verification labels |
| `circuit-breaker-config.test.mjs` | Per-market breaker config fetch + fallback semantics |
| `odds-receipts.test.mjs` | Quote receipt/provenance behavior (never stale-quoted silently) |
| `top-plays.test.mjs` | EV-descending order, confidence/sample-size tie-breaks, hidden incomplete projections, `verified` ignored |
| `uncalibrated-badge.test.mjs` | UNCALIBRATED chrome on non-calibrated sports, absent on NFL |
| `nba-integration.test.mjs` | Both NBA nights: schema, provenance, injuries join regression, `verified:false` scan |
| `nba-injuries.test.mjs` | Availability pill, surge filter + driver badge, vacated_minutes gate, 64/64-ban, Oct-23 boot |
| `autonomous-telemetry.test.mjs` | Telemetry event contract |
| `render-robustness.test.mjs` | Malformed/partial rows must not crash the board |
| `fetch-nba-script.test.mjs` | Fixture-builder script contract |
| `commercial-readiness.test.mjs` | Landed with PR #13 (10 tests): entitlement fails closed, explicit CORS, header-only admin secret, SW excludes market data, release version matches HTML, Vercel security headers |
| `execution-trust-boundary.test.mjs` | Landed with PR #13: execution-path trust boundaries (what may and may not reach the guarded execution path) |
| `decision-gates.test.cjs` | Landed with PR #13: decision-gate contract (gate open/closed conditions) |

Note: `test/public-pages.test.mjs` (7 honesty/faithfulness tests for the B4
static pages) rides with PR #14 (`feat/public-pages`) — suite is 107/107 there.

## Out-of-band checks (manual, before merge of UI work)

Headless smoke on a **fresh port with service-worker unregistered** (SW cache
serves stale assets to repeat headless loads): app boots with zero page errors,
selector labels correct, availability drawer state correct across slate
switches, 390px viewport fits (`scrollWidth == clientWidth`).

## Characterization Backlog

- [ ] Add Playwright keyboard, touch, offline, and stale-to-fresh transition tests (high risk, P1).
- [ ] Add FastAPI tests for auth unavailable/invalid/active, readiness, CORS, and admin endpoints (high risk, P0).
- [ ] Exercise settlement concurrency against the selected durable datastore (high risk, P0).
- [x] Theme toggle contract — closed 2026-10-27: the dark-lock restyle removed the toggle entirely (app.js §11 dark-locks and clears stale `propwire-theme` keys), so there is no aria/persistence contract left to pin.

## CI Gates

- `npm ci`
- `npm run check:production`
- `pip install -r requirements.lock pytest` + `PYTHONPATH=. pytest test/ tests/` (locked set; includes the lock-consistency tests)
- `pip-audit` against the locked set (`continue-on-error` advisory)
- Vercel preview build
- Post-deploy header and feed-cache probe (to add)

## Baseline history

| Date | Branch | Suite | Note |
|---|---|---|---|
| 2026-10-27 | `feat/nba-section` @ 396f0e8 | 90/90 | pre-refactor baseline |
| 2026-10-27 | `refactor/phase2-readability` @ f7c6a6e (base 4b27731) | 90/90 | after phase-2 readability pass (comments + dead-code removal only) — parity goldens untouched |
| 2026-10-27 | main @ d8b1d8a (PR #13 merged) | 100/90+10 | commercial-readiness/execution-trust-boundary/decision-gates tests joined the suite |
| 2026-10-27 | `refactor/phase2-readability` @ 1f2f7d7 (rebased on d8b1d8a) | 100/100 | phase-2 re-verified on new main; app.js conflict resolved (theme block kept live) |
| 2026-10-27 | `feat/public-pages` @ 5c657e1 (PR #14) | 107/107 | +7 public-pages tests |
| 2026-11-02 | `feat/python-lockfile` | pytest 365 passed / 2 skipped | +10 dependency-lock consistency tests; CI now installs `requirements.lock` |

Number-of-record note: the quality plan text references a "93-test" suite; the
measured gate at the phase-2 base was 90 and is 100 post-#13. Treat the
**measured** count as the number of record; discrepancies are recorded here,
not silently absorbed.
