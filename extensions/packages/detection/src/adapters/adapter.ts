/**
 * PropStein Live Sniper — Site Adapters
 * ===================================
 * The common adapter interface (spec §4.2) plus the registry with
 * feature-flag gating. Every adapter fails SAFE: unrecognized structure
 * yields zero markets and a degraded status — never invented matches.
 */

import type { ObservedMarket, BookSource } from "@propstein/core";

export interface AdapterDetectionResult {
  markets: ObservedMarket[];
  /** Healthy adapters report "OK". */
  status: "OK" | "ADAPTER_DEGRADED" | "PAGE_UNSUPPORTED";
  /** 0..1 confidence in the IDENTITY of parsed markets. */
  confidence: number;
  notes: string[];
}

export interface VisibleMarketAdapter {
  platform: BookSource;
  /** Version of the selector set — bumped when layouts change. */
  adapterVersion: string;
  isSupportedPage(url: URL): boolean;
  detectVisibleMarkets(root: Document): Promise<AdapterDetectionResult>;
  /**
   * Subscribe to market changes. Returns an unsubscribe function.
   * Implementations typically delegate to a shared DomMarketExtractor with
   * adapter-specific selector scoping.
   */
  observeChanges(callback: (event: import("@propstein/core").MarketChangeEvent) => void): () => void;
}

export interface AdapterFeatureFlags {
  /** Real sportsbook adapters ship DISABLED pending authorization. */
  draftkings: boolean;
  fanduel: boolean;
  polymarket: boolean;
  /** The synthetic demo adapter is the default-enabled test surface. */
  demobook: boolean;
}

export const DEFAULT_FEATURE_FLAGS: AdapterFeatureFlags = {
  draftkings: false,
  fanduel: false,
  polymarket: false,
  demobook: true,
};

export class AdapterRegistry {
  private readonly adapters = new Map<string, VisibleMarketAdapter>();
  private readonly flags: AdapterFeatureFlags;

  constructor(flags: Partial<AdapterFeatureFlags> = {}) {
    this.flags = { ...DEFAULT_FEATURE_FLAGS, ...flags };
  }

  register(adapter: VisibleMarketAdapter): void {
    this.adapters.set(adapter.platform, adapter);
  }

  isAdapterEnabled(platform: string): boolean {
    return (this.flags as unknown as Record<string, boolean | undefined>)[platform] === true;
  }

  /** Resolve the adapter for a URL, honoring feature flags. */
  resolve(url: URL): { adapter?: VisibleMarketAdapter; reason: string } {
    for (const adapter of this.adapters.values()) {
      if (adapter.isSupportedPage(url)) {
        if (!this.isAdapterEnabled(adapter.platform)) {
          return {
            reason: `${adapter.platform} detection is disabled by feature flag pending authorization — the companion runs in research-only mode on this site`,
          };
        }
        return { adapter, reason: "ok" };
      }
    }
    return { reason: "no adapter supports this page" };
  }

  list(): VisibleMarketAdapter[] {
    return [...this.adapters.values()];
  }
}

/**
 * Fail-safe wrapper for adapter parsing. Any throw degrades to an empty
 * result — the pipeline NEVER surfaces invented markets.
 */
export async function safeDetect(
  adapter: VisibleMarketAdapter,
  root: Document,
): Promise<AdapterDetectionResult> {
  try {
    const result = await adapter.detectVisibleMarkets(root);
    // Post-condition hardening: markets without a parseable identity or
    // odds are still allowed (they show as unpriced) but must carry a
    // source and observation time.
    const markets = result.markets.filter((m) => m.source === adapter.platform && Boolean(m.observedAt));
    return { ...result, markets };
  } catch (err) {
    return {
      markets: [],
      status: "ADAPTER_DEGRADED",
      confidence: 0,
      notes: [
        `adapter ${adapter.platform}@${adapter.adapterVersion} threw during detection: ${String(err)}`,
        "site layout may have changed — no markets will be reported until the adapter is updated",
      ],
    };
  }
}
