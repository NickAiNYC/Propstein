# v147 + v148 — Sportsbook Terminal Design System

Owner spec (2026-10-27): FanDuel dark mode × Bloomberg institutional.
Implemented as a token-first palette swap + a cascade-last design-system
layer owning density, chrome, pills, badges, illumination, and motion.
v148 is the owner revision pass on top: brand P-stem clearance + the
mint accent layer.

## 1. Color & surfaces (owner tokens, verbatim in :root)

`--bg-app #0b0e14` · `--bg-card #141a23` · `--bg-card-hover #1c2432` ·
`--border-subtle rgba(255,255,255,0.07)` · `--text-main #f0f3f6` ·
`--text-muted-2 #8b949e` · `--accent-primary #0052ff` (FanDuel blue) ·
`--accent-success #10b981` (emerald) · `--accent-warning #f59e0b`.
Derived: bright accent `#4d8dff` (AA text/borders), cyan `#00d2ff`
(under side / data), raised stop `#12161f`, row hover `#1a212d`.
All legacy aliases rewired; **~200 hardcoded legacy hexes** remapped
(#7dd3fc→#4d8dff ×55, #38bdf8→#00d2ff ×30, rgba(125,211,252→rgba(77,141,255) ×113,
rgba(56,189,248→rgba(0,210,255) ×44, plus chrome/border/text values).
Pure black eliminated; accent-ink flipped to white for blue fills.

## 2. Density & typography

- Rows: td 56→50px, padding 6/14→5/12px; th 38→32px — 10+ props per glance.
- Controls: global min-height 40→36px (mobile 44px touch rules untouched).
- Strict `tabular-nums lining-nums` extended to hero edges, sparkline
  values, chip counts, banner items (data cells already covered).
- Metadata weight 400 @ `#8b949e`; player names keep 600.

## 3. Components

- **Status banners → compact floating pills**: full-width amber bar is now
  a centered `999px` pill — soft amber fill `rgba(245,158,11,0.09)`, blur
  backdrop, ellipsized items, pill Retry button. Error tone = restrained
  coral. Fixed a specificity override (`.data-quality-banner.warn`).
- **Position badges**: 26×21px mono-face pills, 1px hairline border —
  WR/TE/RB anchoring per row.
- **Command bar**: chrome compacted to 11.5px mono; layered `#1c2432`
  controls; custom SVG chevron on selects; active toggles restyled in
  v148 (see §5) with FanDuel blue kept on primary CTAs.
- **Micro-bars**: bullet graphs restyled (quiet `#1d2531` track, emerald
  projection marker, amber book marker) — the FAIR | CI visual column.
- Cards hover → `#1c2432` + blue edge tint; modals keep v146 elevation.

## 4. Motion

`transition: all 0.15s ease` on every interactive surface (chips, buttons,
selects, steppers, cards, rows) with a `prefers-reduced-motion: reduce`
kill-switch.

## 5. v148 — brand P clearance + mint accent layer (owner revision)

**Brand fix.** The v3 lockup's 52px desktop img was clipped 7px top and
bottom by the legacy 38px `.pw-brand` chip (`overflow:hidden`) — the P
stem lost its cap. Diagnostic probe (`scripts/probe_logo_clip.mjs`, 11
widths) exonerated the SVG (P-mark bbox fits the viewBox with margin)
and pinned the clip on the chip. The cascade-end tile now hugs the
lockup: 56px flush in the 56px topbar (desktop), 48px in the 52px band,
≤768 mobile chip box untouched. Probe re-run: **0px cut at all 11
widths** (1600→390).

**Mint accent layer.** Owner's pre-neon green system restored on a
cascade-end layer (`#34d399 / #6ee7b7 / #3ccf91 / rgba(16,185,129,·)`):
- Active toggles — chip pills, tier pills, nav buttons, Table/Grid seg
  buttons, sport switcher: mint fill `rgba(16,185,129,.16)`, mint border,
  `#6ee7b7` text, mint illumination ring.
- Keyboard focus rail `#3ccf91` (replaces the sky/emerald mix), live
  ping ring mint, bullet projection marker `#3ccf91`, bottom-nav active
  mint.
- FanDuel blue stays where the spec put it: primary CTAs, links, input
  focus, brand lockup, volt Upgrade chip. Amber status pills untouched.

## Cache & gate

- Coherent **v148**: 4 pages ×7 refs, `propwire-v148-prod` (incl. sw.js
  precache), build-hash `2026-w7-v13` (incl. ledger page). Zero stale
  refs.
- `node --test` **110/110**; headless `scripts/verify_v148_green.mjs`
  **ALL 32 CHECKS PASSED** (logo clearance @1280/1600/390 incl. tile
  flushness, mint accents computed + CSSOM, banner pill, density CSSOM,
  0.15s motion, v146 font guards, v145 messaging guards, zero console
  errors).
- Screenshots: `download/headless_v148_{paused_1280,desktop_1600,
  topbar_1600}.png`.
