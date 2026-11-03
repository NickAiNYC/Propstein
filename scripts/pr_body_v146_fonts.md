# v146 — Font identity + unified box design system

Owner directive: "change the font and box design." This pass replaces the
generic Inter identity with an engineered-institutional trio and collapses
12 ad-hoc corner radii into one token scale. Stacked on #19 (contains 9d45f1b);
merge #19 first, then this lands cleanly.

## Typography (visible identity swap)

| Role | Before | After |
|---|---|---|
| Display / headings | Inter 700/800 | **Space Grotesk 500–700** (`h1–h3`, anti-tout title) |
| UI / body | Inter | **IBM Plex Sans 400–700** |
| Data / numerics | JetBrains Mono | **IBM Plex Mono 400–600** (all `--mono` surfaces, tabular-nums preserved) |

- New `--font-display` token; body line-height 1.45 → 1.5; Inter-specific
  `cv02–cv04` font features removed.
- All 3 hardcoded `Inter` / 3 hardcoded `JetBrains Mono` stacks replaced with
  token references (no orphan families).
- Font `<link>` updated on all 4 terminal pages — hosts unchanged, already
  CSP-whitelisted (`fonts.googleapis.com` / `fonts.gstatic.com`).

## Box design system

- Radius tokens: `--radius-sm 4px` / `--radius 7px` / `--radius-lg 12px` /
  `--radius-pill 999px`. **221 declarations** normalized (was 12 distinct
  values: 2/3/4/5/6/7/8/10/12/14/16/20/24px).
- Intentional exceptions preserved: blurred halo (proportional), mobile sheet
  tops (20px platform-idiomatic), circles (`50%`), asymmetric radii.
- New elevation tokens: `--edge-hi` (inset top highlight), `--shadow-sm/md`.
  Applied to: detail dialog, anti-tout paused panel, `.empty-state`
  (now radius-lg), board container (edge highlight), compliance pill +
  toggle track (pill).
- Dark theme stays locked; flat chrome aesthetic preserved — this is a
  refinement, not a re-skin.

## Cache

Coherent **v146**: 4 pages ×7 refs, `propwire-v146-prod`, build-hash
`2026-w7-v11` (including `ledger/index.html`).

## Verification

- `node --check viewer/app.js` clean
- `node --test` **110/110**
- Headless `scripts/verify_v146_fonts.mjs` **ALL CHECKS PASSED**: declared
  stacks (Plex Sans body / Plex Mono chrome / Space Grotesk headings),
  computed radii (12px panels, 7px board, 29 pill elements), edge highlight
  present, zero console errors; v145 messaging regression guard intact
  (Upgrade chip, paused copy, last-trusted time, fail-closed claim).
- Screenshots: `download/headless_v146_paused_1280.png`,
  `download/headless_v146_desktop_1600.png`.

## Merge order

1. Merge **#19** (v145 messaging) — CI green, mergeable clean.
2. Merge **this** — same-base fast path, no conflicts (v146 supersedes v145 refs).
