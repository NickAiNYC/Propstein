/**
 * PropStein Live Sniper — Freshness Engine
 * =======================================
 * Quote-age accounting and per-market staleness rules.
 *
 * Invariants (spec §8):
 *  - The time a quote was SEEN on screen (observedAt) is never equated with
 *    the time the sportsbook GENERATED it (sourceTimestamp).
 *  - Missing or invalid source timestamps fail closed. A recent DOM read
 *    cannot establish when the book published the price.
 *  - Freshness limits are market-type-specific and configurable.
 *  - The defaults below are ENGINEERING DEFAULTS aligned with the repo's
 *    StaleKillSwitch (odds: 20s live / 60s pregame). They are NOT empirical
 *    latency measurements and are labeled as such. Live micro-markets get
 *    tighter limits; nothing claims a universal one-second quote lifetime.
 */

import type { FreshnessRules, MarketTypeCode, ObservedMarket } from "./market-types.ts";

export const DEFAULT_FRESHNESS_RULES: FreshnessRules = {
  maxQuoteAgeMs: 60_000,
  maxSourceAgeMs: 60_000,
};

/**
 * Per-market-type engineering defaults. Live micro-markets (drive / next
 * play) carry far tighter quote lifetimes than pregame full-game markets.
 * Every value is overridable via SignalEngineConfig.
 */
export const MARKET_FRESHNESS_DEFAULTS: Readonly<Record<string, FreshnessRules>> = {
  drive_reception_1plus: { maxQuoteAgeMs: 3_000, maxSourceAgeMs: 20_000 },
  next_play_reception_1plus: { maxQuoteAgeMs: 1_500, maxSourceAgeMs: 10_000 },
  game_reception_over: { maxQuoteAgeMs: 20_000, maxSourceAgeMs: 60_000 },
  game_reception_under: { maxQuoteAgeMs: 20_000, maxSourceAgeMs: 60_000 },
  game_receiving_yards_over: { maxQuoteAgeMs: 20_000, maxSourceAgeMs: 60_000 },
  game_receiving_yards_under: { maxQuoteAgeMs: 20_000, maxSourceAgeMs: 60_000 },
  game_anytime_td: { maxQuoteAgeMs: 20_000, maxSourceAgeMs: 60_000 },
};

export interface FreshnessAssessment {
  quoteAgeMs: number;
  quoteLimitMs: number;
  isStale: boolean;
  sourceAgeMs?: number;
  sourceLimitMs?: number;
  sourceDataStale: boolean;
  reasons: string[];
}

function parseIsoMs(iso: string | undefined): number | undefined {
  if (!iso) return undefined;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : undefined;
}

export function quoteAgeMs(observedAt: string | undefined, nowMs: number): number {
  const t = parseIsoMs(observedAt);
  if (t === undefined) return Number.POSITIVE_INFINITY;
  if (t > nowMs) return Number.POSITIVE_INFINITY;
  return Math.max(0, nowMs - t);
}

/**
 * Assess one observed market's freshness.
 * `nowMs` is injectable for deterministic tests.
 */
export function assessFreshness(
  market: ObservedMarket,
  marketTypeCode: MarketTypeCode | undefined,
  rules: { freshness: Partial<Record<string, FreshnessRules>>; defaultFreshness: FreshnessRules },
  nowMs: number,
): FreshnessAssessment {
  const specific = marketTypeCode ? rules.freshness[marketTypeCode] : undefined;
  const effective = specific ?? MARKET_FRESHNESS_DEFAULTS[marketTypeCode ?? ""] ?? rules.defaultFreshness;
  const age = quoteAgeMs(market.observedAt, nowMs);
  const reasons: string[] = [];

  const isStale = age > effective.maxQuoteAgeMs;
  if (!Number.isFinite(age)) reasons.push("observedAt missing or unparseable");
  if (isStale) reasons.push(`quote age ${Math.round(age)}ms exceeds ${effective.maxQuoteAgeMs}ms limit for ${marketTypeCode ?? "default"}`);

  // Source-data freshness — evaluated SEPARATELY from quote age.
  let sourceAgeMs: number | undefined;
  let sourceDataStale = false;
  const sourceTs = parseIsoMs(market.sourceTimestamp);
  if (sourceTs === undefined) {
    sourceDataStale = true;
    reasons.push("source timestamp missing or unparseable — sportsbook quote freshness cannot be verified");
  } else if (sourceTs > nowMs) {
    sourceDataStale = true;
    reasons.push("source timestamp is in the future — sportsbook quote freshness cannot be verified");
  } else {
    sourceAgeMs = Math.max(0, nowMs - sourceTs);
    if (effective.maxSourceAgeMs !== undefined && sourceAgeMs > effective.maxSourceAgeMs) {
      sourceDataStale = true;
      reasons.push(`source data age ${Math.round(sourceAgeMs)}ms exceeds ${effective.maxSourceAgeMs}ms — the book generated this quote before the current game state`);
    }
  }

  return {
    quoteAgeMs: age,
    quoteLimitMs: effective.maxQuoteAgeMs,
    isStale,
    sourceAgeMs,
    sourceLimitMs: effective.maxSourceAgeMs,
    sourceDataStale,
    reasons,
  };
}

/** Human-readable quote-age label for the UI. */
export function formatQuoteAge(ageMs: number): string {
  if (!Number.isFinite(ageMs)) return "UNKNOWN";
  if (ageMs < 1_000) return `${Math.round(ageMs)}ms`;
  if (ageMs < 60_000) return `${(ageMs / 1000).toFixed(1)}s`;
  return `${Math.floor(ageMs / 60_000)}m ${Math.round((ageMs % 60_000) / 1000)}s`;
}
