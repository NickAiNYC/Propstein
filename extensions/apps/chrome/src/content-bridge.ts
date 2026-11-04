/**
 * PropStein Live Sniper — Content Bridge & Overlay Host
 * =====================================================
 * Injected into monitored sportsbook tabs:
 *  - Isolated world execution (CSP-safe, no inline scripts, no eval)
 *  - Closed Shadow DOM overlay host (mode: 'closed' ensures host.shadowRoot is null to page)
 *  - Global Panic Kill Switch (Ctrl+Shift+K / Cmd+Shift+K) clears all visible footprint
 *  - Fuzzy entity resolution: (player_last_name + market_scope + line_bucket)
 *  - 5-State workflow: MATCH -> VERIFY -> OVERLAY -> HANDOFF -> STALE
 *  - Human-confirm execution only ("Send to slip", "I placed it" audit receipt)
 *  - Zero network fetch from content script: all traffic routes via service worker
 */

import {
  AdapterRegistry,
  DemoBookAdapter,
  DraftKingsAdapter,
  FanDuelAdapter,
  PolymarketAdapter,
  marketIdentityKey,
  detectBookFromHost,
  extractMarketNodeFromElement,
  type VisibleMarketAdapter,
} from "@propstein/detection";
import {
  type BackendLiveSignal,
  type MarketChangeEvent,
  type PlacedAuditRecord,
  matchExtractedNodeToSignal,
} from "@propstein/core";
import { OverlayManager } from "@propstein/ui";

declare const chrome: {
  runtime: {
    sendMessage(msg: unknown): Promise<unknown>;
    onMessage: { addListener(cb: (msg: unknown, sender: unknown, respond: (r: unknown) => void) => boolean | void): void };
  };
};

let active = false;
let unsubscribe: (() => void) | undefined;
let overlayManager: OverlayManager | null = null;
let activeSignals: BackendLiveSignal[] = [];
let observer: MutationObserver | null = null;
let throttleTimer: ReturnType<typeof setTimeout> | undefined;

// ---------------------------------------------------------------------------
// Event coalescing
// ---------------------------------------------------------------------------
// The differ emits one callback per event, but a drive transition produces
// an ATOMICALLY-MEANINGFUL SET — REMOVED(old-drive keys) followed by
// ADDED(new-drive keys). The background can only interpret those removals as
// a drive invalidation when the whole set arrives in ONE batch.
const EVENT_BATCH_WINDOW_MS = 40;
const EVENT_BATCH_LIMIT = 200;

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
  draftkings: true,
  fanduel: true,
  polymarket: true,
  demobook: true,
});
REGISTRY.register(new DemoBookAdapter());
REGISTRY.register(new DraftKingsAdapter());
REGISTRY.register(new FanDuelAdapter());
REGISTRY.register(new PolymarketAdapter());

// ---------------------------------------------------------------------------
// Messaging helper: All network and telemetry routes through service worker
// ---------------------------------------------------------------------------

async function postToBackground(message: Record<string, unknown>): Promise<void> {
  try {
    await chrome.runtime.sendMessage(message);
  } catch {
    // Service worker reloaded / unavailable — fail safe
  }
}

// ---------------------------------------------------------------------------
// Match & Overlay Scan
// ---------------------------------------------------------------------------

