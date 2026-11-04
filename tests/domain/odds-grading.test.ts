/**
 * PropStein — unit tests: odds, de-vig, CLV, staleness, grading.
 *
 * Spec test obligations covered here:
 *   1. Push, void, DNP, cancellation excluded with reason codes.
 *   2. Missing or stale closing prices become unevaluable, not zero.
 *   4. Source disagreement beyond tolerance becomes unevaluable.
 */

import { describe, expect, it } from 'vitest';
import {
  americanFromImplied,
  breakEvenProbability,
  devigTwoWay,
  fairProbabilityForSide,
  impliedProbability,
  oddsBand,
  priceDeltaPp,
} from '../../src/lib/domain/odds';
import { freshnessState, ageSeconds, FRESHNESS_THRESHOLDS } from '../../src/lib/domain/freshness';
import { gradeEntry, priceClvPp, closingQualityFromSources, applyCorrelationPolicy } from '../../src/lib/domain/grading';
import { closingReference } from '../../src/lib/domain/sim-market';
import type { LedgerEntryRecord } from '../../src/lib/domain/ledger';

function entryFixture(overrides: Partial<LedgerEntryRecord> = {}): LedgerEntryRecord {
  return {
    ledgerId: 'test-1',
    userId: 'u1',
    sourceType: 'manual_entry',
    sport: 'NFL',
    league: 'NFL',
    eventId: 'e1',
    gameClusterId: 'NFL:e1',
    playerId: 'p1',
    playerName: 'WR X',
    market: 'player_reception_yds',
    selection: 'over',
    line: 52.5,
    enteredAmericanOdds: -115,
    enteredCounterpartOdds: -105,
    enteredImpliedProbability: 0.5349,
    breakEvenProbability: 0.5349,
    book: 'user_entered',
    capturedAtUtc: '2026-11-08T18:04:22Z',
    snapshotHash: 'abc',
    modelVersion: 'REC-V4',
    modelCoverage: 'calibrated',
    modelProbability: 0.561,
    modelUncertaintyLower: 0.531,
    modelUncertaintyUpper: 0.590,
    priceAssessment: 'PRICE AT MARKET HURDLE',
    provenanceJson: '{}',
    createdAtUtc: '2026-11-08T18:06:00Z',
    entryHash: 'hash1',
    duplicateOfLedgerId: null,
    correlationGroup: null,
    correlationReason: null,
    ...overrides,
  };
}

const FRESH_CLOSE = { quality: 'fresh' as const, fairProbability: 0.55, independenceVerified: true, provider: 'P' };
const SETTLED_WIN = { status: 'settled' as const, result: 'win' as const };

describe('odds mathematics', () => {
  it('-115 implies 53.49% (spec example)', () => {
    expect(impliedProbability(-115)).toBeCloseTo(0.534884, 6);
  });
  it('+150 implies 40%', () => {
    expect(impliedProbability(150)).toBeCloseTo(0.4, 6);
  });
  it('-100 implies 50%', () => {
    expect(impliedProbability(-100)).toBeCloseTo(0.5, 6);
  });
  it('break-even probability equals implied probability', () => {
    expect(breakEvenProbability(-115)).toBe(impliedProbability(-115));
    expect(breakEvenProbability(180)).toBe(impliedProbability(180));
  });
  it('rejects invalid American odds', () => {
    expect(() => impliedProbability(0)).toThrow();
    expect(() => impliedProbability(-50)).toThrow();
    expect(() => impliedProbability(NaN)).toThrow();
  });
  it('americanFromImplied round-trips', () => {
    for (const odds of [-115, -105, -110, -300, +150, +400]) {
      expect(americanFromImplied(impliedProbability(odds))).toBe(odds);
    }
  });
  it('proportional de-vig: fair probabilities sum to 1', () => {
    for (const [o, u] of [[-115, -105], [-110, -110], [-120, +100]] as const) {
      const d = devigTwoWay(o, u);
      expect(d.over + d.under).toBeCloseTo(1, 9);
      expect(d.overround).toBeGreaterThan(1);
    }
  });
  it('symmetric quote de-vigs to 50/50', () => {
    expect(devigTwoWay(-110, -110).over).toBeCloseTo(0.5, 9);
  });
  it('fair probability selects the requested side', () => {
    expect(fairProbabilityForSide(-115, -105, 'over')).toBeCloseTo(devigTwoWay(-115, -105).over, 9);
    expect(fairProbabilityForSide(-115, -105, 'under')).toBeCloseTo(devigTwoWay(-115, -105).under, 9);
  });
  it('price delta matches the specification example: -115 vs -112 is 0.7 pp worse', () => {
    expect(priceDeltaPp(-115, -112)).toBeCloseTo(0.7, 1);
  });
  it('price delta sign: better price is negative (less probability required)', () => {
    expect(priceDeltaPp(-105, -115)).toBeLessThan(0);
    expect(priceDeltaPp(-125, -110)).toBeGreaterThan(0);
  });
  it('odds bands are preregistered', () => {
    expect(oddsBand(-200)).toBe('short');
    expect(oddsBand(-110)).toBe('near_even');
    expect(oddsBand(+250)).toBe('long');
  });
});

