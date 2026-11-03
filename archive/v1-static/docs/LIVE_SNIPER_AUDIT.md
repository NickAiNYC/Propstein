# PropStein Live Sniper — Repository Audit (Mandatory §1)

**Auditor:** PropStein Engineering (extension workstream)
**Date:** 2026-10-30
**Branch:** `feat/live-sniper-foundation` (branched from `main` @ `c6789eb8`)
**Scope:** Full audit of `NickAiNYC/Propstein` (1,208 tracked files, 324 commits) to determine what the Live Sniper browser companion can reuse, what must be built, and what is unsupported.

---

## 1. Executive Summary

PropStein is a real, working product: a FastAPI backend (`api/main.py`, 1,703 lines, deployed on Railway) plus a vanilla-JS quant terminal (`viewer/`, deployed statically on Vercel at `propstein.vercel.app`, verified live at audit time — NFL 2026 W8 slate, stale-kill-switch messaging visible in production). It already ships: multi-provider odds ingestion, a walk-forward-validated full-game NFL receiving model, a LangGraph agent pipeline with a five-gate alert discipline, SSE streaming, CLV ledger and receipts, and Stripe + Whop monetization with server-side entitlement checks.

**Nothing resembling active-screen market detection exists anywhere in the repository.** The existing Chrome extension ("PropWire" v1.2.0) is a side-panel wrapper around the static terminal: no content scripts, no DOM inspection, no authentication, and a stale `host_permissions` entry. Live Sniper is therefore greenfield on the detection side, but it can reuse a substantial amount of proven infrastructure: the packaging pipeline, entitlement services, odds contracts, freshness/kill-switch philosophy, SSE patterns, design tokens, and test conventions.

**The single most important negative finding:** the receiving model is full-game scope. There is no possession-level or drive-level probability model, no NFL live play-by-play source, and no calibration corpus for drive-level reception markets. Drive-level markets must be built as a new model with its own evidence trail, and must show `NO MODEL COVERAGE` until calibrated.

---

## 2. What Exists — Verified Inventory

### 2.1 Backend (FastAPI, `api/main.py`, Railway)

| Area | Finding |
|---|---|
| **Auth / entitlement** | `verify_entitlement()` (main.py:83) validates a Whop membership server-side (`api.whop.com/api/v2/memberships`) from a `Bearer` token; **fail-closed** (503) when `WHOP_API_KEY` unset, with an explicit local-dev bypass (`PROPWIRE_ALLOW_DEV_AUTH_BYPASS=1`, non-production only). `BillingService.check_user_entitlement()` (src/services/billing.py:275) resolves tier: master API key → Stripe subscription (TruthStore) → Whop fallback → free. |
| **Internal API keys** | `require_internal_api_key()` (main.py:1130) gates private sniper routes via `X-PropStein-API-Key`/`X-PropWire-API-Key` or Bearer, using `secrets.compare_digest`. Single shared server key, not per-user. |
| **Billing hardening** | Checkout/portal endpoints authenticate a principal **before** any Stripe call, derive user_id server-side (body user_id ignored), clamp redirects to app origin (anti-phishing), enforce 3 req/min sliding-window rate limit per principal+IP, and process Stripe webhooks only with valid HMAC-SHA256 signatures — unsigned events fail closed. |
| **Sniper engine** | `SniperTerminalEngine` (src/agents/graph.py) — LangGraph + Redis Streams + truth store. Endpoints: `/api/sniper/feed`, `/polymarket`, `/live-board`, `/court-lineups`, `/arb-board`, `/simulate-*`, `/explain`, `/history`, `/receipt/{id}`, and **SSE `/api/sniper/stream`** (events: `snapshot`, `sniper_alert`, `heartbeat`). |
| **Alert discipline** | `SniperAgent` enforces **five fail-closed gates** (test/test_sniper_gate.py): edge threshold (incl. NFL W1 10% special gate), confidence, stale kill switch, thin liquidity, low CLV expectation. Suppression is logged, never silent. |
| **Freshness invariants** | `StaleKillSwitch` (src/agents/stale_kill_switch.py): injury 90s live / 300s pregame; lineup 45s / 300s; **odds 20s live / 60s pregame**; expected cadence NBA 5s, NFL live 30s, pregame 900s. Stale ⇒ alerts suppressed. |
| **CLV infrastructure** | Immutable snapshots (`/api/snapshots`, `/api/freeze`), user-scoped JSONL pick logs with path-traversal-safe user ids, settlement clearinghouse (`/api/v1/settle`, admin token), 3-stage SHA-256 receipt chain + public `/verify/{alert_id}` landing page. |
| **Data endpoints** | `/api/games`, `/api/slate`, `/api/picks`, `/api/performance`, `/api/live-odds`, `/api/ingest-odds`, `/api/injuries`, `/api/v1/edges` (Postgres/SQLite MarketEdge with 12% anomaly quarantine ceiling), `/api/v1/diagnostics`. |

