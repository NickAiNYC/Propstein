/**
 * PropStein — odds mathematics.
 *
 * Pure functions only. No LLM, no randomness. Every number displayed in the
 * product is derived here and is reproducible from stored inputs.
 */

import type { Selection } from './types';

/**
 * Implied probability of an American-odds price.
 *  -115  -> 115/215  = 0.534884...
 *  +150  -> 100/250  = 0.4
 */
export function impliedProbability(americanOdds: number): number {
  if (!Number.isFinite(americanOdds) || americanOdds === 0) {
    throw new RangeError(`invalid American odds: ${americanOdds}`);
  }
  if (Math.abs(americanOdds) < 100 && Math.abs(americanOdds) > 0) {
    // Valid American odds have |odds| >= 100
    throw new RangeError(`invalid American odds: ${americanOdds}`);
  }
  if (americanOdds > 0) {
    return 100 / (americanOdds + 100);
  }
  return -americanOdds / (100 - americanOdds);
}

/**
 * Break-even probability: the true probability at which the recorded price has
 * zero expected value. For a single price this equals the implied probability;
 * it is kept as a distinct name because the product surfaces it as
 * "Break-even probability" (a price property, not a forecast).
 */
export function breakEvenProbability(americanOdds: number): number {
  return impliedProbability(americanOdds);
}

/**
 * Convert a probability back to American odds (rounded to integer).
 */
export function americanFromImplied(p: number): number {
  if (!(p > 0 && p < 1)) throw new RangeError(`probability out of range: ${p}`);
  if (p >= 0.5) {
    return -Math.round((100 * p) / (1 - p));
  }
  return Math.round((100 * (1 - p)) / p);
}

export interface DevigResult {
  over: number;
  under: number;
  /** Total raw implied probability (overround minus 1 = vig). */
  overround: number;
}

/**
 * Proportional de-vig of a two-way quote. The two raw implied probabilities
 * are renormalized to sum to 1. This is the only de-vig used for CLV
 * (preregistered choice; applied identically at entry and at close).
 */
export function devigTwoWay(overOdds: number, underOdds: number): DevigResult {
  const rawOver = impliedProbability(overOdds);
  const rawUnder = impliedProbability(underOdds);
  const s = rawOver + rawUnder;
  if (s <= 0) throw new RangeError('degenerate two-way quote');
  return { over: rawOver / s, under: rawUnder / s, overround: s };
}

/** De-vigged fair probability for a named side. */
export function fairProbabilityForSide(
  overOdds: number,
  underOdds: number,
  side: Selection,
): number {
  const d = devigTwoWay(overOdds, underOdds);
  return side === 'over' ? d.over : d.under;
}

/**
 * Price delta in percentage points between the entered break-even probability
 * and a comparison implied probability.
 *
 * Sign convention (preregistered):
 *   delta = enteredBreakEven - comparisonImplied
 *   delta < 0  -> entered price requires LESS probability than the comparison
 *                 ("Entered price is X pp better than comparison")
 *   delta > 0  -> entered price requires MORE probability
 *                 ("Entered price is X pp worse than comparison")
 *
 * This is a market comparison. It is never described as an advantage claim,
 * and the sign is never labelled with actionable language.
 */
export function priceDeltaPp(enteredAmericanOdds: number, comparisonAmericanOdds: number): number {
  return (breakEvenProbability(enteredAmericanOdds) - impliedProbability(comparisonAmericanOdds)) * 100;
}

/** Format a probability as a percentage with one decimal (display only). */
export function pct(p: number | null, digits = 1): string {
  if (p === null || !Number.isFinite(p)) return '—';
  return `${(p * 100).toFixed(digits)}%`;
}

/** Format an American-odds integer with its sign. */
export function fmtAmerican(odds: number | null | undefined): string {
  if (odds === null || odds === undefined || !Number.isFinite(odds)) return '—';
  return odds > 0 ? `+${Math.round(odds)}` : `${Math.round(odds)}`;
}

/** Odds band for record slicing (preregistered bands). */
export function oddsBand(americanOdds: number): 'short' | 'near_even' | 'long' {
  const p = impliedProbability(americanOdds);
  if (p >= 0.6) return 'short';
  if (p > 0.4) return 'near_even';
  return 'long';
}

export const ODDS_BAND_LABELS: Record<'short' | 'near_even' | 'long', string> = {
  short: 'Implied ≥ 60%',
  near_even: 'Implied 40–60%',
  long: 'Implied ≤ 40%',
};
