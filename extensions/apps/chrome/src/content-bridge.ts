/**
 * PropStein Live Sniper — Content Bridge (isolated world)
 * ====================================================
 * Injected INTO THE MONITORED TAB ONLY on explicit SNIPE_START, after the
 * user granted that site's origin. Runs in the ISOLATED world: it reads the
 * page DOM through the adapter but has no access to page JavaScript or
 * credentials, and it NEVER touches betting controls — no clicks, no form
 * submission, no price manipulation. Read-only observation.
 *
 * The bridge is generic: it asks the adapter registry to resolve the page,
 * then drives the shared batched DOM differ. Unrelated tabs are never
 * injected; SNIPE_STOP disconnects all observers immediately.
 */

import {
  AdapterRegistry,
  DemoBookAdapter,
  DraftKingsAdapter,
  FanDuelAdapter,
  PolymarketAdapter,
  diffMarkets,
  marketIdentityKey,
  type VisibleMarketAdapter,
} from "@propstein/detection";
import type { MarketChangeEvent } from "@propstein/core";

declare const chrome: {
  runtime: {
    sendMessage(msg: unknown): Promise<unknown>;
    onMessage: { addListener(cb: (msg: unknown, sender: unknown, respond: (r: unknown) => void) => boolean | void): void };
  };
};

let active = false;
let unsubscribe: (() => void) | undefined;

// ---------------------------------------------------------------------------
// Event coalescing
// ---------------------------------------------------------------------------
// The differ emits one callback per event, but a drive transition produces
// an ATOMICALLY-MEANINGFUL SET — REMOVED(old-drive keys) followed by
// ADDED(new-drive keys). The background can only interpret those removals as
// a drive invalidation (spec §15 critical test) when the whole set arrives in
// ONE batch: per-event messages race the drive-context adoption, and the old
// signals get silently remove()d instead of driveEnded(). A short coalescing
// window fixes this AND cuts message overhead on mutation bursts.
const EVENT_BATCH_WINDOW_MS = 40;
const EVENT_BATCH_LIMIT = 200; // protocol MAX_EVENTS_PER_MESSAGE

let pendingEvents: MarketChangeEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | undefined;

function flushPendingEvents(): void {
  flushTimer = undefined;
  if (pendingEvents.length === 0) return;
  const events = pendingEvents;
  pendingEvents = [];
  void postToBackground({ type: "MARKET_EVENTS", correlationId: "live", events });
}

function enqueueEvent(event: MarketChangeEvent): void {
  if (!active) return;
  pendingEvents.push(event);
  if (pendingEvents.length >= EVENT_BATCH_LIMIT) {
    if (flushTimer !== undefined) clearTimeout(flushTimer);
    flushPendingEvents();
    return;
  }
  if (flushTimer === undefined) {
    flushTimer = setTimeout(flushPendingEvents, EVENT_BATCH_WINDOW_MS);
  }
}

const REGISTRY = new AdapterRegistry({
  // Real sportsbook adapters stay OFF until authorization + fixture
  // validation. The feature flags are the remote kill switch surface.
  draftkings: false,
  fanduel: false,
  polymarket: false,
  demobook: true,
});
REGISTRY.register(new DemoBookAdapter());
REGISTRY.register(new DraftKingsAdapter());
REGISTRY.register(new FanDuelAdapter());
REGISTRY.register(new PolymarketAdapter());

async function postToBackground(message: Record<string, unknown>): Promise<void> {
  try {
    await chrome.runtime.sendMessage(message);
  } catch {
    // Background gone (extension reloaded) — stop observing to fail closed.
    stop();
  }
}

function start(): void {
  if (active) return;
  const url = new URL(location.href);
  const resolved = REGISTRY.resolve(url);
  if (!resolved.adapter) {
    void postToBackground({ type: "BRIDGE_STATUS", status: "PAGE_UNSUPPORTED", detail: resolved.reason });
    return;
  }
  const adapter: VisibleMarketAdapter = resolved.adapter;
  active = true;

  // Initial full detection pass, then mutation-driven updates.
  void adapter.detectVisibleMarkets(document).then((result) => {
    if (!active) return;
    if (result.status !== "OK") {
      void postToBackground({ type: "BRIDGE_STATUS", status: result.status, detail: result.notes.join("; ") });
    }
    const events: MarketChangeEvent[] = result.markets.map((m) => ({
      kind: "ADDED",
      signalKey: marketIdentityKey(m),
      market: m,
      at: m.observedAt,
    }));
    if (events.length > 0) {
      void postToBackground({ type: "MARKET_EVENTS", correlationId: "initial", events });
    }
  });

  unsubscribe = adapter.observeChanges((event) => {
    if (!active) return;
    if (event.kind === "NAVIGATED") {
      // Preserve causal order: drain events belonging to the old page first.
      if (flushTimer !== undefined) clearTimeout(flushTimer);
      flushPendingEvents();
      void postToBackground({ type: "MARKET_EVENTS", correlationId: "nav", events: [{ kind: "NAVIGATED", at: event.at }] });
      return;
    }
    enqueueEvent(event);
  });
}

function stop(): void {
  active = false;
  if (flushTimer !== undefined) {
    clearTimeout(flushTimer);
    flushTimer = undefined;
  }
  pendingEvents = []; // fail closed: never emit events observed before stop
  unsubscribe?.();
  unsubscribe = undefined;
}

chrome.runtime.onMessage.addListener((msg: unknown, _sender: unknown, respond: (r: unknown) => void) => {
  const m = msg as { type?: string; correlationId?: string } | undefined;
  if (!m?.type) return;
  if (m.type === "SNIPE_START") {
    start();
    respond({ ok: active, correlationId: m.correlationId });
  } else if (m.type === "SNIPE_STOP") {
    stop();
    respond({ ok: true, correlationId: m.correlationId });
  }
  return;
});

// Fail closed when the page unloads.
addEventListener("pagehide", stop);

export {};