### 2.2 Data Providers (`src/odds_adapter.py`, 1,648 lines)

| Provider | Role | Notes |
|---|---|---|
| **PropLine** (`api.propline.com/v1`) | **Primary DK/FD player-props feed** (`PROPLINE_API_KEY`) | Licensed aggregator — DraftKings/FanDuel data arrives via a commercial API, **not** page scraping. This is materially important for compliance posture. |
| **The Odds API** | Fallback provider (`ODDS_API_KEY`) | Pregame props; no drive-level markets. |
| **Bovada** | Free live NFL props endpoint (direct) | Includes browser-ish headers + retry; documented as "live". |
| **SportsGameOdds** | Additional provider | Normalizer preserves book deeplinks. |
| **Polymarket** | Gamma API + CLOB + WebSocket | Used by the arb agent (`mispricing_bps * liquidity_score` ranking). |
| **NBA live PBP** | `cdn.nba.com` playbyplay JSON, 5s cadence | Polled by `scripts/live_nba_sniper_worker.py` via ScraperAPI proxy rotation; feeds substitution sniping + remaining-game re-projection. |

### 2.3 Models

* `src/model.py` — **compound Negative-Binomial / Gamma**: game receptions `N ~ NegBin(mu, alpha≈0.1097)`, per-reception yards `~ Gamma(k≈1.555)`; `p_rec_over`, `p_yards_over` (gamma survival), quantiles, joint sampling. Fitted via statsmodels NB2 GLM with method-of-moments dispersion. **Full-game scope only.**
* NFL markets supported today: `receiving_yards`, `receptions`, `anytime_td` (per `viewer/js/sports/nfl.js` model constants `{alpha: 0.1097, k: 1.555}`).
* NBA (`viewer/js/sports/nba.js`, `src/contracts/nba.py`): points/rebounds/assists/threes/PRA via normal approximation, **explicitly uncalibrated** (`model: null`) and `fixturesOnly: true` (balldontlie paid-tier gate).
* Validation culture is genuine: walk-forward holdout evals (`evaluation/holdout_eval_2026_w*.json`), calibrated breaker hurdles, and a repo-wide norm of labeling uncalibrated output (`test/uncalibrated-badge.test.mjs` enforces the badge).

### 2.4 Contracts (`src/contracts/`)

`OddsQuote` (odds.py): `player_id`, `game_id`, `market`, `line` (0–300), `over_odds`/`under_odds` (American, |odds| ≥ 100), `book`, `observed_at`, plus a **vig validator** (two-way implied sum must lie in [0.98, 1.45]) and `QuoteEvaluation` (`status: UNVERIFIED` default, `prob_edge`, `break_even_adv`, `expected_return`). `LiveOddsFeed` adds feed status/verification counts and a `_fixture` flag with a `fixture_notice` — a repo convention for distinguishing synthetic data that Live Sniper should adopt verbatim.

### 2.5 Frontend & Extension

* **Live production frontend:** `viewer/` (vanilla JS, one 8,518-line IIFE, 15,162-line CSS) — deployed via root `vercel.json` (`outputDirectory: viewer`). Strong CSP (`script-src 'self'`, `frame-ancestors 'none'`), HSTS, locked-down Permissions-Policy.
* **Design system (reusable):** "2027 Quantitative Terminal — Obsidian & Neon Chartreuse": `--bg-app:#070708`, `--bg-card:#0e1117`, `--surface-2:#12161f`, text `#f8fafc`, accent `#D4FB11`, success `#10b981`, warning `#f59e0b`, danger `#f87171`; fonts Space Grotesk / IBM Plex Sans / JetBrains Mono. Legacy `--baby-blue` alias exists (remapped to lime).
* **Existing Chrome extension** (`extension/`): MV3, `sidePanel`+`contextMenus`+`storage`, host permission only `https://propwire.vercel.app/*` (stale — production is propstein.vercel.app). `background.js` (37 lines): opens side panel on action click; context menu broadcasts one `search_intent` message handled by the viewer app. **No content scripts, no DOM reading, no auth, no tokens.** Packaging (`scripts/package_extension.sh`) copies `viewer/*` + overlays extension files into a store-ready zip — a proven pipeline Live Sniper can extend.
* **Next.js `app/` directory is aspirational spec code** — `package.json` has zero runtime deps (no next/react/stripe/prisma/next-auth installed, no tsconfig). The shipped billing path is FastAPI. **Do not build on `app/`.**

### 2.6 Tests & CI

