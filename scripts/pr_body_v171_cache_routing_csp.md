# v171 — cache-bust rescue + CSP-clean Alert Routing markup

## Why (audit findings on ab04158 + 3337233)

The Polymarket CLOB arb engine (`ab04158`) and Discord/Telegram webhook
dispatcher + Alert Routing UI (`3337233`) commits changed `viewer/app.js`
(+404) and `viewer/style.css` (+293) but did not touch the release
versioning. Consequences on current main:

1. **Stale cache for returning visitors (P0).** Buster still
   `2026_v170`, SW cache still `propwire-v170-prod`, build-hash still
   `2026-w8-v23`, and `sw.js` is byte-identical to the previously
   installed one — so the browser never re-installs the SW and returning
   visitors stay pinned to the old precached `app.js`/`style.css`. The
   new Polymarket arb pane and Alert Routing UI are invisible to them,
   and the fleet forks between old/new asset bytes at identical URLs.
2. **CSP-stripped inline styles (P1).** The Alert Routing pane shipped
   15 inline `style=""` attributes. Prod CSP is `style-src 'self'`
   (no `unsafe-inline`, `viewer/vercel.json`), so those declarations are
   silently dropped and the pane renders without its intended layout.

## What this PR does

- **Three-piece bump:** buster `2026_v170 -> 2026_v171` (5 terminal
  pages + `site.webmanifest` + `sw.js`), SW cache
  `propwire-v170-prod -> propwire-v171-prod` (precache keeps the
  bare + busted `app.js`/`style.css` pair), build-hash
  `2026-w8-v23 -> 2026-w8-v24`. Sweep: `scripts/sweep_v171_busters.py`.
- **CSP-clean conversion:** the 15 Alert Routing inline styles are now
  class-driven (`arb-head-tools`, `arb-routing-head`, `arb-routing-title`,
  `arb-routing-subnote`, `arb-routing-telegram-row`, `arb-routing-block`,
  `arb-routing-label-tight`, `arb-routing-actions`, `arb-routing-save`,
  `arb-routing-result`, `arb-routing-payload-pre`) with 1:1 property
  parity in `style.css`. Static inline-style count in `app.js` returns
  from 106 to the 91 baseline; zero markup behavior changes.
- **Harness re-pin:** `verify_v152_books`, `verify_v153_rebrand`,
  `verify_v154_dropwire`, `verify_v155_photos` moved to v171 markers.

## Verification

- `node --check viewer/app.js viewer/sw.js` — OK
- `npm test` — 110/110
- `python3 scripts/autopilot.py --selftest` — ALL PASS
- 4 harnesses — ALL PASS (books; rebrand cspDebt=178; dropwire
  overflow=0; photos 422/422, zero non-CSP-debt console errors)
- Visual: regenerated mobile + desktop screenshots verified (frameless
  v170 avatar design intact, lime logo chips rendering, no regressions)

## Not changed (flagged for owner)

- `GET/POST /api/sniper/webhooks` + `/webhooks/test` are currently
  unauthenticated while the repo has a `verify_entitlement` convention —
  SSRF impact is contained by the dispatcher's hard host allowlist
  (discord.com / api.telegram.org, HTTPS-only, private-IP rejection),
  but config-overwrite/spam is possible. Owner decision.
