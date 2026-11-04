# PropStein Live Sniper — Extension Monorepo

Browser companion that detects **visible** live markets on the active tab,
normalizes them against the PropStein quant stack, and shows model
probability, fair odds, EV and signal validity in a terminal-grade side
panel.

**Intelligence only. It never places, prepares, or submits a wager.**
**It never collects credentials, never bypasses anti-bot systems, and only
reads markets the user can already see in their own viewport.**

---

## Package layout

```
extensions/
├── packages/
│   ├── core        @propstein/core      — market types, odds math, normalizer,
│   │                                    matcher, DRIVE-REC-V1, freshness,
│   │                                    signal state machine, lifecycle
│   ├── detection   @propstein/detection — visibility filter, adaptive-batched
│   │                                    DOM differ, adapter registry,
│   │                                    DemoBook adapter + DK/FD/Polymarket
│   │                                    scaffolds (feature-flagged OFF)
│   ├── browser     @propstein/browser   — origin-validated messaging,
│   │                                    untrusted-payload validation,
│   │                                    per-origin site permissions
│   └── ui          @propstein/ui        — React terminal panel (signal cards,
│                                        entitlement gate, state views)
├── apps/
│   └── chrome                           — MV3 app: background service worker,
│                                        content bridge (isolated world),
│                                        side panel + web companion
├── demo/                                — synthetic DemoBook fixture page
├── scripts/build.mjs                    — esbuild → dist/* (prod/dev/companion)
└── tests/
    ├── unit/                            — 109 core tests (node --test, TS native)
    ├── integration/                     — 24 detection tests (linkedom fixtures)
    └── e2e/                             — 6 Playwright scenarios (real Chromium,
                                                                                 real MV3 load)
```

Server counterpart: `api/extension_router.py` in the repository root
(scoped session tokens, kill switch, model coverage — see
`docs/LIVE_SNIPER_AUDIT.md` for the decision matrix).

## Quickstart

```bash
cd extensions
npm install                # Node >= 22.6 (Node 24 runs TS tests natively)

npm run typecheck          # tsc --noEmit across all packages
npm run test:core          # 133 unit + integration tests
npm run build              # esbuild → dist/propstein-chrome{,-dev} + companion

# Browser e2e (needs Playwright's chromium once):
npx playwright@1.57.0 install chromium
npm run test:e2e           # 6 scenarios, ~6s

# Local demo loop (fixture page + API dev bypass):
npm run demo               # serves demo/demo-sportsbook.html on :4173
APP_ENV=development PROPWIRE_ALLOW_DEV_AUTH_BYPASS=1 ALLOW_INSECURE_DEV_TOKENS=1 \
  uvicorn api.main:app --port 8000    # from the repository root; or set EXTENSION_SESSION_SECRET instead of the insecure-token flag
```

### Loading the extension

1. `npm run build`
2. `chrome://extensions` → Developer mode → **Load unpacked**
3. Pick `extensions/dist/propstein-chrome-dev` (grants `localhost:4173`
   for the demo) or `dist/propstein-chrome` (production manifest).
