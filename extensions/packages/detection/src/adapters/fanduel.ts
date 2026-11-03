/**
 * PropStein Live Sniper — FanDuel Adapter Scaffold
 * ===============================================
 * STATUS: DISABLED BY DEFAULT — feature-flag gated (same authorization and
 * fixture-validation requirements as the DraftKings scaffold; see that
 * file's header for the full rationale).
 */

import type { MarketChangeEvent, ObservedMarket } from "@propstein/core";
import { parseAmericanOddsText } from "@propstein/core";
import type { AdapterDetectionResult, VisibleMarketAdapter } from "./adapter.ts";
import { diffMarkets, type DifferHooks } from "../dom-extractor.ts";

export const FANDUEL_ADAPTER_VERSION = "fd-selectors-v0.1-unverified";

export const FANDUEL_SELECTORS = {
  marketGroup: "div[class*='live'] af-dropdown-list, div[data-testid='market-group']",
  marketRow: "li[class*='market'], div[data-testid='market-item']",
  playerName: "span[class*='participant'], div[data-testid='player-name']",
  marketTitle: "h2[class*='title'], div[data-testid='market-title']",
  oddsButton: "button[class*='selection'], div[data-testid='odds-button']",
} as const;

const HOST_ALLOWLIST = /^https:\/\/sportsbook\.fanduel\.com$/;
const LIVE_PATHS = /^\/(in-play|live|leagues\/nfl)/;

export class FanDuelAdapter implements VisibleMarketAdapter {
  readonly platform = "fanduel" as const;
  readonly adapterVersion = FANDUEL_ADAPTER_VERSION;
  private readonly now: () => Date;
  private unsubscribe: (() => void) | undefined;

  constructor(opts: { now?: () => Date } = {}) {
    this.now = opts.now ?? (() => new Date());
  }

  isSupportedPage(url: URL): boolean {
    return HOST_ALLOWLIST.test(url.origin) && LIVE_PATHS.test(url.pathname);
  }

  async detectVisibleMarkets(root: Document): Promise<AdapterDetectionResult> {
    const group = root.querySelector(FANDUEL_SELECTORS.marketGroup);
    if (!group) {
      return {
        markets: [],
        status: "ADAPTER_DEGRADED",
        confidence: 0,
        notes: ["live market container not found — FD layout may have changed or this page has no live props"],
      };
    }
    const rows = group.querySelectorAll(FANDUEL_SELECTORS.marketRow);
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
        notes: ["no rows parsed end-to-end — selectors require fixture validation before enabling"],
      };
    }
    return { markets, status: "OK", confidence: 0.7, notes: ["parsed with UNVERIFIED selectors"] };
  }

  private parseRow(row: Element): ObservedMarket | undefined {
    const nameEl = row.querySelector(FANDUEL_SELECTORS.playerName);
    const oddsEl = row.querySelector(FANDUEL_SELECTORS.oddsButton);
    if (!nameEl?.textContent?.trim()) return undefined;
    const americanOdds = parseAmericanOddsText(oddsEl?.textContent ?? "");
    if (americanOdds === undefined) return undefined;
    const title = row.closest("[data-testid='market-item']")?.querySelector(FANDUEL_SELECTORS.marketTitle)?.textContent?.trim()
      ?? "";
    return {
      source: "fanduel",
      sport: "football",
      league: "NFL",
      playerName: nameEl.textContent!.trim(),
      marketType: title,
      marketLabel: title,
      selection: "YES",
      americanOdds,
      marketStatus: "UNKNOWN",
      observedAt: this.now().toISOString(),
      adapterVersion: this.adapterVersion,
      detectionConfidence: 0.7,
      provenance: "visible-page",
    };
  }

  observeChanges(callback: (event: MarketChangeEvent) => void): () => void {
    const hooks: DifferHooks = {
      selectCards: (root) => Array.from(root.querySelectorAll(FANDUEL_SELECTORS.marketRow)),
      parseCard: (el) => this.parseRow(el),
    };
    this.unsubscribe = diffMarkets(hooks, callback, { targetSelector: FANDUEL_SELECTORS.marketGroup });
    return () => this.unsubscribe?.();
  }
}
