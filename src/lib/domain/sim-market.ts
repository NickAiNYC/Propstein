/**
 * PropStein — demo data plane (simulated providers).
 *
 * All providers here are DETERMINISTIC functions of (event key, seed
 * namespace). They stand in for licensed feeds in the reference deployment
 * and are labelled as simulated data everywhere they surface. The production
 * deployment replaces them with licensed feeds behind the same interfaces.
 *
 * Independence rule (preregistered): the closing-reference provider namespace
 * is disjoint from the model input feed namespace, so closing references are
 * independent of model inputs by construction.
 */

import { gauss, mulberry32, seedFrom } from './determinism';
import { fairProbabilityForSide, impliedProbability } from './odds';
import { closingQualityFromSources } from './grading';
import { FRESHNESS_THRESHOLDS } from './freshness';
import { MODEL_FEED_PROVIDER } from './model-registry';
import type { ComparisonQuote, Selection } from './types';

export const COMPARISON_PROVIDER = 'DEMO-CMP-A (simulated)';
export const CLOSING_PROVIDER = 'DEMO-CLOSE-1 (simulated)';
export const CLOSING_PROVIDER_2 = 'DEMO-CLOSE-2 (simulated)';
export const SETTLEMENT_PROVIDER = 'DEMO-SETTLE-1 (simulated)';

/** Sports for which the demo comparison feed is "licensed". */
export const LICENSED_COMPARISON_SPORTS = new Set(['NFL', 'NBA']);

export interface ComparisonRequest {
  sport: string;
  league: string;
  eventId: string;
  playerId: string;
  market: string;
  line: number;
  enteredAmericanOdds: number;
  capturedAtUtc: string;
  /** Demo scenario injection (fail-closed demonstrations). */
  scenario?: 'none' | 'no_market_data' | 'entitlement_failure';
}

/**
 * Deterministic comparison two-way quote. The quote is seeded from the event
 * key alone (not from the entered odds), so it behaves like an external
 * market: sometimes better, sometimes worse than the entered price.
 */
export function comparisonQuote(req: ComparisonRequest): ComparisonQuote | null {
  if (req.scenario === 'no_market_data' || req.scenario === 'entitlement_failure') {
    return null;
  }
  if (!LICENSED_COMPARISON_SPORTS.has(req.sport)) {
    return null; // unlicensed sport -> INSUFFICIENT MARKET DATA (fail closed)
  }
  const key = seedFrom('CMP', req.sport, req.eventId, req.playerId, req.market, req.line);
  const rand = mulberry32(key);
  // Juice between 4.5% and 6.5% on the two-way market.
  const vig = 0.045 + rand() * 0.02;
  // Market's fair P(over) — uniform 0.35..0.65 with a nudge.
  const pOverFair = 0.35 + rand() * 0.3;
  const rawOver = pOverFair * (1 + vig) / 1;
  const rawUnder = (1 - pOverFair) * (1 + vig);
  return {
    provider: COMPARISON_PROVIDER,
    book: 'DEMO-COMP-BOOK',
    overAmericanOdds: americanFromProb(rawOver),
    underAmericanOdds: americanFromProb(rawUnder),
    capturedAtUtc: req.capturedAtUtc,
    licensed: true,
    rawRef: `cmp:${key.toString(16)}`,
  };
}

export function americanFromProb(p: number): number {
  const clamp = Math.min(0.97, Math.max(0.03, p));
  if (clamp >= 0.5) return -Math.round((100 * clamp) / (1 - clamp));
  return Math.round((100 * (1 - clamp)) / clamp);
}

export interface ClosingRequest {
  sport: string;
  eventId: string;
  playerId: string;
  market: string;
  line: number;
  selection: Selection;
  /** Entry two-way quote (entered book). */
  entryOverOdds: number;
  entryUnderOdds: number;
  capturedAtUtc: string;
  nowUtc: string;
  scenario?: 'none' | 'stale_close' | 'conflicting_close' | 'missing_close';
}

