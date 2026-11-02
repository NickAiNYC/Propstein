# PHASE 1A AUDIT — WS-A: Live Verified Board + News-Watcher Fix

**Status: AUDIT COMPLETE — STOPPED FOR OWNER APPROVAL. No code changed, nothing pushed.**

Audit executed 2026-11-02, 18:31–18:50 UTC by the lead engineer.
Method: repo inspection at `feat/2027-season-readiness` (local HEAD `e1893c39`, 4 commits ahead of `origin/main` @ `9e2328ea`) + `origin/main` inspection (the deployed truth) + live-site checks against `https://propstein.vercel.app` (static asset SHA-256 verified identical to `origin/main:viewer/app.js`) + headless-browser JS-state dump + GitHub Actions REST API + direct provider reachability tests. Every claim below carries a file path, a commit, a measured number, or a quoted live string.

---

## a) market_feed on the LIVE site

### Numbers (measured 2026-11-02T18:31–18:45Z)

| Metric | Value | Evidence |
|---|---|---|
| Verified quotes, last 24h | **0** | Live banner (browser dump): `"No verified price receipts / 23 quotes ingested. Offers are visible, but action fields remain locked."`; deployed feed `verified_quotes_count: 0`, `verified_books_count: 0`; viewer state `quotesLen: 23` |
| Age of newest quote | **~17 min** | Deployed `viewer/live_odds_feed.json` `updated_at: 2026-11-02T18:24:39.208043Z` (refreshed by Actions run #9, started 18:24:18Z) |
| Refresh cadence | **Every 4 h** (cron `'15 */4 * * *'`), Polymarket-only, keyless | `.github/workflows/odds_freshness.yml:5`; 9 runs since 2026-10-31T15:15Z (≈13 expected ticks — GitHub dropped/delayed ~4; latest run was itself 9 min late) |
| Viewer poll | Client-side re-fetch of the static file every 60 s | `viewer/app.js` §8 (`state.nextPollSeconds = 60`, `fetchJson(oddsUrl + '?t=' + Date.now())`) |
| News heartbeat | **6.1 h stale**, `last_polled_at: 2026-11-02T12:26:52Z`, `poll_count: 2` | `git show origin/main:data/news_watcher_state.json`; live viewer state dump |

Composition of the deployed 23 quotes: **13 Polymarket + 10 synthetic** (`"Synthetic Book A"…D`, quote timestamps 2026-10-20 — i.e. 311.8 h old at publish). The synthetic books were created by `scripts/hotfix_fixtures.py` (real book names → Synthetic A–E) and are retained forever by `merge_feed` (`scripts/fetch_polymarket_props.py:579`: `keep = [q for q in feed["quotes"] if q.get("book") != BOOK]` — no age-based pruning of non-Polymarket quotes).

### Why verified quotes are not flowing reliably — root-cause chain (ranked, with evidence)

1. **The verification code is not deployed.** The ingested→receipt-verified pipeline exists as local commit `f8680507` ("receipt-matched quotes — the ingested→receipt-verified pipeline is live", pytest 355 passed) and is **not on `origin/main`** (`git rev-list --count origin/main..HEAD` = 4; `data/polymarket_receipt_log.json` "exists on disk, but not in 'origin/main'"). On main, `verified_*_count` is structurally hardcoded 0 and the Polymarket contract forbids any verification claim (per that commit's own message).
2. **Single-publisher structure.** Frozen `verification.v1` requires `min_sharp_books=2` for the V3_conflict clause (`src/contracts/verification.py:128`); the deployed feed has exactly one real publisher (Polymarket). A second book (The Odds API) is already coded (`src/odds.py`, `src/odds_adapter.py:505`) and the `ODDS_API_KEY` repo secret demonstrably works — NBA FanDuel quotes landed 2026-11-01T16:55Z via `daily_update.yml` → `scripts/fetch_nba_odds.py` (`viewer/nba_odds_2026-11-01.json`: 52 FanDuel quotes, `status: live-unverified`). **But the only workflow that publishes the NFL board feed (`odds_freshness.yml`) passes no secrets and its script path on main never calls The Odds API** — so the NFL feed stays single-book and structurally unverifiable.
3. **The Railway `market_feed` service cannot feed the public board as architected.** It is declared in `railway.json` (`services.market_feed` → `python -m src.services.market_feed`) but (i) its primary provider is dead: `api.propline.com` **does not resolve** (DNS NXDOMAIN; `propline.com` is a GoDaddy parked auction page), (ii) there is no evidence the service runs, and (iii) even running, it dual-writes to a Railway-local `TruthStore`/`last_known_odds` (`src/services/market_feed.py:111–129`) — nothing publishes from it to `viewer/live_odds_feed.json`, which is the file Vercel actually serves. The public board's only live data path is: **GitHub Actions → repo → Vercel static deploy** (redeploy verified within seconds of the 18:24:39Z push).
4. **Frontend is NOT the blocker.** The viewer renders verification strictly from feed fields — `quoteState()` (`viewer/app.js:706–713`) returns `VERIFIED` only when verified stamps exist, and action fields lock at 0 verified (`viewer/app.js:2655`).
5. **Wiring landmine:** `scripts/check_odds_freshness.py:45` hard-requires `feed_status == "LIVE_POLYMARKET_CLOB_UNVERIFIED"`. Merging `f8680507` (which introduces `LIVE_POLYMARKET_CLOB_RECEIPTED`) without patching the checker will false-alarm every freshness run.

---

## b) Viewer mode + minimal change set to serve priced quotes from OUR backend

**Snapshot mode: confirmed.**
- Board data is loaded from static files co-deployed with the page: `viewer/js/sports/nfl.js` slates + `viewer/feeds/slate-index.json` (W8 → `odds: 'live_odds_feed.json'`, `slate: 'slate_2026_w8.json'`, …).
- `viewer/app.js:3835` fetches `/api/sniper/feed` **relatively** — on Vercel this 404s and falls back to the static `/feeds/sniper_terminal_snapshot.json` (line 3842). The FastAPI (`api/main.py`) is on Railway and is not wired into the public board at all.
- Browser state dump confirms: all rendered data (23 quotes, 18 slate records, 13 live picks, news state) traces to the static files; nothing comes from a backend at runtime.

**Bring-your-own-key: already gone from the deployed viewer.**
- No API-key input or BYOK copy exists anywhere in `viewer/` (searched `viewer/app.js`, `viewer/index.html`, `viewer/js/**`; live page shows no key-related copy).
- The only remnant is undeployed legacy: root `index.html:890` (`<option value="the_odds_api">The Odds API (API Key)</option>`) — root files are not served (`vercel.json` → `outputDirectory: "viewer"`).
- No secrets in the frontend: CSP `connect-src 'self' https:` with no key handling in JS; verified by search.

**Minimal change set (wiring existing code — no rewrite):**
1. Push/merge local commit `f8680507` (receipt pipeline in `scripts/fetch_polymarket_props.py`, additive amendment to `src/contracts/polymarket.py`, viewer `RECEIPT-MATCHED` label; already tested — pytest 355 passed).
2. Patch `scripts/check_odds_freshness.py` to also accept `LIVE_POLYMARKET_CLOB_RECEIPTED` (2-line diff).
3. `.github/workflows/odds_freshness.yml`: add `ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}` and an NFL bulk player-props sweep (existing `src/odds.py` client, bulk `/v4/sports/americanfootball_nfl/odds` endpoint, 2 credits/sweep) merged into the same feed → second sharp book → V3_conflict becomes checkable → `VERIFIED` becomes structurally possible. Cadence per §d.
4. Viewer-only WS-A diffs (the only real frontend work): sanity/quarantine layer before display; one source of truth for header counts; fail-closed stale state ("no verified lines — feed stale"); stop rendering `LIVE FRESH · Connected` while 0 verified.
5. **PropLine: drop from Phase 1A** (dead host, §d). Bovada (keyless) remains the composite provider's fallback for any future Railway path; not needed for the Actions path.

**Honesty gaps observed on the live board (verbatim):**
- Header metric: `"Feed-verified player lines clearing Poisson-Gamma hurdle · 23 quotes ingested"` while the state line directly beneath says `"No verified price receipts / 23 quotes ingested"` — "verified" used with two meanings in one screen.
- Ribbon: `"FEED HEALTH / LIVE FRESH · Connected"` reflects **odds-file age only** (`viewer/app.js:2469–2472` — the ribbon title switches on `oddsFreshness`/`odds` alone), while 0 quotes are verified and the news heartbeat is 6 h stale.
- Currently displayed edges are in a sane range (+13.1 %, −20.4 %, +12.3 %, each behind a `VERIFY` button — browser dump), but the structural cause of the earlier 169–332 % displays is still present: synthetic and stale quotes persist in the feed with no cross-book sanity gate, so any future model refresh can re-combine them into wild edges.

---

## c) News-watcher concurrency defect + minimal fix

### What is actually broken (measured)
- `news_watcher.yml` is registered and **active** on `origin/main` (GitHub API: workflow id 404629746, `state: "active"`, created 2026-11-02T14:46:35Z — the PR #80 merge), cron `'5,35 * * * *'` … and has **ZERO runs ever** (`total_count: 0`) as of 18:31Z — ~8 expected ticks missed. The heartbeat is frozen at 12:26:52Z / `poll_count: 2`.
- Not a YAML or push defect: the file on main is byte-identical to local; syntax valid; `permissions: contents: write` correct; the commit+`git push` mechanics are identical to `odds_freshness.yml`, whose pushes demonstrably land (run #9 → commit `9e2328ea` at 18:24:39Z). All other scheduled workflows demonstrably fire (Odds Feed Freshness: 9 runs).
- Most probable cause: GitHub scheduler registration lag/drop for a newly added schedule (GitHub documents that schedule events can be delayed and delayed runs may be dropped — consistent with 4 of ~13 odds_freshness ticks also missing). **Confirming requires one manual `workflow_dispatch`, which needs an owner click (no write token in this session).**
- Consequence chain: 300 s dead-man tripped → automated sniper dispatch suppressed (intentional per the workflow's own honesty comment — do not widen it) → if nothing changes, the site's 24 h "feed abandoned" banner fires at ~12:26Z on 2026-11-03.

### Real concurrency defects (for when runs do start)
1. **`freeze_tnf.yml` pushes to main with NO concurrency group** (checked all 8 workflows: `daily_update`, `freeze_sunday_early`, `freeze_ufc`, `odds_freshness`, `news_watcher` share group `autopilot`; `freeze_tnf` has none; `nba_daily` calls `daily_update` and itself pushes nothing). With measured 9-minute scheduler delays, a delayed `:35` news run can straddle Thursday 23:45 → two workflows committing and pushing concurrently → non-fast-forward rejection → red run + lost heartbeat or lost freeze snapshot.
2. **Non-atomic state writes.** `scripts/news_watcher.py:80–106` (`save_watcher_state`, `append_status_log`) writes plain `open(...,"w")` to three copies (`data/`, `viewer/`, `public/`) and does read-modify-write on the status log with **no tmp+rename and no lock** → an interleaved run can corrupt the JSON or lose log entries.
3. Shared `autopilot` group means a long `daily_update` (11:00/21:00 UTC full slate build) queues the news run and delays the heartbeat — acceptable and documented; the 5-minute `timeout-minutes` already bounds the news job itself.

### Minimal fix (smallest diff the evidence justifies)
1. **One manual dispatch** of "News Watcher Poll" (owner click, or an authed API call) to light up/verify the schedule and prove the pipeline end-to-end.
2. Add to `freeze_tnf.yml` (2 lines): `concurrency: { group: autopilot, cancel-in-progress: false }` — closes the only genuine concurrent-push window.
3. Make `save_watcher_state` atomic — write tmp + `os.replace()` for the three copies (~6-line diff in `scripts/news_watcher.py`).
4. No run-lock beyond that: the shared group already serializes every other pusher. This is a fix, not a rewrite — no scheduler, no persistence layer.

---

## d) Feed call volume at proposed cadence vs plan cap

**Official pricing verified during this audit (the-odds-api.com homepage, 2026-11-02):** Free = 500 credits/mo; 20K = $30/mo; 100K = $59/mo; 5M = $119/mo; 15M = $249/mo. Credit cost = 1 per sport × market × region per request. Player props available for selected US sports/books. (Their /terms URL 404s — review the ToS at signup before paying.)

**STOP-AND-REPORT on PropLine (per §6):** `api.propline.com` does not resolve (curl: `Could not resolve host`, DNS failure) and `propline.com` is a GoDaddy parked/auction page. The bracketed "PropLine Pro $19/mo — 25,000 req/day; Hobby $9/mo" **cannot be verified against any official source; the host is dead.** Do not pay. Phase 1A must not depend on PropLine.

Volume math (`MARKETS = ["player_receptions", "player_reception_yds"]`, `src/odds.py:26`; NFL slate ≈ 15 games; Polymarket batch POST ≤ 400 tokens):

| Path | Per run | Current (4 h) | Proposed 15-min in slate windows, 60-min idle | Cap / fit |
|---|---|---|---|---|
| Polymarket (free, keyless) | 1 GET events + 1 POST books (+1 verification re-pull after `f8680507`) ≈ 3 calls | ~18/day | ~288/day in-window | No published cap; modest |
| The Odds API — **bulk** `/odds` sweep | **2 credits** (2 markets × 1 region, all events in one request) | 0 (not wired) | 2 × 96 = 192/day ≈ **5.8k/mo** worst case | 20K tier ($30/mo): ~29 % util ✅ |
| The Odds API — per-event pattern (current `OddsClient.slate()`) | ~30+ credits (15 events × 2 markets; docstring `src/odds.py:6` says 250–450 across ~8 books) | — | 2,880+/day ≈ 86k+/mo | ❌ does not fit $30 tier — **use the bulk endpoint** |
| Sleeper news feed | 1 call (14.6 MB, measured 0.21 s) | 0 (not running) | 48/day | Free, keyless |

Precedent: the NBA path already caps itself (`fetch_nba_odds.py --max-credits 20`). Recommendation: **Polymarket (free) as book #1 + The Odds API 20K ($30/mo) as book #2, bulk endpoint only, 15-min cadence during Tue–Sun slate windows / 60-min otherwise** ≈ ≤6k credits/mo — inside the 20K tier with >3× headroom. The free 500/mo tier is only enough for audit/dev (~2 bulk sweeps/day).

Scheduler reliability note for the 48 h exit criterion: GitHub dropped ~4 of ~13 expected 4-hourly ticks in the last 51 h and delayed the latest by 9 min. A 4-hourly cadence with a 6-hour TTL alarm has thin margin; the proposed 15-min cadence gives ~24× redundancy inside the same TTL.

---

## e) Frozen-contract confirmation

The Phase 1A plan touches **none** of: `src/model.py`, `src/features.py`, `src/contracts/quant.py`, `src/contracts/gate.py`, `src/contracts/verification.py`. The only contract change is the **additive** amendment to `src/contracts/polymarket.py` already written in local commit `f8680507` (new `feed_status` value + receipt counts, strict fail-closed invariants, `VERIFIED` still rejected single-book) — an extension, not a replacement, exactly as the brief permits. Display/verification gates (edge threshold, market/player match, injury confirmation, staleness regime) remain enforced by the frozen `evaluate_gate`/`verification.v1` engine — untouched. No gate is loosened anywhere in this plan.

Non-goals respected: no auth, Stripe, Postgres, Sniper Alerts dialog, email/Discord, analytics/Sentry, NBA parity, extension, or API-product work is proposed. Existing dormant code for those is left as-is.

CI guardrail: `.github/workflows/ci.yml` runs the contract/verification/logging/leakage pytest set plus the full `test/` suite and Node production gates on every push — the "CI stays green" non-negotiable is enforceable as-is.

---

## Open items requiring the owner (STOP-AND-REPORT)

1. **PropLine tier:** unverifiable + dead host → recommend dropping PropLine from Phase 1A and using The Odds API $30/mo (20K credits) as the second book. Per §6 I stop here and will not choose/pay any tier without your sign-off.
2. **The Odds API commercial-use terms:** ToS page unreachable during the audit (404) — review at signup before paying.
3. **One manual dispatch** of the News Watcher Poll workflow (your click) to activate/verify the schedule — I have no write token in this session.

## Proposed build sequence (after approval — for context only, nothing started)

- **PR-1 (wiring + fixes):** merge `f8680507`; freshness-checker accepts RECEIPTED; atomic news-watcher state writes; `freeze_tnf` concurrency group. Tests: full pytest + node gates.
- **PR-2 (second book + cadence):** `odds_freshness.yml` gains `ODDS_API_KEY` + bulk NFL sweep; cadence 15-min/60-min (feature-flagged via workflow input so it can be dialed back without a code change).
- **PR-3 (viewer honesty):** sanity/quarantine layer, single-source header counts, fail-closed stale state.
- **PR-4:** `PHASE1A_RUNBOOK.md` + start of the 48 h observation window (exit criteria §7).

After each PR: what changed, tests run, and exactly what to click to verify.
