/**
 * PropStein Live Sniper — DraftKings Adapter Scaffold
 * =================================================
 * STATUS: DISABLED BY DEFAULT — feature-flag gated.
 *
 * AUTHORIZATION REQUIRED BEFORE ENABLING:
 *  - DraftKings terms of service must be reviewed for automated page reading.
 *  - The repo's licensed DK/FD data channel today is the PropLine commercial
 *    API (see docs/LIVE_SNIPER_AUDIT.md §2.2). Page-level DOM inspection is a
 *    SEPARATE permission question and is not covered by the PropLine license.
 *  - Selectors below are UNVERIFIED STRUCTURAL HYPOTHESES based on common
 *    sportsbook UI patterns. They MUST be validated against captured page
 *    fixtures before any release, and the adapter must fail safe on any
 *    mismatch — which is exactly what this scaffold does.
 *
 * BEHAVIOR TODAY:
 *  - isSupportedPage: strict host/path allowlist.
 *  - detectVisibleMarkets: attempts parse; on any structural miss returns
 *    ADAPTER_DEGRADED with ZERO markets (never invented matches).
 *  - The registry refuses to resolve this adapter while the feature flag is
 *    off, so the product shows MARKET UNSUPPORTED on DK pages instead of
 *    silently scraping.
 */

import type { MarketChangeEvent, ObservedMarket } from "@propstein/core";
import { parseAmericanOddsText } from "@propstein/core";
import type { AdapterDetectionResult, VisibleMarketAdapter } from "./adapter.ts";
import { diffMarkets, type DifferHooks } from "../dom-extractor.ts";

export const DRAFTKINGS_ADAPTER_VERSION = "dk-selectors-v0.1-unverified";

/** Versioned selector set — bump the version when layouts change. */
export const DRAFTKINGS_SELECTORS = {
  /** Live player-prop market group container. */
  marketGroup: "div[data-testid='player-prop-markets']",
  /** A single market row (player + line + odds buttons). */
  marketRow: "tr[data-testid*, 'prop-row'], div[data-testid='prop-card']",
  playerName: "[data-testid='prop-player-name']",
  marketTitle: "[data-testid='prop-market-title'], [class*='market-title']",
  line: "[data-testid='prop-line'], [class*='prop-line']",
  oddsButton: "button[data-testid*='outcome-button'], div[data-testid*='odds']",
} as const;

const HOST_ALLOWLIST = /^https:\/\/sportsbook\.draftkings\.com$/;
const LIVE_PATHS = /^\/(in-game|live-betting|leagues\/nfl)/;

export class DraftKingsAdapter implements VisibleMarketAdapter {
  readonly platform = "draftkings" as const;
  readonly adapterVersion = DRAFTKINGS_ADAPTER_VERSION;
  private readonly now: () => Date;
  private unsubscribe: (() => void) | undefined;

  constructor(opts: { now?: () => Date } = {}) {
    this.now = opts.now ?? (() => new Date());
  }

  isSupportedPage(url: URL): boolean {
    return HOST_ALLOWLIST.test(url.origin) && LIVE_PATHS.test(url.pathname);
  }

  async detectVisibleMarkets(root: Document): Promise<AdapterDetectionResult> {
    const group = root.querySelector(DRAFTKINGS_SELECTORS.marketGroup);
    if (!group) {
      return this.degraded("live prop market container not found — DK layout may have changed or this page has no live props");
    }
    const rows = group.querySelectorAll(DRAFTKINGS_SELECTORS.marketRow);
    if (rows.length === 0) {
      return this.degraded("market container present but no rows matched the versioned selectors");
    }
    // Structural parse attempt. Every field must resolve or the row is
    // skipped — partial parses never produce invented markets.
    const markets: ObservedMarket[] = [];
    for (const row of Array.from(rows)) {
      const m = this.parseRow(root, row);
      if (m) markets.push(m);
    }
    if (markets.length === 0) {
      return this.degraded("rows found but none parsed end-to-end — selectors require fixture validation before enabling");
    }
    return {
      markets,
      status: "OK",
      confidence: 0.7, // Hypothesis-grade confidence; raised only after fixture validation.
      notes: ["parsed with UNVERIFIED selectors — enable only after authorization and fixture capture"],
    };
  }

  private parseRow(root: Document, row: Element): ObservedMarket | undefined {
    const playerNameEl = row.querySelector(DRAFTKINGS_SELECTORS.playerName);
    const marketTitleEl = row.querySelector(DRAFTKINGS_SELECTORS.marketTitle) ?? root.querySelector("h1");
    const oddsEl = row.querySelector(DRAFTKINGS_SELECTORS.oddsButton);
    if (!playerNameEl?.textContent?.trim()) return undefined;
    const americanOdds = parseAmericanOddsText(oddsEl?.textContent ?? "");
    if (americanOdds === undefined) return undefined;
    return {
      source: "draftkings",
      sport: "football",
      league: "NFL",
      playerName: playerNameEl.textContent!.trim(),
      marketType: marketTitleEl?.textContent?.trim() ?? "",
      marketLabel: marketTitleEl?.textContent?.trim() ?? "",
      selection: "YES",
      americanOdds,
      marketStatus: "UNKNOWN",
      observedAt: this.now().toISOString(),
      adapterVersion: this.adapterVersion,
      detectionConfidence: 0.7,
      provenance: "visible-page",
    };
  }

  private degraded(reason: string): AdapterDetectionResult {
    return {
      markets: [],
      status: "ADAPTER_DEGRADED",
      confidence: 0,
      notes: [reason, "adapter ships disabled by feature flag pending authorization and fixture validation"],
    };
  }

  observeChanges(callback: (event: MarketChangeEvent) => void): () => void {
    const hooks: DifferHooks = {
      selectCards: (root) => Array.from(root.querySelectorAll(DRAFTKINGS_SELECTORS.marketRow)),
      parseCard: (el) => this.parseRow(el.ownerDocument ?? document, el),
    };
    this.unsubscribe = diffMarkets(hooks, callback, { targetSelector: DRAFTKINGS_SELECTORS.marketGroup });
    return () => this.unsubscribe?.();
  }
}