export interface SimulatedClosing {
  provider: string | null;
  capturedAtUtc: string | null;
  overAmericanOdds: number | null;
  underAmericanOdds: number | null;
  impliedProbability: number | null;
  fairProbability: number | null;
  quality: 'fresh' | 'stale' | 'missing' | 'conflicting';
  secondSource: { provider: string; impliedProbability: number } | null;
  independenceVerified: boolean;
}

/**
 * Deterministic closing reference, captured at the pricing cutoff. The close
 * drifts from the entry fair probability by a seeded amount (this is what
 * makes CLV non-trivial in the demo).
 */
export function closingReference(req: ClosingRequest): SimulatedClosing {
  if (req.scenario === 'missing_close') {
    return {
      provider: null,
      capturedAtUtc: null,
      overAmericanOdds: null,
      underAmericanOdds: null,
      impliedProbability: null,
      fairProbability: null,
      quality: 'missing',
      secondSource: null,
      independenceVerified: true,
    };
  }

  const entryFair = fairProbabilityForSide(req.entryOverOdds, req.entryUnderOdds, req.selection);
  const key = seedFrom('CLOSE', req.sport, req.eventId, req.playerId, req.market, req.line, req.selection);
  const rand = mulberry32(key);
  // Seeded drift of the market between entry and close (in probability points).
  const driftPp = gauss(rand) * 2.6 + (rand() - 0.5) * 1.2;
  const closeFairOver =
    req.selection === 'over' ? entryFair + driftPp / 100 : 1 - (1 - entryFair + driftPp / 100);

  const vig = 0.045 + rand() * 0.02;
  const overOdds = americanFromProb(closeFairOver * (1 + vig));
  const underOdds = americanFromProb((1 - closeFairOver) * (1 + vig));

  const cutoff = Date.parse(req.capturedAtUtc) + 45 * 60 * 1000; // close ~45 min after entry snapshot
  const capturedAt = new Date(req.scenario === 'stale_close' ? cutoff + 2 * FRESHNESS_THRESHOLDS.closingWindowSeconds * 1000 : cutoff);

  let quality: SimulatedClosing['quality'] = 'fresh';
  let secondSource: SimulatedClosing['secondSource'] = null;
  const sideImplied = impliedProbability(req.selection === 'over' ? overOdds : underOdds);
  const sideFair = req.selection === 'over' ? closeFairOver : 1 - closeFairOver;

  if (req.scenario === 'conflicting_close') {
    // Second independent source disagrees beyond the preregistered tolerance.
    const p2 = impliedProbability(overOdds) + (FRESHNESS_THRESHOLDS.closingSourceTolerancePp + 0.8) / 100;
    secondSource = { provider: CLOSING_PROVIDER_2, impliedProbability: Number(p2.toFixed(4)) };
  } else {
    // Agreeing second source within tolerance.
    const p2 = impliedProbability(overOdds) + (rand() - 0.5) * 2 * (FRESHNESS_THRESHOLDS.closingSourceTolerancePp - 0.3) / 100;
    secondSource = { provider: CLOSING_PROVIDER_2, impliedProbability: Number(p2.toFixed(4)) };
  }
  quality = closingQualityFromSources(sideImplied, secondSource.impliedProbability, FRESHNESS_THRESHOLDS.closingSourceTolerancePp);

  return {
    provider: CLOSING_PROVIDER,
    capturedAtUtc: capturedAt.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    overAmericanOdds: overOdds,
    underAmericanOdds: underOdds,
    impliedProbability: Number(sideImplied.toFixed(4)),
    fairProbability: Number(sideFair.toFixed(4)),
    quality,
    secondSource,
    independenceVerified: true, // namespace disjoint from MODEL_FEED_PROVIDER
  };
}