describe('staleness', () => {
  const now = '2026-11-08T19:00:00Z';
  it('fresh under threshold', () => {
    const f = freshnessState('2026-11-08T18:59:40Z', now);
    expect(f.state).toBe('fresh');
    expect(f.ageSeconds).toBe(20);
  });
  it('stale over the 300-second preregistered threshold', () => {
    const f = freshnessState('2026-11-08T18:54:00Z', now);
    expect(f.state).toBe('stale');
  });
  it('missing timestamp is unknown, not fresh', () => {
    expect(freshnessState(null, now).state).toBe('unknown');
    expect(freshnessState('garbage', now).state).toBe('unknown');
  });
  it('age never negative', () => {
    expect(ageSeconds('2026-11-08T20:00:00Z', now)).toBe(0);
  });
});

describe('CLV', () => {
  it('entry Over -105 / close Over -115 gives positive CLV ~ +2.2 pp (beat close)', () => {
    // Entering at -105 and closing at -115: the close requires more
    // probability than the entry did, so the recorded price was superior.
    const entryFair = fairProbabilityForSide(-105, -115, 'over');
    const closeFair = fairProbabilityForSide(-115, -105, 'over');
    const r = priceClvPp(entryFixture({ enteredAmericanOdds: -105, enteredCounterpartOdds: -115 }), {
      quality: 'fresh',
      fairProbability: closeFair,
      independenceVerified: true,
      provider: null,
    });
    expect(r.reason).toBeNull();
    expect(r.clvPp).toBeCloseTo((closeFair - entryFair) * 100, 3);
    expect(r.clvPp).toBeGreaterThan(0);
    expect(r.clvPp).toBeGreaterThan(2.0);
    expect(r.clvPp).toBeLessThan(2.5);
  });
  it('worse-than-close entry gives negative CLV', () => {
    const entryFair = fairProbabilityForSide(-125, +105, 'over');
    const closeFair = fairProbabilityForSide(-110, -110, 'over');
    const r = priceClvPp(entryFixture({ enteredAmericanOdds: -125, enteredCounterpartOdds: 105 }), {
      quality: 'fresh',
      fairProbability: closeFair,
      independenceVerified: true,
      provider: null,
    });
    expect(r.clvPp).toBeLessThan(0);
  });
});

