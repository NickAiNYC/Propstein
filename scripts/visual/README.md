# Visual regression harness

A safety net for CSS refactors. The unit and DOM tests check markup and data, not how
the page looks, so a CSS change can pass `npm run check` and still break the layout.

```sh
npm run visual:baseline   # capture the current tree into .visual/baseline
# ... change CSS ...
npm run visual:check      # capture into .visual/actual and diff against the baseline
```

`visual:check` exits 1 if any screenshot changed and writes diff images to `.visual/diff/`
(changed pixels in red over a dimmed copy of the new screenshot).

To check only some screenshots, run `node scripts/visual/capture.mjs <dir> --only <substring>`.
For compare options, run `node scripts/visual/compare.mjs <base> <actual> [diff] --tolerance 8 --max-pixels 0`.

## What it captures

There are 15 screenshots, at mobile (375×812 @2x) and desktop (1280×900) unless noted:

- home (the first 4000px)
- home with the header condensed after scrolling (mobile only)
- board in cards view and in table view (desktop only)
- the pricing, settings and player-detail dialogs
- `/ledger.html` and `/audit.html`

## Why the screenshots are deterministic

Two captures of the same tree are pixel-identical. This was checked across 5 full runs
(75 screenshots, 0 differing pixels).

| Source of noise | How it is handled |
|---|---|
| The autopilot commits new slates and odds several times a day | Every `.json`/`.csv` is served from the commit in `scripts/visual/data-ref`. Page code comes from the working tree. |
| Freshness copy depends on the time | `Date.now()` is fixed to the data-ref commit's timestamp. |
| Google Fonts and ESPN/NBA headshots | Cross-origin requests never reach the network. Images get a transparent 1×1 PNG, stylesheets get empty CSS. |
| CSS animations, script-driven bottom sheets, focus rings | An animation-off stylesheet is injected, Web Animations are finished, and the script waits until open dialogs stop moving. Focus is cleared before each shot. |
| GPU raster of `backdrop-filter` and clipped strips | Chromium runs with software raster, an sRGB profile and no threaded scrolling. Each shot is retaken until two consecutive frames are identical. |

Baselines depend on the machine (font rendering differs by OS), so `.visual/` is gitignored.
Record a baseline on the commit you start from, then run `visual:check` after each change.

To move the pinned data forward, write a newer commit SHA to `scripts/visual/data-ref`
and re-record the baseline.

The harness uses `playwright-core` 1.57.0 (the same version as `extensions/`) with the
full Chromium build in headless mode (`channel: 'chromium'`). If that browser is missing,
run `npx playwright-core install chromium`.
