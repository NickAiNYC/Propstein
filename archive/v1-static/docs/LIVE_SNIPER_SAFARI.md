# Live Sniper — Safari Adaptation Guide

Chrome MV3 is the reference platform. This document is the honest list of
what Safari's WebExtension support covers, what needs a shim, and what
cannot be ported at all. All shared logic already avoids Chrome-only APIs
by construction: `packages/{core,detection,ui}` are platform-free, and
`packages/browser` isolates the platform surface behind typed interfaces.

## Compatibility inventory (Safari 17+ / safari-web-extension-converter)

| Chrome API used | Safari status | Adaptation |
|---|---|---|
| Manifest V3 (service worker background) | Supported | Converter maps to non-persistent background page; keep the worker start-up idempotent (it already is — listeners re-register on every start) |
| `chrome.runtime.onMessage` / `sendMessage` | Supported | Same protocol object; `sender.id` equals the extension id — keep the trust check |
| `chrome.scripting.executeScript` | Supported (with `scripting` permission) | Same injection model; confirm isolated-world semantics on target Safari version |
| `chrome.sidePanel` | **Not available** | The companion page already exists (`web-companion/index.html`) and runs the identical panel bundle; bind it to the toolbar via `browserAction` default popup or a pinned tab |
| `chrome.storage.session` | **Not available** (Safari has no memory-backed area) | Shim: `storage.local` + explicit purge on `browser.startup`/lock. The security property "cleared when the browser closes" must be re-verified on the shim before shipping |
| `chrome.storage.local` | Supported | Direct |
| `chrome.permissions.request` (optional host) | Partially supported | Validate per-origin grant flow on target OS; Safari may require the host in `permissions` at conversion time — prefer keeping the demo-only localhost host and shipping real-book hosts after review |
| `chrome.tabs` (query/track active tab) | Supported | Same bookkeeping |
| `chrome.alarms` | Supported | Not currently used (intervals suffice while the panel is open) |

## Conversion steps

```bash
xcrun safari-web-extension-converter \
  extensions/dist/propstein-chrome \
  --project-location ./build/safari \
  --app-name "PropStein Live Sniper" \
  --bundle-identifier com.propstein.live-sniper
```

1. Pre-conversion patch of the built `manifest.json`:
   - remove `"side_panel"` key and the `sidePanel` permission;
   - add `"browser_action"` (or `action` with `default_popup` pointing at
     `web-companion/index.html` — the popup width should be pinned, the
     panel CSS already handles narrow viewports);
   - drop the `minimum_chrome_version` field.
2. Apply the `storage.session` shim in the background entry before other
   modules read session state.
3. Verify the fail-closed matrix from
   `docs/LIVE_SNIPER_SECURITY.md` on Safari: token expiry lockout,
   kill-switch 503 handling, blurred-tab pause.
4. Run the demo fixture loop (`npm run demo` + dev-bypass API) end-to-end
   on Safari before any real-origin adapter flag is considered.

## What cannot be ported

- Chrome's *new headless* e2e harness: the Playwright suite loads the MV3
  build via `--load-extension`; Safari automation goes through
  `safaridriver` + a built app — keep the e2e suite as the Chrome gate and
  add a manual Safari pass per release using the same fixture page.
- Any reliance on Chromium-only CSS (none used — the panel is standard
  flexbox/grid).

## Store review notes (Apple)

- Submit the privacy justification from `docs/LIVE_SNIPER_SECURITY.md`
  (no data collection category applies; the only network peer is the
  PropStein API).
- The demo fixture page must ship enabled so reviewers can exercise the
  full flow without a sportsbook account — same as the Chrome listing.
- Real-book host permissions should NOT be in the first submission
  (matches the adapter authorization model: scaffolds stay off).