function scanAndMatchVisibleMarkets(): void {
  if (!active || !overlayManager || overlayManager.isPanicKillEngaged()) return;
  if (activeSignals.length === 0) return;

  const book = detectBookFromHost(location.hostname);
  const rows = document.querySelectorAll(
    '[data-testid*="prop-card"], [data-testid*="market"], .sportsbook-market-row, .demobook-card, tr[data-testid*="row"]'
  );

  const telemetryEvents: Array<{
    book: string;
    outcome: "MATCHED" | "AMBIGUOUS" | "NO_EXTRACTION" | "MULTI_MATCH" | "MARKET_UNSCOPEABLE";
    details?: string;
    client_latency_ms?: number;
    timestamp: string;
  }> = [];

  const startScanTime = Date.now();

  for (const row of rows) {
    const extracted = extractMarketNodeFromElement(row, book);
    if (!extracted) {
      telemetryEvents.push({
        book,
        outcome: "NO_EXTRACTION",
        details: "DOM element missing expected player/market attributes",
        client_latency_ms: Date.now() - startScanTime,
        timestamp: new Date().toISOString(),
      });
      continue;
    }

    if (!extracted.rawMarket || extracted.rawMarket.toLowerCase().includes("unknown")) {
      telemetryEvents.push({
        book,
        outcome: "MARKET_UNSCOPEABLE",
        details: `Unscopeable market: ${extracted.rawMarket}`,
        client_latency_ms: Date.now() - startScanTime,
        timestamp: new Date().toISOString(),
      });
      continue;
    }

    const matchedSignal = matchExtractedNodeToSignal(extracted, activeSignals, 1.5);
    if (!matchedSignal) {
      const name = (extracted.rawPlayer || "").trim().toLowerCase();
      const candidates = activeSignals.filter((s) => s.playerName.toLowerCase().includes(name));
      if (candidates.length > 1) {
        telemetryEvents.push({
          book,
          outcome: "MULTI_MATCH",
          details: `Multiple candidates for ${extracted.rawPlayer} (${candidates.length})`,
          client_latency_ms: Date.now() - startScanTime,
          timestamp: new Date().toISOString(),
        });
      } else {
        telemetryEvents.push({
          book,
          outcome: "AMBIGUOUS",
          details: `Line ${extracted.line} outside tolerance for ${extracted.rawPlayer}`,
          client_latency_ms: Date.now() - startScanTime,
          timestamp: new Date().toISOString(),
        });
      }
      continue;
    }

    telemetryEvents.push({
      book,
      outcome: "MATCHED",
      details: `${matchedSignal.playerName} ${matchedSignal.marketType} line=${matchedSignal.line}`,
      client_latency_ms: Date.now() - startScanTime,
      timestamp: new Date().toISOString(),
    });

    // Find odds button to anchor overlay next to price
    const anchor = row.querySelector('button, [data-testid*="price"], [data-testid*="odds"]') || row;

    overlayManager.renderOverlay(anchor, matchedSignal, {
      onSendToSlip: () => {
        // Human-initiated stage: click the odds button on the book page
        if (anchor instanceof HTMLElement) {
          anchor.click();
        }
      },
    });
  }

  if (telemetryEvents.length > 0) {
    void postToBackground({
      type: "MATCH_TELEMETRY",
      events: telemetryEvents,
    });
  }
}

function throttledScan(): void {
  if (throttleTimer) return;
  throttleTimer = setTimeout(() => {
    throttleTimer = undefined;
    scanAndMatchVisibleMarkets();
  }, 100);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

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

  // Initialize closed Shadow DOM overlay manager
  overlayManager = new OverlayManager({
    doc: document,
    onPanicKillChange: (isPanic) => {
      void postToBackground({ type: "PANIC_KILL_SWITCH", active: isPanic });
    },
    onAuditPlaced: (record: PlacedAuditRecord) => {
      void postToBackground({ type: "AUDIT_PLACED_RECORD", record });
    },
  });
  overlayManager.init();

  // Request latest active signals from service worker
  void chrome.runtime.sendMessage({ type: "GET_ACTIVE_SIGNALS" }).then((resp: unknown) => {
    const r = resp as { signals?: BackendLiveSignal[] } | undefined;
    if (r?.signals) {
      activeSignals = r.signals;
      throttledScan();
    }
  });

  // Watch DOM mutations with 100ms throttle
  observer = new MutationObserver(() => {
    throttledScan();
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });

  // Initial detection pass
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
  pendingEvents = [];
  if (throttleTimer) {
    clearTimeout(throttleTimer);
    throttleTimer = undefined;
  }
  observer?.disconnect();
  observer = null;
  unsubscribe?.();
  unsubscribe = undefined;
  overlayManager?.destroy();
  overlayManager = null;
}

// ---------------------------------------------------------------------------
// Background message listener
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg: unknown, _sender: unknown, respond: (r: unknown) => void) => {
  const m = msg as {
    type?: string;
    correlationId?: string;
    signals?: BackendLiveSignal[];
    active?: boolean;
    signalId?: string;
  } | undefined;
  if (!m?.type) return;

  if (m.type === "SNIPE_START") {
    start();
    respond({ ok: active, correlationId: m.correlationId });
  } else if (m.type === "SNIPE_STOP") {
    stop();
    respond({ ok: true, correlationId: m.correlationId });
  } else if (m.type === "SIGNALS_UPDATE" && m.signals) {
    activeSignals = m.signals;
    throttledScan();
    respond({ ok: true });
  } else if (m.type === "PANIC_KILL_SWITCH") {
    if (m.active !== undefined && overlayManager) {
      if (overlayManager.isPanicKillEngaged() !== m.active) {
        overlayManager.togglePanicKill();
      }
    }
    respond({ ok: true });
  }
});

addEventListener("pagehide", stop);

export {};
