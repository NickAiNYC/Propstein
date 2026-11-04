/**
 * PropStein — Luck Meter verdict ladder and statistics tests.
 */

import { describe, expect, it } from 'vitest';
import { buildLuckMeterReport, clusterBootstrapMean, shrunkMean, calibrationTable, SHRINKAGE_K, MIN_SAMPLE } from '../../src/lib/domain/stats';
import type { ClvOutcome } from '../../src/lib/domain/types';

function outcome(overrides: Partial<ClvOutcome> = {}): ClvOutcome {
  return {
    ledgerId: `l-${Math.random().toString(36).slice(2, 8)}`,
    sport: 'NFL',
    gameClusterId: 'NFL:g1',
    market: 'player_reception_yds',
    modelVersion: 'REC-V4',
    entrySource: 'manual_entry',
    oddsBand: 'near_even',
    clvPp: 0.5,
    evaluable: true,
    reasonCode: null,
    beatClose: true,
    modelProbability: 0.55,
    modelCalibrated: true,
    result: 'win',
    ...overrides,
  };
}

function many(n: number, fn: (i: number) => Partial<ClvOutcome>): ClvOutcome[] {
  return Array.from({ length: n }, (_, i) => outcome({ ...fn(i), gameClusterId: `NFL:g${i % Math.ceil(n / 25)}` }));
}

describe('luck meter verdict ladder', () => {
  it('NO RECORD when there are no entries at all', () => {
    const r = buildLuckMeterReport({ outcomes: [] });
    expect(r.verdict).toBe('NO RECORD');
    expect(r.verdictDisplayRule).toBe('No graded entries yet.');
  });

  it('INSUFFICIENT SAMPLE below the minimum', () => {
    const r = buildLuckMeterReport({ outcomes: many(MIN_SAMPLE - 1, () => ({ clvPp: 3 })) });
    expect(r.verdict).toBe('INSUFFICIENT SAMPLE');
    expect(r.verdictDisplayRule).toBe('Not enough evaluable entries to draw a conclusion.');
  });

  it('INCONCLUSIVE when the interval includes zero', () => {
    // Alternating +2.4 / −1.6: mean +0.4, sd 2.0 over 40 — CI straddles zero.
    const r = buildLuckMeterReport({
      outcomes: many(40, (i) => ({ clvPp: i % 2 === 0 ? 2.4 : -1.6 })),
    });
    expect(r.evaluableCount).toBe(40);
    expect(r.confidenceIntervalPp?.lower).toBeLessThan(0);
    expect(r.confidenceIntervalPp?.upper).toBeGreaterThan(0);
    expect(r.verdict).toBe('INCONCLUSIVE');
    expect(r.verdictDisplayRule).toContain('includes zero');
  });

  it('POSITIVE BUT UNPROVEN when interval excludes zero on the positive side without a gate PASS', () => {
    // mean +2 with tiny variance: lower bound above zero.
    const r = buildLuckMeterReport({
      outcomes: many(40, (i) => ({ clvPp: Number((0.1 * Math.sin(i) + 2).toFixed(3)) })),
    });
    expect(r.confidenceIntervalPp?.lower).toBeGreaterThan(0);
    expect(r.verdict).toBe('POSITIVE BUT UNPROVEN');
    expect(r.verdictDisplayRule).toContain('preregistered confirmation gate has not passed');
  });

  it('GATE PASSED requires both a recorded gate PASS and compliance approval', () => {
    const outcomes = many(40, (i) => ({ clvPp: Number((0.1 * Math.sin(i) + 2).toFixed(3)) }));
    const withGate = buildLuckMeterReport({ outcomes, gatePassed: true, complianceApproved: false });
    expect(withGate.verdict).not.toBe('GATE PASSED');
    const withBoth = buildLuckMeterReport({ outcomes, gatePassed: true, complianceApproved: true });
    expect(withBoth.verdict).toBe('GATE PASSED');
  });

  it('DESCRIPTIVE ONLY when the record is negative', () => {
    const r = buildLuckMeterReport({
      outcomes: many(40, (i) => ({ clvPp: Number((0.1 * Math.sin(i) - 2).toFixed(3)) })),
    });
    expect(r.verdict).toBe('DESCRIPTIVE ONLY');
  });
});