describe('grading: exclusions with reason codes (spec tests 1, 2, 4)', () => {
  it('test 1: push is excluded with PUSH reason code', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, { status: 'push', result: 'push' });
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('PUSH');
    expect(g.clvPp).toBeNull();
    expect(g.beatClose).toBeNull();
  });
  it('test 1: void is excluded with VOID reason code', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, { status: 'void', result: 'void' });
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('VOID');
  });
  it('test 1: cancellation is excluded with CANCELED reason code', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, { status: 'canceled', result: null });
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('CANCELED');
  });
  it('test 1: DNP is excluded with DNP reason code', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, { status: 'dnp', result: null });
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('DNP');
  });
  it('test 2: missing close becomes unevaluable with MISSING_CLOSE, never zero', () => {
    const g = gradeEntry(entryFixture(), null, SETTLED_WIN);
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('MISSING_CLOSE');
    expect(g.clvPp).toBeNull(); // never 0
  });
  it('test 2: stale close becomes unevaluable with STALE_CLOSE, never zero', () => {
    const g = gradeEntry(entryFixture(), { ...FRESH_CLOSE, quality: 'stale' }, SETTLED_WIN);
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('STALE_CLOSE');
    expect(g.clvPp).toBeNull();
  });
  it('test 2: unsettled entries are unevaluable with UNSETTLED', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, { status: 'pending', result: null });
    expect(g.reasonCode).toBe('UNSETTLED');
  });
  it('test 4: source disagreement beyond tolerance becomes CONFLICTING_CLOSE', () => {
    const tol = FRESHNESS_THRESHOLDS.closingSourceTolerancePp;
    expect(closingQualityFromSources(0.55, 0.55 + (tol - 0.2) / 100, tol)).toBe('fresh');
    expect(closingQualityFromSources(0.55, 0.55 + (tol + 0.2) / 100, tol)).toBe('conflicting');
    const g = gradeEntry(entryFixture(), { ...FRESH_CLOSE, quality: 'conflicting' }, SETTLED_WIN);
    expect(g.evaluable).toBe(false);
    expect(g.reasonCode).toBe('CONFLICTING_CLOSE');
    expect(g.clvPp).toBeNull();
  });
  it('non-independent close becomes unevaluable with NOT_INDEPENDENT_CLOSE', () => {
    const g = gradeEntry(entryFixture(), { ...FRESH_CLOSE, independenceVerified: false }, SETTLED_WIN);
    expect(g.reasonCode).toBe('NOT_INDEPENDENT_CLOSE');
  });
  it('duplicate flag excludes with DUPLICATE', () => {
    const g = gradeEntry(entryFixture(), FRESH_CLOSE, SETTLED_WIN, { duplicate: true, correlatedExcluded: false });
    expect(g.reasonCode).toBe('DUPLICATE');
  });
  it('evaluable grades compute beatClose from CLV sign', () => {
    const entryFair = fairProbabilityForSide(-115, -105, 'over');
    const g = gradeEntry(entryFixture(), { ...FRESH_CLOSE, fairProbability: entryFair + 0.02 }, SETTLED_WIN);
    expect(g.evaluable).toBe(true);
    expect(g.beatClose).toBe(true);
  });
  it('simulated conflicting_close fixture produces conflicting quality end-to-end', () => {
    const close = closingReference({
      sport: 'NFL', eventId: 'e1', playerId: 'p1', market: 'player_reception_yds', line: 52.5,
      selection: 'over', entryOverOdds: -115, entryUnderOdds: -105,
      capturedAtUtc: '2026-11-08T18:04:22Z', nowUtc: '2026-11-08T23:30:00Z', scenario: 'conflicting_close',
    });
    expect(close.quality).toBe('conflicting');
    expect(close.secondSource).not.toBeNull();
  });
  it('simulated fresh close fixture stays fresh with agreeing second source', () => {
    const close = closingReference({
      sport: 'NFL', eventId: 'e1', playerId: 'p1', market: 'player_reception_yds', line: 52.5,
      selection: 'over', entryOverOdds: -115, entryUnderOdds: -105,
      capturedAtUtc: '2026-11-08T18:04:22Z', nowUtc: '2026-11-08T23:30:00Z', scenario: 'none',
    });
    expect(close.quality).toBe('fresh');
    expect(close.independenceVerified).toBe(true);
  });
});

describe('correlation policy (spec test 3, dedup half)', () => {
  it('keeps the earliest signal per correlation group and flags the rest', () => {
    const rows = [
      { ledgerId: 'a', correlationGroup: 'corr:g1:p1', recordedAtUtc: '2026-11-01T10:00:00Z' },
      { ledgerId: 'b', correlationGroup: 'corr:g1:p1', recordedAtUtc: '2026-11-01T11:00:00Z' },
      { ledgerId: 'c', correlationGroup: null, recordedAtUtc: '2026-11-01T09:00:00Z' },
    ];
    const decisions = applyCorrelationPolicy(rows);
    expect(decisions.get('a')).toBe('retain');
    expect(decisions.get('b')).toBe('correlated');
    expect(decisions.get('c')).toBe('retain');
  });
  it('independent groups do not interfere', () => {
    const rows = [
      { ledgerId: 'a', correlationGroup: 'corr:g1:p1', recordedAtUtc: '2026-11-01T10:00:00Z' },
      { ledgerId: 'b', correlationGroup: 'corr:g1:p2', recordedAtUtc: '2026-11-01T11:00:00Z' },
    ];
    const decisions = applyCorrelationPolicy(rows);
    expect(decisions.get('a')).toBe('retain');
    expect(decisions.get('b')).toBe('retain');
  });
});