* Python: `pytest test/ tests/` — sniper five-gate tests, API security fail-closed suite (unauthenticated 401, invalid-token fail-closed, rate-limit 429, legacy-key never unlocks PRO), contracts, odds adapter, ingestion wiring, provenance, recalc idempotency, arb ledger, worker startup.
* Node: `node --test` — render robustness, execution trust boundary, decision gates, circuit-breaker config, localStorage migration, public pages, commercial readiness, adapter registry, sport switcher, feed health, odds receipts.
* CI (`.github/workflows/ci.yml`): `npm ci && npm run check:production` + Python 3.12 with Gitleaks secret scanning and pip-audit, then pytest. Also `daily_update.yml` and `freeze_tnf.yml` operational cron workflows.

---

## 3. Reuse / Build / Unsupported — Decision Matrix

### 3.1 Reusable as-is or with light extension

1. **Whop + Stripe entitlement services** — `BillingService.check_user_entitlement()` is the correct server-side primitive for the extension session flow; Live Sniper adds short-lived scoped tokens on top rather than replacing it.
2. **`OddsQuote`/`LiveOddsFeed` contracts** — extend with drive/possession fields and a visible-market provenance marker; keep the American-odds and vig validators.
3. **Stale-kill-switch thresholds and philosophy** — adopt per-feed freshness limits (odds 20s live / 60s pregame) as the *default* freshness config, refined per market type; keep the "suppress, never silently fire" invariant.
4. **Five-gate suppression pattern** — maps directly onto the required signal state machine (edge → confidence → freshness → liquidity → CLV).
5. **SSE infrastructure** — `/api/sniper/stream` pattern (snapshot + event + heartbeat, disconnect checks) is the template for `/api/v1/markets/stream`.
6. **Extension packaging pipeline** — `scripts/package_extension.sh` proves the store-zip path; Live Sniper's Chrome app replaces the borrowed viewer UI with a purpose-built panel while keeping the same packaging conventions.
7. **Design tokens & assets** — obsidian surfaces, terminal typography, book wordmark SVGs (`viewer/books/*.svg`), league logos, PropStein logo lockups. Live Sniper follows the brief's baby-blue accent for the Sniper sub-product while reusing the existing surface/text/status colors.
8. **Test conventions** — `node --test` (now runs TypeScript natively on Node 24) and pytest; both suites will run in CI unchanged.
9. **Rate-limiting pattern** — the process-local sliding-window limiter from billing extends to per-session market-evaluation quotas.

### 3.2 Must be built (greenfield)

1. **Active-screen detection stack** — viewport/visibility filtering, batched MutationObserver pipeline, SPA navigation handling, per-site adapters with versioned selectors and fail-safe degradation. Nothing exists.
2. **Canonical `ObservedMarket` schema + normalizer + matcher** — player alias/team canonicalization, strict market-type separation (drive vs next-play vs full-game), ambiguity → `UNVERIFIED`.
3. **Signal state machine** — `DETECTED → NORMALIZED → MODEL_MATCHED → VALIDATED → ALERTABLE/BELOW_THRESHOLD/UNVERIFIED/STALE/SUSPENDED/MODEL_UNAVAILABLE`, with hysteresis and dedup.
4. **Drive-level reception model** — possession-scope probability service (independent-play baseline, then absorbing-Markov drive model), calibration harness, and honest `NO MODEL COVERAGE` until evidence exists.
5. **Extension session tokens** — short-lived scoped tokens (HMAC-signed, `exp`/`iat`/`jti`, revocation), issued after server-side entitlement validation; today's Bearer = raw Whop membership id is long-lived and unscoped.
6. **Entitlement enforcement on market-intelligence endpoints** — today `/api/sniper/feed` and `/api/sniper/stream` are public; premium gating for Live Sniper endpoints must be enforced server-side (fail-closed), never client-side.
7. **Chrome MV3 app** (manifest, service worker, side panel, origin-validated messaging, per-site injection with user opt-in), **web companion**, **Safari packaging path**.
8. **Privacy/compliance documentation** suitable for Chrome Web Store and Apple review.

### 3.3 Unsupported today — explicit limitations

1. **NFL drive-level markets: no data source, no model, no calibration corpus.** The full-game NB/Gamma model **must not** be used to price drive-level receptions (audit confirms the concern in the brief). Until a possession-level feed (e.g. live NFL PBP) and calibration data exist, drive markets display `NO MODEL COVERAGE`.
2. **No NFL live play-by-play ingestion exists** (NBA PBP only, 5s cadence). "Current drive" context cannot be sourced today; the schema and state machine support `driveId`, but the live NFL data path is a Phase 3 dependency.
3. **No screenshot/OCR capability** — to be investigated only as a consent-gated secondary path; nothing exists to reuse.
4. **Direct DraftKings/FanDuel page DOM inspection is not covered by any existing permission.** PropLine's commercial API is the authorized DK/FD data channel in this repo. Page-level adapters therefore ship disabled behind feature flags pending legal/contractual review; the synthetic demo adapter and web companion are the testable surfaces.
5. **Public Railway API domain is not disclosed in the repository** (only the internal `propstein-web.railway.internal:8000`). The extension's API base URL must be a build-time/deploy-time configuration item.

