/**
 * PropStein Live Sniper — Batched DOM Extraction & Change Differencing
 * ==================================================================
 * Mutation-driven pipeline (spec §4.1):
 *  - MutationObserver scoped to the adapter's market container
 *  - ADAPTIVE BATCHING: mutation records are collected and flushed on an
 *    animation-frame cadence; the batch window adapts between 16ms and
 *    200ms based on measured flush cost (CPU/battery control)
 *  - No full-page polling loops — processing happens only on mutations
 *  - Pure `computeChangeEvents` differ: ADDED / ODDS_CHANGED / LABEL_CHANGED
 *    / STATUS_CHANGED / SUSPENDED / REMOVED / NAVIGATED
 *  - Virtualized lists are handled naturally: destroyed cards emit REMOVED,
 *    re-created cards with identical identity update in place (no spurious
 *    ADDED), and only elements passing the visibility predicate are
 *    considered.
 *  - SPA navigation is detected by comparing location.href at flush time
 *    (a cheap string compare, not a polling loop).
 */

import type { MarketChangeEvent, MarketChangeKind, ObservedMarket } from "@propstein/core";
import { classifyMarketLabel } from "@propstein/core";

/** Stable identity for a market card across re-renders and cosmetic relabels. */
export function marketIdentityKey(m: ObservedMarket): string {
  const scope = classifyMarketLabel(`${m.marketType} ${m.marketLabel}`).code;
  return [
    m.source,
    m.eventId ?? "no-event",
    m.playerId ?? m.playerName.toLowerCase(),
    scope,
    m.selection,
    m.line !== undefined ? String(m.line) : "",
    m.driveId ?? "no-drive",
  ].join("|");
}

// ---------------------------------------------------------------------------
// Pure differ — unit-testable without a DOM
// ---------------------------------------------------------------------------

export interface MarketIdentity {
  key: string;
  observed: ObservedMarket;
}

function oddsOf(m: ObservedMarket): number | undefined {
  return m.americanOdds ?? m.decimalOdds;
}

function labelOf(m: ObservedMarket): string {
  return `${m.marketType}|${m.marketLabel}|${m.selection}`;
}

/**
 * Compute change events between two observations of the same market set.
 * `previous`/`current` are keyed by stable signal identity.
 */
export function computeChangeEvents(
  previous: Map<string, ObservedMarket>,
  current: Map<string, ObservedMarket>,
  at: string,
): MarketChangeEvent[] {
  const events: MarketChangeEvent[] = [];

  for (const [key, prev] of previous) {
    const curr = current.get(key);
    if (!curr) {
      events.push({ kind: "REMOVED", signalKey: key, at });
      continue;
    }
    if (oddsOf(prev) !== oddsOf(curr)) {
      const kind: MarketChangeKind = "ODDS_CHANGED";
      events.push({
        kind,
        signalKey: key,
        market: curr,
        detail: `${String(oddsOf(prev))} → ${String(oddsOf(curr))}`,
        at,
      });
      continue;
    }
    if (labelOf(prev) !== labelOf(curr)) {
      events.push({ kind: "LABEL_CHANGED", signalKey: key, market: curr, at });
      continue;
    }
    if (prev.marketStatus !== curr.marketStatus) {
      events.push({
        kind: curr.marketStatus === "SUSPENDED" ? "SUSPENDED" : "STATUS_CHANGED",
        signalKey: key,
        market: curr,
        detail: `${prev.marketStatus} → ${curr.marketStatus}`,
        at,
      });
      continue;
    }
    // Same identity, same content — refresh the observation timestamp only.
    events.push({ kind: "ODDS_CHANGED", signalKey: key, market: curr, detail: "re-observed", at });
  }

  for (const [key, curr] of current) {
    if (!previous.has(key)) {
      events.push({ kind: "ADDED", signalKey: key, market: curr, at });
    }
  }
  return events;
}

// ---------------------------------------------------------------------------
// Browser wiring — adaptive batching + visibility + SPA navigation
// ---------------------------------------------------------------------------