describe('exclusion reporting honesty', () => {
  it('excluded records never count as losses or zeros: mean is computed over evaluable only', () => {
    const evaluable = many(10, () => ({ clvPp: 1.0 }));
    const excluded = [
      outcome({ clvPp: null, evaluable: false, reasonCode: 'PUSH' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'VOID' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'DNP' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'CANCELED' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'MISSING_CLOSE' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'STALE_CLOSE' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'CONFLICTING_CLOSE' }),
      outcome({ clvPp: null, evaluable: false, reasonCode: 'DUPLICATE' }),
    ];
    const r = buildLuckMeterReport({ outcomes: [...evaluable, ...excluded] });
    expect(r.evaluableCount).toBe(10);
    expect(r.excludedCount).toBe(8);
    expect(r.meanClvPp).toBeCloseTo(1.0, 5); // not diluted toward zero by exclusions
    const reasons = r.exclusions.map((e) => e.reason);
    for (const code of ['PUSH', 'VOID', 'DNP', 'CANCELED', 'MISSING_CLOSE', 'STALE_CLOSE', 'CONFLICTING_CLOSE', 'DUPLICATE']) {
      expect(reasons).toContain(code);
    }
  });

  it('slices flag below-minimum groups', () => {
    const r = buildLuckMeterReport({
      outcomes: [
        ...many(35, () => ({ clvPp: 0.5, sport: 'NFL' })),
        ...many(4, () => ({ clvPp: -1, sport: 'NBA' })),
      ],
    });
    const nba = r.slices.find((s) => s.dimension === 'Sport' && s.value === 'NBA');
    expect(nba?.belowMinSample).toBe(true);
    const nfl = r.slices.find((s) => s.dimension === 'Sport' && s.value === 'NFL');
    expect(nfl?.belowMinSample).toBe(false);
  });
});

describe('statistics', () => {
  it('shrinkage pulls the estimate toward zero by N/(N+K)', () => {
    expect(shrunkMean([2, 2, 2], 100)).toBeCloseTo((3 / 103) * 2, 9);
    expect(SHRINKAGE_K).toBe(100);
    // large N: shrinkage ~ identity
    const big = Array.from({ length: 100000 }, () => 1);
    expect(shrunkMean(big)).toBeCloseTo(1, 2);
  });

  it('bootstrap is deterministic for a fixed seed and reflects clustering', () => {
    const vals = Array.from({ length: 50 }, (_, i) => (i % 2 === 0 ? 1.5 : -0.5));
    const clusters = vals.map((_, i) => `g${Math.floor(i / 5)}`);
    const a = clusterBootstrapMean(vals, clusters, { seed: 20261024, replicates: 2000 });
    const b = clusterBootstrapMean(vals, clusters, { seed: 20261024, replicates: 2000 });
    expect(a.lowerBoundOneSided0125).toBe(b.lowerBoundOneSided0125);
    expect(a.ci95).toEqual(b.ci95);
  });

  it('calibration table: perfect predictor has Brier 0 and observed == predicted', () => {
    const probs = [1, 1, 1, 1, 0, 0, 0, 0];
    const outcomes = [1, 1, 1, 1, 0, 0, 0, 0];
    const t = calibrationTable(probs, outcomes);
    expect(t.brierScore).toBe(0);
    for (const row of t.deciles) {
      expect(row.observed).toBeCloseTo(row.predicted, 4);
    }
  });

  it('calibration table: always-wrong predictor has Brier 1', () => {
    const t = calibrationTable([1, 1], [0, 0]);
    expect(t.brierScore).toBe(1);
  });
});
