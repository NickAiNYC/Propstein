/**
 * PropStein Live Sniper — Polymarket Adapter Scaffold
 * =================================================
 * STATUS: DISABLED BY DEFAULT — feature-flag gated.
 *
 * Rationale: the repo ALREADY integrates Polymarket through its public
 * Gamma/CLOB APIs (src/agents/polymarket_agent.py) and that licensed,
 * documented API is the preferred data channel for Polymarket prices.
 * Page-level DOM inspection would only be justified for visible-market
 * UX affordances and must respect Polymarket's terms. The adapter therefore
 * ships as a scaffold and the backend path is the recommended source.
 */

import type { MarketChangeEvent, ObservedMarket } from "@propstein/core";
import { parseDecimalOddsText } from "@propstein/core";
import type { AdapterDetectionResult, VisibleMarketAdapter } from "./adapter.ts";
import { diffMarkets, type DifferHooks } from "../dom-extractor.ts";

export const POLYMARKET_ADAPTER_VERSION = "pm-selectors-v0.1-unverified";

export const POLYMARKET_SELECTORS = {
  marketGroup: "div[class*='market'], main",
  marketRow: "div[class*='MarketCard'], div[data-testid='market-card']",
  playerName: "span[class*='title'], h3",
  marketTitle: "div[class*='sub-title'], p",
  priceButton: "button[class*='outcome'], span[class*='price']",
} as const;

const HOST_ALLOWLIST = /^https:\/\/polymarket\.com$/;

export class PolymarketAdapter implements VisibleMarketAdapter {
  readonly platform = "polymarket" as const;
  readonly adapterVersion = POLYMARKET_ADAPTER_VERSION;
  private readonly now: () => Date;
  private unsubscribe: (() => void) | undefined;

  constructor(opts: { now?: () => Date } = {}) {
    this.now = opts.now ?? (() => new Date());
  }

  isSupportedPage(url: URL): boolean {
    return HOST_ALLOWLIST.test(url.origin);
  }

  async detectVisibleMarkets(root: Document): Promise<AdapterDetectionResult> {
    const rows = root.querySelectorAll(POLYMARKET_SELECTORS.marketRow);
    if (rows.length === 0) {
      return {
        markets: [],
        status: "ADAPTER_DEGRADED",
        confidence: 0,
        notes: ["no market cards matched — layout changed or page has no markets in view"],
      };
    }
    const markets: ObservedMarket[] = [];
    for (const row of Array.from(rows)) {
      const m = this.parseRow(row);
      if (m) markets.push(m);
    }
    if (markets.length === 0) {
      return {
        markets: [],
        status: "ADAPTER_DEGRADED",
        confidence: 0,
        notes: ["no rows parsed end-to-end — prefer the licensed CLOB API path over page parsing"],
      };
    }
    return { markets, status: "OK", confidence: 0.7, notes: ["parsed with UNVERIFIED selectors"] };
  }

  private parseRow(row: Element): ObservedMarket | undefined {
    const nameEl = row.querySelector(POLYMARKET_SELECTORS.playerName);
    const priceEl = row.querySelector(POLYMARKET_SELECTORS.priceButton);
    if (!nameEl?.textContent?.trim() || !priceEl?.textContent?.trim()) return undefined;
    // Polymarket displays cent prices ("62¢" = 0.62 probability → decimal 1.61).
    const cents = /^(\d+(?:\.\d+)?)¢$/.exec(priceEl.textContent!.trim());
    const parsedDecimal = cents ? 1 / (Number(cents[1]!) / 100) : parseDecimalOddsText(priceEl.textContent!.trim());
    if (parsedDecimal === undefined || parsedDecimal <= 1) return undefined;
    return {
      source: "polymarket",
      sport: "football",
      league: "NFL",
      playerName: nameEl.textContent!.trim(),
      marketType: row.querySelector(POLYMARKET_SELECTORS.marketTitle)?.textContent?.trim() ?? "",
      marketLabel: row.querySelector(POLYMARKET_SELECTORS.marketTitle)?.textContent?.trim() ?? "",
      selection: "YES",
      decimalOdds: parsedDecimal,
      marketStatus: "UNKNOWN",
      observedAt: this.now().toISOString(),
      adapterVersion: this.adapterVersion,
      detectionConfidence: 0.7,
      provenance: "visible-page",
    };
  }

  observeChanges(callback: (event: MarketChangeEvent) => void): () => void {
    const hooks: DifferHooks = {
      selectCards: (root) => Array.from(root.querySelectorAll(POLYMARKET_SELECTORS.marketRow)),
      parseCard: (el) => this.parseRow(el),
    };
    this.unsubscribe = diffMarkets(hooks, callback, { targetSelector: "main" });
    return () => this.unsubscribe?.();
  }
}
