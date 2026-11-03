## v168 — Composite Player Avatar: Team Logo on the Picture's Bottom-Left Corner

Combines the team logo and the player photo into **one larger visible picture** — the team logo now rides the bottom-left corner of the player's photo as a circular chip, everywhere a player avatar renders.

### What changed

**Composite avatar (`viewer/app.js`)**
- `avatarFor(playerId, displayName, team)` gains a `team` param and renders `pw-avatar-team-badge`: a circular ESPN CDN team logo chip absolutely positioned at the picture's bottom-left corner (`left: 4%; bottom: 4%`, 52% of the avatar, `object-fit: contain` on a solid slate surface with a ring — guaranteed contrast on any photo).
- The standalone team crest that used to sit next to the avatar is **removed at every composite surface** — no redundant double-logo:
  - mobile cards (`card-id-block`)
  - injury panel
  - detail modal (was `crest-lg`)
  - desktop slate rows (was `teamCrest(row.team, 'md')`)
- Execution dialog had no adjacent crest — it gains the badge via the new `team` param.
- The CLV audit table keeps its standalone small crest (no avatar there — not a composite surface).

**Larger pictures** (`viewer/style.css`)
| Context | Before | After |
|---|---|---|
| Desktop slate row | 26px | 34px |
| Mobile card | 44px | 58px |
| Injury panel | 34px | 44px |
| Execution dialog | 48px | 56px |
| Detail modal | 56px | 64px |

Badge scales automatically (52% of avatar per context); initials fallback font sizes scaled to match.

### CSP & fail-open discipline (unchanged guarantees)
- Team logos + headshots both ride `https://a.espncdn.com` — allowed by `img-src` since v150. Zero new origins.
- Badge joins the delegated capture-phase error handler: a dead logo self-removes, initials/photo show through. No inline styles, no inline handlers.
- Chip surface is CSS-owned (solid dark chip, light-theme variant) — NFL_LOGO_MAP alpha tints (18–25%) are too subtle over photos; team identity comes from the logo image itself.

### Version sweep
- Busters `2026_v167` → `2026_v168` across 5 pages + `sw.js` + `site.webmanifest` (new `scripts/sweep_v168_busters.py`)
- SW cache `propwire-v168-prod`; precache keeps bare + busted `/app.js` and `/style.css` pairs (v149 addAll discipline)
- Build-hash meta `2026-w8-v20` → `2026-w8-v21` (5 pages)

### Gates (all green locally)
- `node --check` app.js/sw.js — PASS
- `npm test` — **110/110 PASS**
- NFL parity snapshots re-captured (`PW_UPDATE_SNAPSHOTS=1` — announced intentional change; goldens now carry the badge markup)
- `autopilot.py --selftest` — ALL PASS
- `verify_v152_books` / `verify_v153_rebrand` (cspDebt=178, not grown) / `verify_v154_dropwire` (mobile-390 overflow **0px** — owner redesign cleared the old 10px debt) / `verify_v155_photos` (**422/422** avatars, 18 decoded, zero console errors, SW v168 registered, 25 precache entries) — **ALL PASS** after re-pin to v168
- Visual: composite verified on mobile + desktop screenshots (LA/DAL/SEA/DET/BAL/CIN chips on bottom-left)

Base: latest `main` (`d7a9b30`, owner headshot/card-grid upgrade included).
