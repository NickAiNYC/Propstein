## v169 — Cache-Bust Rescue for the Sniper UI + CSP-Clean Court/Sniper Markup

Follow-up to the audit of Antigravity's `facc769` (live NBA PBP sniper worker + split court-to-sniper UI). The features are sound — this PR fixes two shipping hazards they introduced.

### 1. Version bump was missing → returning visitors would never see the sniper UI (fixed)

`facc769` changed `app.js` (+309) and `style.css` (+186) but left the busters at `2026_v168` and the SW cache at `propwire-v168-prod` — which **precached the old pre-sniper app.js**. Cache-first serving would keep the stale bundle in front of returning visitors indefinitely.

- Busters `2026_v168` → `2026_v169` (5 pages + `sw.js` + `site.webmanifest`)
- SW cache `propwire-v168-prod` → `propwire-v169-prod`
- Build-hash meta `2026-w8-v21` → `2026-w8-v22`
- Sweep tooling: `scripts/sweep_v169_busters.py`

### 2. Prod-CSP violations in the new court/sniper markup (fixed)

- **2 inline `style=""` attributes** in the sniper markup (`nba-game-switcher` justify-content + pill-row flex wrapper) — blocked on prod by `style-src`. Moved to CSS classes `.nba-game-switcher-split` / `.nba-game-pill-row`. `app.js` inline-style count 93 → 91.
- **1 inline `onerror=`** on `nba-court-avatar-img` (from `9c7780d`'s court commit) — blocked on prod by `script-src 'self'`, so dead court headshots would render as broken images. Rewritten with the v150 delegated pattern: the boot-time capture-phase error listener now hides `.nba-court-avatar-img` via CSSOM (`display: none` — keeps the lineup slot layout, initials fallback shows through). Real inline handlers in `app.js` now **zero**.

### Gates (all green locally)

- `node --check` app.js/sw.js — PASS
- `npm test` — **110/110 PASS**
- `autopilot.py --selftest` — ALL PASS
- All 4 harnesses re-pinned v169 and **ALL PASS**: `verify_v152_books`, `verify_v153_rebrand` (cspDebt=178), `verify_v154_dropwire` (mobile-390 overflow **0px**), `verify_v155_photos` (422/422 avatars, zero console errors, SW v169 registered)
- No snapshot re-capture needed (court/sniper markup is NBA-only; NFL parity goldens untouched)

### Merge notes

- Absorbed owner's `270e507` (Railway worker deployment config) mid-flight — backend-only, zero conflicts with viewer changes.
- Base: latest `main`.
