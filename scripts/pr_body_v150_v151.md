## What this ships

Two fixes on top of merged main (multi-sport rebrand):

### v150 — fix: team logos / images missing on production (`05d4564`)

Root cause of "I don't see the logos and other images": the production CSP
(`vercel.json`) shipped `img-src 'self' data:` — every team crest
(`a.espncdn.com/i/teamlogos/...`) was refused by the browser (28/28
`requestfailed :: csp`) while the server returned 200. Local harnesses never
caught it because they served no CSP headers.

- `vercel.json`: `img-src += https://a.espncdn.com` (NFL + NBA crests)
- Crest markup is now CSP-clean: no inline `style=` / `onerror=` (both were
  also CSP-blocked on prod). Theme colors ride `data-crest-bg/border` applied
  via CSSOM by one delegated MutationObserver (CSP-exempt).
- New permanent guard `scripts/verify_v150_csp.mjs`: serves viewer/ WITH the
  vercel.json header parity and proves 28/28 crest logos decode under the
  production CSP, zero CSP-blocked requests.
- Repro probe committed: `scripts/probe_prod_images.mjs`

### v151 — feat: daily autopilot — lines refresh + automatic NFL week rollover (`333bf3e`)

Answers "how do I keep it up to date with the lines and automatically update
the weeks in NFL and NBA daily":

- `.github/workflows/daily_update.yml`: 2× daily cron (11:00 / 21:00 UTC =
  07:00 / 17:00 ET) runs `scripts/autopilot.py`, commits new week data as a
  bot commit on change; Vercel auto-deploys. Viewer needs **no code release**
  to show a new week.
- `scripts/autopilot.py` (idempotent, selftested): nflverse feed refresh,
  **active-week resolution from the real schedule** (next-kickoff + 4h
  Monday-night grace), full model run (`src/week1.py`), viewer week files
  matching the committed w7 schemas, provenance-stamped; writes
  `viewer/feeds/slate-index.json` manifest (NFL weeks + NBA date slates).
- `app.js initSlateIndex`: fail-closed manifest merge at boot — new
  weeks/nights appear without code releases; offline keeps built-in slates
  (JSON is network-only per SW data policy).
- **Board ships on live W8** (Oct 29–Nov 2, CAR@GB TNF): 422 modeled
  receivers retrained through W7 (fair lines: Nacua 118.0, Lamb 114.0,
  JSN 113.5); W7 auto-flipped historical; boot default `2026_w8`.
- Root `vercel.json` CSP gap closed too (v150 fixed only `viewer/vercel.json`;
  production uses the root config — without this the logo fix never reached
  the live site).

### Owner unlocks (GitHub Secrets, optional)

| Secret | Effect |
|---|---|
| `ODDS_API_KEY` (The Odds API — paid props tier, see `docs/B1-LINE-HISTORY-SPEC.md`) | daily sportsbook lines refresh replaces fair-line-only mode |
| `BALLDONTLIE_API_KEY` (free tier) | NBA date slates generated automatically each night |

Without keys the board stays honest: fair lines + odds feed explicitly
stale-flagged.

## Version / cache

`2026_v151` ×7 ×4 pages + sw.js · cache `propwire-v151-prod` · build-hash
`2026-w8-v16` ×5. Multi-sport titles/descriptions/og-image from main are
preserved (manual conflict resolution kept owner branding, took our
build-hash).

## Gates

- `node --check` OK · `node --test` **110/110**
- `scripts/autopilot.py --selftest` ALL PASS
- `verify_v151_autopilot.mjs` ALL PASS (29 checks: manifest schema/default/
  historical flips, w8 files resolve, boot `2026_w8`, selector W8/W7/W1,
  research mode 422 rows w/ Nacua first, zero console errors, SW v151 precache)
- `verify_v150_csp.mjs` ALL PASS · `verify_v149_ios.mjs` ALL PASS ·
  `verify_v148_green.mjs` ALL PASS
