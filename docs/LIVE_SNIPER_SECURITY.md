# Live Sniper — Security & Privacy Model

Audience: Chrome Web Store review, Apple App Review (Safari wrapper), and
PropStein operators. This document is the authoritative statement of what
the extension does and does not do. The upstream repository audit
(`docs/LIVE_SNIPER_AUDIT.md`, findings S-1…S-8) motivates every control
below.

## Data flow inventory

| Data | Where it lives | Leaves the browser? |
|---|---|---|
| Observed market DOM (odds text, labels, attributes) | In-memory signal registry in the service worker | **No.** Never transmitted; never persisted to disk |
| Signal snapshots (state, EV, reasons) | Service worker memory + panel render | **No.** |
| Scoped session token | `chrome.storage.session` (memory-backed; cleared when the browser closes) | Sent only to the PropStein API as an `Authorization` header — never in a URL/query |
| PropStein membership token (user-pasted) | Held only long enough to exchange; not written to `chrome.storage.local` | Sent once to `POST /api/v1/extension/session` over HTTPS |
| Settings (thresholds, panel options) | `chrome.storage.local` | **No.** |
| Ledger of OBSERVED quotes | Service worker memory | **No.** |

**The extension never reads, stores, or transmits sportsbook credentials,
cookies, session tokens, payment details, or anything typed into the
monitored page.** The content bridge runs in the isolated world with no
access to page JavaScript; it queries market-card DOM nodes only.

## Permission justification (Chrome Web Store)

| Permission | Why it is required | Why it is minimal |
|---|---|---|
| `storage` | Panel settings + memory-backed session state | `chrome.storage.session`/`local` only; no `unlimitedStorage` |
| `scripting` | Inject the read-only observation bridge into the tab the user explicitly started monitoring | Programmatic injection on user action; nothing at install time; bridge source is auditable in `apps/chrome/src/content-bridge.ts` |
| `tabs` | Track the *active content tab* so monitoring pauses on blur and never targets unrelated tabs | Only URL/tab-id bookkeeping; no content reading of other tabs |
| `sidePanel` | The panel itself | UI surface only |
| Host permissions | **None requested at install.** Per-origin grants are requested at runtime via `chrome.permissions.request()` when the user starts monitoring that origin | Granted origins are enumerated in `packages/browser/src/permissions.ts` |

## Trust boundaries

1. **Page → bridge.** All DOM-derived data is untrusted. Every inbound
   `MARKET_EVENTS` batch passes `validateMarketEventBatch`: type checks,
   per-string length clamps, control-character stripping (anti-markup
   smuggling), a 200-event cap, and field-level sanitization before any
   value reaches the signal engine.
2. **Bridge/page → background.** `chrome.runtime.onMessage` handlers verify
   `sender.id === chrome.runtime.id`; bridge traffic additionally requires
   the sender origin to be in the granted-origin set. Extension-page
   traffic and content traffic are separated by message type.
3. **Background → API.** HTTPS only; scoped token in the `Authorization`
   header; fail closed on 401/403/5xx/network error (no silent downgrade to
   free data).
4. **API → extension.** Session tokens are HMAC-SHA256 signed with
   `exp`/`iat`/`jti`, revocable, 15-minute TTL, issued only after a
   server-side Whop entitlement check. The raw membership id never
   authorizes a market route.

## Fail-closed matrix

| Condition | Behavior |
|---|---|
| Membership not verifiable (API down / key missing) | Session issuance returns 503; no session, no model data, panel shows SIGN IN REQUIRED |
| Scoped token expired / tampered / revoked | 401 on every market route; the panel's expiry watcher locks the panel to SESSION_EXPIRED |
| `EXTENSION_KILL_SWITCH=1` on the server | Health reports disabled; session issuance and all market routes 503 |
| Quote older than the freshness limit (20s live odds) | Signal → `STALE` (withdrawn, reason shown) |
| Market suspended/closed at the book | Signal → `SUSPENDED` (withdrawn) |
| Drive ended | Every signal bound to that drive → withdrawn (`DRIVE ENDED`), even if the price is still visible |
| Adapter confidence below floor (0.6) | Signal → `UNVERIFIED`; never alertable |
| Tab blurred/closed/navigated | Observation pauses; signals withdraw; nothing monitors unrelated tabs |

There is **no** fail-open path: every error branch withdraws the signal or
locks the panel.

## Non-goals that are also non-features

- **No bet placement.** No code can click a bet slip, submit a form, or
  manipulate prices on the monitored page. The bridge is read-only by
  construction.
- **No scraping of hidden content.** Only viewport-visible market cards are
  parsed; virtualized/offscreen cards are filtered before parsing.
- **No anti-bot evasion.** The extension attaches to the user's own
  legitimate session and renders exactly what that session renders.
- **No telemetry.** No analytics, no crash reporting, no remote logging in
  v0.1.0 (adding any requires an updated privacy disclosure and review).

## Upstream findings this branch mitigates

- **S-1** (public market endpoints): all new `/api/v1/markets/*` routes are
  entitlement-gated server-side.
- **S-2** (forgeable client tier): the panel's EntitlementGate renders only
  server-verified entitlement; `localStorage` tier hints are ignored.
- **S-3** (long-lived unscoped bearer): replaced by scoped, revocable,
  15-minute tokens for every extension-originated call.
- **S-4** (stale host permissions / borrowed viewer packaging): fresh
  manifest with minimal permissions and a purpose-built panel.
- **S-6** (shared internal key for subscriber routes): per-session tokens +
  per-principal rate limiting on session issuance.
