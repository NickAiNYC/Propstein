/**
 * PropStein — gate simulation tests.
 *
 * Spec test obligations:
 *   3. Duplicate and correlated signals are deduplicated without destroying
 *      cluster dependence.
 *   6. Model-version changes stratify or invalidate confirmatory sets.
 *   7. Passing and failing gate scenarios produce exact verdicts.
 *   8. Insufficient cluster representation produces an inconclusive verdict.
 *   9. A failed second attempt retires the sport's commercial actionable-signal flag.
 * Plus: cross-sport pooling forbidden; interim look is descriptive only;
 * compliance approval required in addition to a PASS; deterministic seed.
 */

import { describe, expect, it } from 'vitest';
import {
  CrossSportPoolingError,
  evaluateGateAttempt,
  prepareConfirmatorySet,
  sportCommercialState,
} from '../../src/lib/domain/gate';
import { clusterBootstrapMean } from '../../src/lib/domain/stats';
import type { GateSignal } from '../../src/lib/domain/types';

/** Deterministic signal factory. */
function makeSignals(opts: {
  sport: string;
  n: number;
  clusters: number;
  meanPp: number;
  sdPp?: number;
  seed?: number;
  modelVersion?: string | null;
  idPrefix?: string;
  clusterOffset?: number;
}): GateSignal[] {
  // Simple seeded generator (LCG) kept local to the test.
  let state = (opts.seed ?? 42) >>> 0;
  const rand = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const gauss = () => {
    const u = rand() || 1e-9;
    const v = rand() || 1e-9;
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const perCluster = Math.ceil(opts.n / opts.clusters);
  const offset = opts.clusterOffset ?? 0;
  const out: GateSignal[] = [];
  for (let i = 0; i < opts.n; i++) {
    const cluster = `${opts.sport}:G${offset + Math.floor(i / perCluster)}`;
    const player = `P${i % 97}`;
    out.push({
      signalId: `${opts.sport}|${opts.idPrefix ?? ''}${cluster}|${player}|mkt${i % 9}|${(i % 13) * 0.5}#a`,
      sport: opts.sport,
      gameClusterId: cluster,
      playerId: player,
      clvPp: Number((gauss() * (opts.sdPp ?? 2.6) + opts.meanPp).toFixed(3)),
      evaluable: true,
      reasonCode: null,
      modelVersion: opts.modelVersion === undefined ? 'REC-V4' : opts.modelVersion,
      recordedAtUtc: new Date(Date.UTC(2026, 9, 1) + i * 60_000).toISOString(),
    });
  }
  return out;
}

const AT = '2026-11-01T00:00:00Z';

describe('gate: exact verdicts (spec test 7)', () => {
  it('a strong positive set produces exactly PASS', () => {
    // Mean ~ +1.6 pp with sd 2.2 over 600 signals / 60 clusters: threshold and
    // lower bound both clear.
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 1.6, sdPp: 2.2, seed: 7 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.verdict).toBe('PASS');
    expect(r.nEvaluable).toBe(600);
    expect(r.meanClvPp).toBeGreaterThanOrEqual(1.0);
    expect(r.bootstrapLbPp).toBeGreaterThan(0);
    expect(r.seed).toBe(20261024);
    expect(r.replicates).toBe(10000);
  });

  it('a weak positive set (mean below threshold) produces exactly FAIL', () => {
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 0.4, sdPp: 2.6, seed: 7 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.verdict).toBe('FAIL');
  });

  it('a strong-signal but noisy set (lower bound at or below zero) produces FAIL', () => {
    // Mean ~ +3 pp but per-signal sd 35: cluster-level variance keeps the
    // bootstrap lower bound at or below zero.
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 3.0, sdPp: 35, seed: 11 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.meanClvPp).toBeGreaterThanOrEqual(1.0);
    expect(r.bootstrapLbPp).toBeLessThanOrEqual(0);
    expect(r.verdict).toBe('FAIL');
  });

  it('a clearly negative set produces exactly FAIL', () => {
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: -1.5, sdPp: 2.0, seed: 3 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.verdict).toBe('FAIL');
  });

  it('N < 300 is IN_PROGRESS, never a verdict', () => {
    const signals = makeSignals({ sport: 'NFL', n: 250, clusters: 30, meanPp: 2.5, seed: 5 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.verdict).toBe('IN_PROGRESS');
    expect(r.bootstrapLbPp).toBe(0);
  });

  it('interim look at N=300..599 is INTERIM and descriptive only', () => {
    const signals = makeSignals({ sport: 'NFL', n: 450, clusters: 50, meanPp: 3.0, seed: 5 });
    const r = evaluateGateAttempt('NFL', 1, signals, AT);
    expect(r.verdict).toBe('INTERIM');
    expect(r.notes.some((n) => n.includes('descriptive only'))).toBe(true);
  });

  it('attempt numbers beyond the second are a protocol violation', () => {
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 1.5, seed: 9 });
    expect(() => evaluateGateAttempt('NFL', 3, signals, AT)).toThrow(/ATTEMPT_LIMIT/);
  });
});