---

## 4. Technical Debt & Security Findings Relevant to the Extension

| # | Severity | Finding | Impact on Live Sniper | Mitigation in this branch |
|---|---|---|---|---|
| S-1 | **High** | `/api/sniper/feed`, `/api/sniper/stream` and most market data endpoints are **public** — the free/PRO boundary is enforced client-side in the viewer | Premium intelligence would be fetchable without entitlement | New `/api/v1/extension/*` + `/api/v1/markets/*` endpoints enforce entitlement server-side, fail-closed; flag S-1 for the existing endpoints as a follow-up (out of scope to avoid silently changing production behavior) |
| S-2 | **High** | Viewer tier resolution: `localStorage['propwire-user-tier']`, **defaults to `'pro'`**; `?tier=` URL param honored (documented severity-4 in docs/DESIGN.md, "authenticated server hookup pending") | Extension must not replicate forgeable client gating | EntitlementGate component renders from server-verified entitlement only; UI tier state is display-only |
| S-3 | Medium | Extension Bearer token = Whop membership id (long-lived, unscoped, no rotation/revocation) | Insufficient for a browser-resident client | New scoped session tokens (15-min TTL default, `jti` revocation list, HMAC) issued only after server-side entitlement check |
| S-4 | Medium | Existing extension `host_permissions` points at `propwire.vercel.app` (stale brand/domain); packaging copies the entire viewer into the panel | Brand/permission drift precedent | Fresh manifest with explicit, minimal permissions; per-site opt-in injection instead of broad content scripts |
| S-5 | Medium | CORS allowlist has no `chrome-extension://` origins | Panel-to-API calls would be blocked | Documented deploy step: add the packaged extension origin to `ALLOWED_ORIGINS` (operator action; not silently changed in this branch) |
| S-6 | Low | Single shared internal API key protects "private" sniper routes (not per-user) | Acceptable for server-to-server; insufficient for subscriber-facing routes | Per-session tokens + per-session rate limits on all new routes |
| S-7 | Low | Next.js `app/` billing routes are unwired spec code (no deps installed) | Confusion risk | Audit note: build on FastAPI path only |
| S-8 | Low | Pricing inconsistency across surfaces ($29/mo viewer, $99 dialog, $299 React page, $290/yr FastAPI) | Compliance/review confusion | Documented; not changed in this branch |

Positive security properties worth preserving: fail-closed defaults everywhere (webhook secrets, entitlement, settlement admin token), `secrets.compare_digest` for key comparison, SSRF-clamped webhook targets and redirects, path-traversal-safe user ids, CSP-locked static frontend, Gitleaks + pip-audit in CI.

---

## 5. Deployed Production Capability (verified 2026-10-30)

* `https://propstein.vercel.app` is live: PropStein branding, NFL 2026 W8 slate, Sniper surface, "LIVE FRESH · Connected" feed status, and stale-kill-switch messaging ("NEWS FEED STALE — automated sniper dispatch is suppressed") visible to anonymous visitors — confirming the fail-closed stale discipline is deployed, not just written.
* The FastAPI service runs on Railway (serving the same viewer same-origin plus `/api/*`); its public domain is not published in the repo. Extension builds must therefore treat `API_BASE_URL` as configuration, defaulting to the operator-configured production API origin.
* No drive-level or live NFL market data flows anywhere in production today.

---

## 6. Implications for the Build Plan (Phases 1–2 of the brief)

1. **Phase 1 (Foundation)** can reuse: entitlement service, session-token issuance (new), packaging pipeline, design tokens/assets, test conventions, and the SSE pattern. The synthetic visible-market detector targets a local demo fixture page — no sportsbook access needed, satisfying the Phase 1 success criterion.
2. **Phase 2 (Quant Engine)** implements the canonical schema, matcher, freshness engine, state machine, EV math (mirroring `OddsQuote` conventions), and the drive-reception baseline model — with a calibration harness that reports *insufficient evidence* (and `NO MODEL COVERAGE` in the UI) rather than fabricated confidence. Deterministic fixtures must produce auditable, mathematically exact assessments.
3. **Phase 3 (Authorized Live Integration)** is blocked on two external dependencies that only the owner can resolve: (a) a licensed live NFL possession-level feed, and (b) written authorization for page-level DK/FD inspection. Both are documented as feature-flagged-off adapters; nothing pretends to be live.
4. The existing full-game model and its endpoints remain untouched. All backend additions are additive (new router module + one include line) to keep the changeset reviewable and reversible.