4. Open the demo fixture (`npm run demo` → http://localhost:4173/demobook),
   open the Live Sniper side panel, **SIGN IN** (dev bypass accepts any
   non-empty token), press **START MONITORING**.

## The signal pipeline

### Read-only trial status (2026-10-31)

Only DemoBook is enabled. Its drive context and model are synthetic and are
labeled as such in the panel. DraftKings, FanDuel, and Polymarket adapters
remain disabled. A sportsbook DOM drive ID is never treated as an independent
possession feed. Real drive signals require a separate feed with matching
event and drive IDs, a fresh source timestamp, and a prospectively calibrated
model. Until those inputs exist, the extension cannot provide live NFL betting
alerts.

The service worker appends observed events and decisions to a local IndexedDB
trial journal. Use **EXPORT TRIAL LOG** in the panel to save a JSONL copy for
review. If the journal cannot be opened or written, monitoring stops. The log
is local to the browser profile; export it before removing the extension or
clearing browser data.

```
sportsbook tab (visible DOM only)
  └─ content bridge (isolated world, read-only, opt-in per origin)
       └─ adapter (versioned selectors, confidence-scored parse)
            └─ ObservedMarket  [canonical schema, OBSERVED provenance]
                 └─ normalizer → matcher (roster + coverage)
                      └─ model (DRIVE-REC-V1 · SYNTHETIC DEMO PARAMETERS)
                           └─ signal state machine
   DETECTED → NORMALIZED → MODEL_MATCHED → VALIDATED
                                        ├→ ALERTABLE
                                        ├→ BELOW_THRESHOLD
                                        ├→ UNVERIFIED
                                        ├→ STALE
                                        ├→ SUSPENDED
                                        └→ MODEL_UNAVAILABLE
                                └─ panel (side panel / companion)
```

A signal is `ALERTABLE` only when ALL of: visible, matched, model-covered,
open, above the EV threshold *after* the uncertainty haircut, fresh, and
bound to the live possession. Any failure withdraws it — withdrawals render
in the panel with their reason (auditable, never silent). Hysteresis
(enter +5% / exit +3% post-haircut) plus alert cooldown guard against
oscillation.

## Iron rules (enforced in code, not just docs)

1. **Never place bets.** The content bridge has no click/submit code paths;
   it reads DOM only, and its header comment is a contract.
2. **Never collect credentials.** No login forms, no password fields, no
   storage of sportsbook cookies. The only credential is a PropStein
   membership token the user pastes into the panel, exchanged server-side
   for a 15-minute scoped token held in memory-backed
   `chrome.storage.session`.
3. **Never bypass anti-bot systems.** No headless spoofing of the
   sportsbook itself; the extension observes whatever the user's own browser
   legitimately renders.
4. **Only visible markets.** The detection layer filters to elements
   intersecting the active viewport; hidden/infinite-list cards are not
   analyzed. Monitoring pauses when the tab loses focus.
5. **No fabricated numbers.** Everything from the page is labeled
   `OBSERVED`; everything from the model carries its model version and
   confidence label (`UNCALIBRATED` today — honestly); real-book
   drive-level markets show `NO MODEL COVERAGE` until a licensed possession
   feed and calibration corpus exist.

## Adapter authorization model

| Platform  | Status | Mechanism |
|-----------|--------|-----------|
| `demobook`| ON     | Synthetic fixture — the fully tested surface |
| `draftkings` | OFF | Feature flag in the content bridge registry; requires written authorization + validated selectors + remote kill-switch config before enable |
| `fanduel` | OFF | Same |
| `polymarket` | OFF | Same — the licensed Gamma/CLOB API is the preferred channel (per repo audit) |

Enabling a real adapter is an operational act (flag + reviewed selector set
+ audit sign-off), never a code default. See
`docs/LIVE_SNIPER_ADAPTERS.md` for the rollout checklist.

## Server API (v1)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET  /api/v1/extension/health` | public | Kill switch + minimum extension version |
| `POST /api/v1/extension/session` | Whop membership | Issue 15-min scoped token (fail closed) |
| `POST /api/v1/extension/session/revoke` | scoped token | Revoke by `jti` |
| `GET  /api/v1/markets/model-coverage` | scoped token | Roster + coverage verdicts |
| `POST /api/v1/markets/evaluate` | scoped token | DRIVE-REC-V1 evaluation |

Deploy note: add the packaged `chrome-extension://<id>` origin to
`ALLOWED_ORIGINS` (operator action, audit S-5).

## Test matrix

| Suite | Count | What it proves |
|---|---|---|
| `tests/unit/` | 109 | Odds math exactness (spec §7: +160 → 38.46% break-even, EV formulas), normalizer, matcher, DRIVE-REC-V1 numerics, freshness, state machine transitions incl. all withdrawal paths, lifecycle hysteresis/dedup |
| `tests/integration/` | 24 | Visibility filter, adaptive batching, change differencing (ADDED/ODDS_CHANGED/LABEL_CHANGED/SUSPENDED/REMOVED/NAVIGATED), DemoBook adapter against linkedom fixtures |
| `tests/e2e/` | 6 | Real Chromium + real MV3 extension: spec §15 critical scenarios — +160→+115 recompute, suspension withdrawal, drive-end invalidation, plus panel bootstrap and stop |
| repo `tests/test_extension_api.py` | 24 | Server entitlement/token/kill-switch/rate-limit/coverage-honesty contract |

Everything above is green in CI order: `npm run typecheck && npm test`.
