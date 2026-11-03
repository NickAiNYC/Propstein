# Live Sniper — Adapter Contract & Authorization Rollout

The detection layer is the only component that understands individual
sportsbook DOM. Everything downstream consumes the canonical
`ObservedMarket` and never knows which book it came from. This document
defines that contract and the process for turning a scaffolded real-book
adapter on.

## The contract (`packages/detection/src/adapters/adapter.ts`)

```ts
interface VisibleMarketAdapter {
  readonly platform: string;          // "demobook" | "draftkings" | ...
  readonly adapterVersion: string;    // selector-set version, e.g. "0.1.0"
  supports(url: URL): boolean;        // host/path match for this book
  detectVisibleMarkets(doc: Document): Promise<DetectionResult>;
  observeChanges(onEvent: (e: MarketChangeEvent) => void): () => void;
}
```

Guarantees every adapter must uphold:

1. **Visible-only.** Cards failing the shared visibility predicate are
   never parsed (no offscreen/infinite-list harvesting).
2. **Confidence-scored.** Each observation carries
   `detectionConfidence ∈ [0,1]`. Structural anchors (stable attributes,
   data-* hooks) score high; fuzzy text parsing scores low. Below the floor
   (0.6) the engine refuses to alert (`UNVERIFIED`) — the adapter "losing
   identity" is a withdrawal condition, not a best-effort guess.
3. **Versioned selectors.** `adapterVersion` is reported end-to-end and
   appears in withdrawal reasons. A selector change is a version bump, so
   field debugging can correlate misparses with a selector set.
4. **Fail-safe degradation.** Unparseable card → no observation (the signal
   goes stale), never a fabricated one. Unknown market wording →
   `UNVERIFIED`, never a guess.
5. **Read-only.** Adapters never dispatch events, click, or mutate the
   page. The DemoBook fixture's *control buttons* are page-side fixtures —
   the adapter only reads the resulting DOM.

## Current registry state

| Platform | Adapter file | Flag | Selector source |
|---|---|---|---|
| `demobook` | `adapters/synthetic.ts` | **ON** | Owns the fixture contract (`data-ps-*`) — deterministic |
| `draftkings` | `adapters/draftkings.ts` | OFF (scaffold) | Placeholder; empty until validation |
| `fanduel` | `adapters/fanduel.ts` | OFF (scaffold) | Placeholder |
| `polymarket` | `adapters/polymarket.ts` | OFF (scaffold) | Placeholder — licensed Gamma/CLOB API preferred over DOM |

The flags live in the content bridge's `AdapterRegistry` and are the
remote kill-switch surface: a build with flags flipped is the operator's
explicit act, recorded in code review.

## Enabling a real-book adapter — the checklist

Doing these out of order is how projects end up in ToS litigation or
shipping garbage selectors; the order is deliberate.

1. **Written authorization.** Documented permission from the book (or a
   confirmed reading that user-agent-assisted display for personal use is
   permitted under their terms). Note: DraftKings/FanDuel player-prop data
   already arrives in this repo via the licensed **PropLine** API — page
   adapters are a *display-context* enhancement, not the data channel.
2. **Selector validation pass.** Against saved, consented page snapshots
   (the repo's `test/fixtures/` convention with `_fixture` flags):
   - every selector resolves on N ≥ 30 snapshots across viewport sizes;
   - a mutation-injected misparse battery (garbled label, missing attr,
     swapped odds) drives confidence below the floor and the engine
     withdraws;
   - linkedom integration tests for the parse table.
3. **Kill-switch wiring.** The selector set ships with an `adapterVersion`
   and a documented server-side "minimum healthy adapter version" so a bad
   release can be switched off without a store review cycle.
4. **Staged rollout.** Flag ON for internal profiles → opt-in beta
   (`chrome.storage.local` preference) → GA. Watch withdrawal-reason
   distributions: a spike in `LOW_DETECTION_CONFIDEDENCE` means the
   selector set rotted — disable, don't limp.
5. **Selector rotation plan.** Books redesign. Adapters are expected to
   break; the design goal is that they break *loudly* (withdrawals), never
   *quietly* (wrong prices).

## Why DOM adapters at all, when licensed feeds exist?

The product promise is **"the market you are looking at, priced now"**:
the panel must react to the exact price the user sees, including prices a
feed lags on or never carries (in-play drive props). Licensed feeds remain
the source of truth for *model inputs* (player params, possession state);
the DOM adapter supplies *display-context quotes*, labeled `OBSERVED`.
That division is what keeps the honesty model intact: page data is never
laundered into model output, and model output is never presented as a
page observation.