export interface SettlementRequest {
  sport: string;
  eventId: string;
  playerId: string;
  market: string;
  line: number;
  selection: Selection;
  /** True win probability for the sim (model or market fair). */
  winProbability: number;
  scenario?: 'none' | 'push' | 'void' | 'canceled' | 'dnp';
}

export interface SimulatedSettlement {
  status: 'settled' | 'void' | 'canceled' | 'push' | 'dnp';
  result: 'win' | 'loss' | 'push' | 'void' | null;
  reasonCode: string | null;
  actualValue: number | null;
}

/** Deterministic settlement. Exclusion scenarios produce explicit statuses. */
export function settle(req: SettlementRequest): SimulatedSettlement {
  if (req.scenario && req.scenario !== 'none') {
    switch (req.scenario) {
      case 'push':
        return { status: 'push', result: 'push', reasonCode: 'PUSH', actualValue: req.line };
      case 'void':
        return { status: 'void', result: 'void', reasonCode: 'VOID', actualValue: null };
      case 'canceled':
        return { status: 'canceled', result: null, reasonCode: 'CANCELED', actualValue: null };
      case 'dnp':
        return { status: 'dnp', result: null, reasonCode: 'DNP', actualValue: null };
    }
  }
  const key = seedFrom('SETTLE', req.sport, req.eventId, req.playerId, req.market, req.line, req.selection);
  const rand = mulberry32(key);
  const noise = (rand() - 0.5) * 24; // yards/points scale
  const win = rand() < req.winProbability;
  const actual = req.selection === 'over' ? req.line + (win ? 6 + noise * 0.4 : -6 + noise * 0.4) : req.line - (win ? 6 - noise * 0.4 : -6 - noise * 0.4);
  // Integer lines with exact landing produce pushes (retained, excluded from CLV).
  if (Number.isInteger(req.line) && Math.abs(actual - req.line) < 0.75) {
    return { status: 'push', result: 'push', reasonCode: 'PUSH', actualValue: req.line };
  }
  return {
    status: 'settled',
    result: win ? 'win' : 'loss',
    reasonCode: null,
    actualValue: Number(actual.toFixed(1)),
  };
}

export interface MarketDriftRequest {
  eventId: string;
  playerId: string;
  market: string;
  line: number;
  enteredAmericanOdds: number;
  elapsedSeconds: number;
}

export interface MarketDrift {
  newAmericanOdds: number;
  suspended: boolean;
  playerStatus: 'Questionable' | 'Out' | 'Available';
}

/** Deterministic market drift for tracked-entry alert evaluation. */
export function marketDrift(req: MarketDriftRequest): MarketDrift {
  const key = seedFrom('DRIFT', req.eventId, req.playerId, req.market, req.line);
  const rand = mulberry32(key);
  const cents = Math.round(gauss(rand) * 30); // drift in odds cents
  const newOdds = req.enteredAmericanOdds + cents * (req.enteredAmericanOdds < 0 ? 1 : -1);
  return {
    newAmericanOdds: newOdds,
    suspended: rand() < 0.05,
    playerStatus: rand() < 0.04 ? 'Out' : rand() < 0.12 ? 'Questionable' : 'Available',
  };
}

/** Provider namespaces, for the independence audit surface. */
export const PROVIDER_NAMESPACES: { provider: string; role: string; independentOf: string[] }[] = [
  { provider: COMPARISON_PROVIDER, role: 'market comparison', independentOf: [MODEL_FEED_PROVIDER] },
  { provider: CLOSING_PROVIDER, role: 'closing reference', independentOf: [MODEL_FEED_PROVIDER] },
  { provider: CLOSING_PROVIDER_2, role: 'closing reference (second source)', independentOf: [MODEL_FEED_PROVIDER, CLOSING_PROVIDER] },
  { provider: SETTLEMENT_PROVIDER, role: 'settlement', independentOf: [MODEL_FEED_PROVIDER] },
];
