## v170 — Frameless Player Avatars: No Round Holder, +50% Picture, 2027 Lime Logo Chip

Follows the merged v168 (composite avatar) and v169 (cache-bust + CSP-clean). CSS-only release — `app.js` untouched, NFL parity goldens unaffected.

### The ask

> "remove the background and round holder around the players and make logos smaller and player picture 50% larger and more visible on web and mobile"
> "around the team logos make it 2027 vibes"

### What changed

**Frameless avatar (all surfaces)**
- Circular holder removed: `border-radius 50%` → `14%` soft rounded rectangle
- Ring (`border`) and inset-highlight chrome removed
- Dark radial backdrop removed — flat `#16202e` surface remains **only** for the initials-fallback state (photos cover it entirely); light theme synced
- Soft drop shadow keeps photos visible against card backgrounds

**Pictures +50%**
| Context | Before | After |
|---|---|---|
| Desktop slate row | 34px | **50px** |
| Mobile card | 58px | **86px** |
| Injury panel | 44px | **64px** |
| Execution dialog | 56px | **84px** |
| Detail modal | 64px | **96px** |

Initials fallback font sizes scaled to match (14/20/16/22px). Mobile `!important` block fully synced (dimensions, radius, border removal, flex-basis).

**Team logo chip — smaller + "2027 vibes"**
- Footprint 52% → **38%** of the picture, still anchored bottom-left
- Restyled on the existing brand token system (`--accent-primary` = "2027 Electric Lime" `#D4FB11`): dark glass gradient chip + 1px electric-lime ring (`--brand-accent-border`) + lime glow (`--brand-accent-glow`) + inset lime wash + `backdrop-filter: blur(4px)`
- Light theme: white glass + lime ring
- Mobile block adds a stronger 14px glow for small-screen punch

### Version sweep

- Busters `2026_v169` → `2026_v170` (5 pages + `sw.js` + `site.webmanifest`), SW cache `propwire-v170-prod`, build-hash `2026-w8-v22` → `2026-w8-v23`
- `scripts/sweep_v170_busters.py` (note: first sed-derived generation self-mangled — rewritten via direct write; logged in worklog)

### Gates (all green locally)

- `npm test` — **110/110 PASS**
- `autopilot.py --selftest` — ALL PASS
- All 4 harnesses re-pinned v170, **ALL PASS**: `verify_v152_books`, `verify_v153_rebrand` (cspDebt=178), `verify_v154_dropwire` (mobile-390 overflow **0px**), `verify_v155_photos` (422/422 avatars, zero console errors, SW v170 registered)
- Visual verified on regenerated mobile + desktop screenshots: frameless photos, lime chips on bottom-left
- No snapshot re-capture needed (CSS-only; markup untouched)

Base: latest `main` (includes merged PR #28).