export interface DifferHooks {
  selectCards: (root: Document) => Element[];
  parseCard: (el: Element) => ObservedMarket | undefined;
  /** Visibility predicate; defaults to "element is connected to the DOM". */
  isVisible?: (el: Element) => boolean;
}

export interface DiffOptions {
  /** Selector for the observed subtree (adapter market container). */
  targetSelector: string;
  /** Initial batch window (ms). Defaults to 16 (one frame). */
  initialBatchMs?: number;
  /** Max batch window under sustained load. Defaults to 200. */
  maxBatchMs?: number;
  /** Flush cost budget (ms) for the adaptive controller. Defaults to 8. */
  budgetMs?: number;
  /** Scheduler injection for deterministic tests. */
  schedule?: (fn: () => void, ms: number) => () => void;
  /** Clock injection for deterministic tests. */
  now?: () => Date;
}

export function diffMarkets(
  hooks: DifferHooks,
  onChange: (event: MarketChangeEvent) => void,
  opts: DiffOptions,
): () => void {
  const initialBatchMs = opts.initialBatchMs ?? 16;
  const maxBatchMs = opts.maxBatchMs ?? 200;
  const budgetMs = opts.budgetMs ?? 8;
  const now = opts.now ?? (() => new Date());
  const schedule =
    opts.schedule ??
    ((fn: () => void, ms: number) => {
      if (typeof requestAnimationFrame === "function" && ms <= 16) {
        const id = requestAnimationFrame(fn);
        return () => cancelAnimationFrame(id);
      }
      const id = setTimeout(fn, ms);
      return () => clearTimeout(id);
    });

  if (typeof MutationObserver === "undefined" || typeof document === "undefined") {
    return () => undefined; // No DOM — nothing to observe (unit-test context).
  }

  let previous = new Map<string, ObservedMarket>();
  let lastHref = typeof location !== "undefined" ? location.href : "";
  let batchWindowMs = initialBatchMs;
  let scheduled: (() => void) | undefined;
  let pending = false;
  let stopped = false;

  const isVisible = hooks.isVisible ?? ((el: Element) => el.isConnected);

  function flush(): void {
    pending = false;
    scheduled = undefined;
    if (stopped) return;
    const start = performance.now();

    // SPA navigation detection — string compare only.
    const href = typeof location !== "undefined" ? location.href : "";
    if (href !== lastHref) {
      lastHref = href;
      previous = new Map();
      onChange({ kind: "NAVIGATED", detail: href, at: now().toISOString() });
    }

    const current = new Map<string, ObservedMarket>();
    for (const el of hooks.selectCards(document)) {
      if (!isVisible(el)) continue;
      const market = hooks.parseCard(el);
      if (!market) continue;
      current.set(marketIdentityKey(market), market);
    }

    const events = computeChangeEvents(previous, current, now().toISOString());
    previous = current;
    for (const e of events) onChange(e);

    // Adaptive batch controller: shrink when cheap, grow when expensive.
    const cost = performance.now() - start;
    if (cost > budgetMs) {
      batchWindowMs = Math.min(maxBatchMs, Math.max(batchWindowMs * 1.5, 16));
    } else if (cost < budgetMs / 2 && batchWindowMs > initialBatchMs) {
      batchWindowMs = Math.max(initialBatchMs, batchWindowMs / 1.25);
    }
  }

  function onMutations(): void {
    if (pending || stopped) return;
    pending = true;
    scheduled = schedule(flush, batchWindowMs);
  }

  const target = document.querySelector(opts.targetSelector) ?? document.body;
  const observer = new MutationObserver(onMutations);
  observer.observe(target, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: [
      "data-ps-american-odds", "data-ps-odds-text", "data-ps-market-status",
      "data-ps-player-name", "data-ps-market-label", "data-ps-line",
      "data-ps-drive-id", "data-ps-event-id", "data-ps-feed-tick",
      "class", "style",
    ],
  });

  // Initial sweep.
  onMutations();

  return () => {
    stopped = true;
    observer.disconnect();
    scheduled?.();
    previous = new Map();
  };
}

/** Re-observation policy helper for virtualized containers. */
export function elementsConnected(els: Element[]): boolean {
  return els.every((el) => el.isConnected);
}
