# v155 — player headshots across the terminal

User ask: **"can we add the player photos"** — stacked on PR #24 (base
`feat/v153-pwire-rebrand`) so the approved v154 visual stack stays intact.

## What ships

- **`viewer/feeds/player_photos.json`** — verified ESPN headshot map for
  647/654 players (98.9%) across the current NFL W8 slate + NBA night slate:
  `{photos: {player_id: {url, name, league}}, by_name: {normalized_name: id}}`.
  Keyed by the app's own ids (GSIS for NFL, fx slugs for NBA) with a
  normalized-name index for rows that only carry a name (picks, injuries,
  CLV).
- **`scripts/build_player_photos.py`** — resolution builder: ESPN public
  search v2, strict normalized-name match (accent-folded, punctuation-drop,
  suffix-strip), `defaultLeagueSlug` pool filter (kills same-name
  college/WNBA duplicates), uid-dedupe preferring image-bearing copies, and a
  guarded fuzzy pass (same league + same surname + same first-initial +
  unique candidate only). Every URL is verified (HTTP 200 + `image/*` +
  >=1KB) before it ships. Surname-only queries are rejected by design — the
  surname pool is ambiguous ("mann" -> Tre Mann) and a wrong photo in a
  betting terminal is worse than no photo.
- **app.js** — `initPlayerPhotos()` at boot (network-only, 4s abort,
  fail-open) + `avatarFor()` used in slate rows, mobile cards, the detail
  modal title, the execution slip identity, and the injury feed. Initials
  render underneath every avatar; a delegated capture-phase error listener
  removes dead images so initials show through. Zero inline handlers/styles
  (v150 CSP discipline). Headshots ride `a.espncdn.com` — the production CSP
  `img-src` already allows it since v150, so **no CSP change is required**.
- **style.css** — avatar layer appended at cascade end (sizes 24-48px per
  surface, light-theme variants).
- **autopilot.py** — pipeline step 6: incremental, fail-open photo refresh
  after the NBA day fetch; selftest extended; documented in the module
  docstring and `--plan`.
- **v155 markers** — SW cache `propwire-v155-prod`, busters `2026_v155`
  across the terminal pages + manifest, build-hash `2026-w8-v20`. Feeds JSON
  stays network-only per the SW data policy (never precached).

## Honest fallbacks (7 names, 1.1%)

`Two-Way Callup` is a fixture placeholder; Chris Moore has no ESPN pro
headshot; five low-profile/variant names (Deuce McBride, James Mitchell,
Marquise Brown, Ron Holland II, Tyler Scott) stay unmapped rather than risk
a wrong-photo match — they render clean initials avatars.

## Bonus fix (pre-existing time bomb)

`test/feed-health.test.mjs` anchored a stale-feed fixture to the *real*
clock while the sandbox freezes `Date` at 2026-10-22 — the fixture aged
itself into the future and the paused-panel test detonated on 2026-10-29.
Both fixtures now anchor to the sandbox's frozen clock (deterministic
forever).

## Gates

- `node --check` OK; **npm test 110/110**
- `autopilot.py --selftest` + `build_player_photos.py --selftest` ALL PASS
- parity goldens re-captured per protocol (`PW_UPDATE_SNAPSHOTS=1`) with
  char-level audits: delta = avatar markup only (verified twice)
- **`verify_v155_photos.mjs` ALL PASS (22 checks)** — production-CSP header
  parity server: ZERO CSP-blocked requests, 422 avatars on the board (418
  real headshots decoded incl. Puka Nacua), 422/422 mobile cards, detail
  modal avatar, SW v155 precache populated, slate coverage 557/562
- Screenshots: `headless_v155_photos_{desktop,mobile}.png`
