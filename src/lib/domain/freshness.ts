/**
 * PropStein — snapshot freshness rules.
 *
 * Preregistered thresholds. Every comparison displays its snapshot time and
 * age; anything past threshold is STALE QUOTE, never silently used.
 */

export interface FreshnessThresholds {
  /** Pregame market comparison staleness threshold (seconds). */
  marketComparisonSeconds: number;
  /** Closing reference must be captured within this window of the pricing cutoff (seconds). */
  closingWindowSeconds: number;
  /** Two independent closing sources may differ by at most this (fair probability points). */
  closingSourceTolerancePp: number;
}

export const FRESHNESS_THRESHOLDS: FreshnessThresholds = {
  marketComparisonSeconds: 300,
  closingWindowSeconds: 900,
  closingSourceTolerancePp: 1.5,
};

export function ageSeconds(capturedAtUtc: string | null | undefined, nowUtc: string): number | null {
  if (!capturedAtUtc) return null;
  const t = Date.parse(capturedAtUtc);
  const now = Date.parse(nowUtc);
  if (!Number.isFinite(t) || !Number.isFinite(now)) return null;
  return Math.max(0, Math.round((now - t) / 1000));
}

export function freshnessState(
  capturedAtUtc: string | null | undefined,
  nowUtc: string,
  thresholdSeconds: number = FRESHNESS_THRESHOLDS.marketComparisonSeconds,
): { ageSeconds: number | null; thresholdSeconds: number; state: 'fresh' | 'stale' | 'unknown' } {
  const age = ageSeconds(capturedAtUtc, nowUtc);
  if (age === null) return { ageSeconds: null, thresholdSeconds, state: 'unknown' };
  return {
    ageSeconds: age,
    thresholdSeconds,
    state: age > thresholdSeconds ? 'stale' : 'fresh',
  };
}

/** Human-readable age, e.g. "22 seconds", "9 minutes". */
export function fmtAge(seconds: number | null): string {
  if (seconds === null) return 'unknown';
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'}`;
  const h = Math.floor(m / 60);
  return `${h} hour${h === 1 ? '' : 's'}`;
}