describe('gate: cross-sport pooling is forbidden', () => {
  it('pooling two sports raises CrossSportPoolingError', () => {
    const nfl = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 1.5, seed: 1 });
    const nba = makeSignals({ sport: 'NBA', n: 10, clusters: 5, meanPp: 2.0, seed: 2 });
    expect(() => evaluateGateAttempt('NFL', 1, [...nfl, ...nba], AT)).toThrow(CrossSportPoolingError);
  });
  it('prepareConfirmatorySet also refuses pooled input', () => {
    const mixed = makeSignals({ sport: 'NBA', n: 5, clusters: 3, meanPp: 1, seed: 4 });
    expect(() => prepareConfirmatorySet('NFL', mixed)).toThrow(CrossSportPoolingError);
  });
});

describe('gate: dedup and correlation (spec test 3)', () => {
  it('exact duplicates are excluded with DUPLICATE, retention of the first', () => {
    const base = makeSignals({ sport: 'NFL', n: 10, clusters: 5, meanPp: 1, seed: 6 });
    const dup: GateSignal = { ...base[0], signalId: `${base[0].signalId.split('#')[0]}#b`, recordedAtUtc: new Date(Date.UTC(2026, 9, 1, 2)).toISOString() };
    const { qualifying, excluded } = prepareConfirmatorySet('NFL', [...base, dup]);
    expect(excluded.some((e) => e.reason === 'DUPLICATE')).toBe(true);
    expect(qualifying.some((s) => s.signalId === dup.signalId)).toBe(false);
    expect(qualifying.some((s) => s.signalId === base[0].signalId)).toBe(true);
  });

  it('correlated siblings (same cluster+player) are excluded with CORRELATED while cluster ids stay intact', () => {
    const base = makeSignals({ sport: 'NFL', n: 10, clusters: 5, meanPp: 1, seed: 6 });
    const s0 = base[0];
    const correlated: GateSignal = {
      ...s0,
      signalId: `${s0.sport}|${s0.gameClusterId}|${s0.playerId}|corr-mkt|0.5#a`,
      clvPp: s0.clvPp + 0.5,
      recordedAtUtc: new Date(Date.UTC(2026, 9, 1, 3)).toISOString(),
    };
    const { qualifying, excluded } = prepareConfirmatorySet('NFL', [...base, correlated]);
    expect(excluded.some((e) => e.reason === 'CORRELATED')).toBe(true);
    // Cluster dependence preserved: the retained original keeps its game cluster.
    const retained = qualifying.find((s) => s.signalId === s0.signalId);
    expect(retained?.gameClusterId).toBe(s0.gameClusterId);
    // And the retained set still contains multiple signals per cluster.
    const clusters = new Map<string, number>();
    for (const q of qualifying) clusters.set(q.gameClusterId, (clusters.get(q.gameClusterId) ?? 0) + 1);
    expect([...clusters.values()].some((c) => c > 1)).toBe(true);
  });

  it('non-evaluable signals are retained as exclusions with their reason codes', () => {
    const base = makeSignals({ sport: 'NFL', n: 10, clusters: 5, meanPp: 1, seed: 6 });
    const pushSig: GateSignal = { ...base[1], evaluable: false, reasonCode: 'PUSH', clvPp: 0 };
    const { excluded } = prepareConfirmatorySet('NFL', [...base, pushSig]);
    expect(excluded.some((e) => e.signalId === pushSig.signalId && e.reason === 'PUSH')).toBe(true);
  });
});

describe('gate: model-version stratification (spec test 6)', () => {
  it('a version change mid-set invalidates prior accumulation with PRE_REGISTRATION', () => {
    const old = makeSignals({ sport: 'NFL', n: 300, clusters: 40, meanPp: 1.2, seed: 21, modelVersion: 'REC-V3', idPrefix: 'V3-', clusterOffset: 0 });
    const newer = makeSignals({ sport: 'NFL', n: 300, clusters: 40, meanPp: 1.2, seed: 22, modelVersion: 'REC-V4', idPrefix: 'V4-', clusterOffset: 40 });
    // newer recorded later
    for (const s of newer) s.recordedAtUtc = '2026-10-20T00:00:00Z';
    for (const s of old) s.recordedAtUtc = '2026-10-01T00:00:00Z';
    const { qualifying, excluded, modelVersionIssue } = prepareConfirmatorySet('NFL', [...old, ...newer]);
    expect(modelVersionIssue).not.toBeNull();
    expect(excluded.some((e) => e.reason === 'PRE_REGISTRATION')).toBe(true);
    // Only the newer version's signals remain qualifying.
    expect(new Set(qualifying.map((s) => s.modelVersion))).toEqual(new Set(['REC-V4']));
  });
});

describe('gate: cluster representation (spec test 8)', () => {
  it('600 signals crammed into too few clusters is INCONCLUSIVE', () => {
    const signals = makeSignals({ sport: 'NBA', n: 600, clusters: 12, meanPp: 1.8, sdPp: 2.0, seed: 8 });
    const r = evaluateGateAttempt('NBA', 1, signals, AT);
    expect(r.nEvaluable).toBeGreaterThanOrEqual(600);
    expect(r.distinctClusters).toBeLessThan(30);
    expect(r.verdict).toBe('INCONCLUSIVE');
    expect(r.notes.some((n) => n.includes('Insufficient cluster representation'))).toBe(true);
  });
});

describe('gate: retirement and commercial state (spec test 9)', () => {
  it('two failed attempts retire the commercial flag', () => {
    const state = sportCommercialState('NFL', [
      { attemptNo: 1, verdict: 'FAIL' },
      { attemptNo: 2, verdict: 'FAIL' },
    ], { status: 'granted' });
    expect(state.retired).toBe(true);
    expect(state.gatePassed).toBe(false);
    expect(state.commercialSignalEnabled).toBe(false); // even WITH compliance approval
    expect(state.explanation).toContain('retired');
  });

  it('PASS + compliance granted enables the flag', () => {
    const state = sportCommercialState('NFL', [{ attemptNo: 1, verdict: 'PASS' }], { status: 'granted' });
    expect(state.commercialSignalEnabled).toBe(true);
  });

  it('PASS without compliance approval still denies (default deny)', () => {
    const state = sportCommercialState('NFL', [{ attemptNo: 1, verdict: 'PASS' }], { status: 'pending' });
    expect(state.gatePassed).toBe(true);
    expect(state.commercialSignalEnabled).toBe(false);
  });

  it('no attempts denies', () => {
    const state = sportCommercialState('UFC', [], null);
    expect(state.commercialSignalEnabled).toBe(false);
  });

  it('fail then pass (second attempt succeeds) does not retire', () => {
    const state = sportCommercialState('NFL', [
      { attemptNo: 1, verdict: 'FAIL' },
      { attemptNo: 2, verdict: 'PASS' },
    ], { status: 'granted' });
    expect(state.retired).toBe(false);
    expect(state.commercialSignalEnabled).toBe(true);
  });
});

describe('gate: determinism', () => {
  it('the same signals and seed 20261024 always give the same lower bound', () => {
    const signals = makeSignals({ sport: 'NFL', n: 600, clusters: 60, meanPp: 1.1, sdPp: 2.4, seed: 13 });
    const a = evaluateGateAttempt('NFL', 1, signals, AT);
    const b = evaluateGateAttempt('NFL', 1, signals, '2026-11-02T00:00:00Z');
    expect(a.verdict).toBe(b.verdict);
    expect(a.meanClvPp).toBe(b.meanClvPp);
    expect(a.bootstrapLbPp).toBe(b.bootstrapLbPp);
    expect(a.seed).toBe(20261024);
  });

  it('cluster bootstrap preserves within-cluster dependence (clustered vs independent differ)', () => {
    const vals = [1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0];
    const clustered = ['g1', 'g1', 'g2', 'g2', 'g3', 'g3', 'g4', 'g4'];
    const independent = vals.map((_, i) => `s${i}`);
    const a = clusterBootstrapMean(vals, clustered, { seed: 1, replicates: 400 });
    const b = clusterBootstrapMean(vals, independent, { seed: 1, replicates: 400 });
    // Clustered resampling produces a different (wider) replicate distribution.
    const spread = (reps: number[]) => {
      const sorted = [...reps].sort((x, y) => x - y);
      return sorted[Math.floor(sorted.length * 0.975)] - sorted[Math.floor(sorted.length * 0.025)];
    };
    expect(spread(a.replicates)).toBeGreaterThan(spread(b.replicates));
  });
});
