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
import { runHurdleRouter, checkProvenance, HURDLE_BAND_PP } from '../../src/lib/domain/hurdle';
import { clusterBootstrapMean, shrunkMean, calibrationTable, buildLuckMeterReport } from '../../src/lib/domain/stats';
import { evaluateGateAttempt, CrossSportPoolingError, sportCommercialState } from '../../src/lib/domain/gate';
import { gradeEntry, priceClvPp } from '../../src/lib/domain/grading';
import { createLedgerEntry, buildRevision, verifyEntryChain } from '../../src/lib/domain/ledger';
import { lintCopy } from '../../src/lib/domain/copy-lint';
import { issueToken, verifyToken, revocationStore } from '../../src/lib/domain/tokens';

describe('odds math', () => {
  it('implied probability: -115 -> 0.534884', () => {
    expect(impliedProbability(-115)).toBeCloseTo(0.534884, 6);
  });
  it('implied probability: +150 -> 0.4', () => {
    expect(impliedProbability(150)).toBeCloseTo(0.4, 6);
  });
  it('implied probability: -100 -> 0.5', () => {
    expect(impliedProbability(-100)).toBeCloseTo(0.5, 6);
  });
  it('break-even equals implied probability', () => {
    expect(breakEvenProbability(-115)).toBe(impliedProbability(-115));
  });
  it('american round trip', () => {
    expect(americanFromImplied(impliedProbability(-115))).toBe(-115);
    expect(americanFromImplied(impliedProbability(150))).toBe(150);
  });
  it('devig sums to one', () => {
    const d = devigTwoWay(-115, -105);
    expect(d.over + d.under).toBeCloseTo(1, 9);
    expect(d.overround).toBeGreaterThan(1);
  });
  it('devig symmetry', () => {
    const a = devigTwoWay(-110, -110);
    expect(a.over).toBeCloseTo(0.5, 9);
  });
  it('fair probability for side', () => {
    expect(fairProbabilityForSide(-110, -110, 'over')).toBeCloseTo(0.5, 9);
    expect(fairProbabilityForSide(-110, -110, 'under')).toBeCloseTo(0.5, 9);
  });
  it('price delta sign: entered -115 vs comparison -112 is worse by ~0.7pp', () => {
    // example from the specification
    const delta = priceDeltaPp(-115, -112);
    expect(delta).toBeCloseTo(0.7, 1);
  });
  it('odds bands', () => {
    expect(oddsBand(-200)).toBe('short');
    expect(oddsBand(-110)).toBe('near_even');
    expect(oddsBand(+250)).toBe('long');
  });
});

describe('smoke: hurdle router', () => {
  const prov = (cutoffOffsetSec = -3600) => ({
    inputs: [
      { key: 'spread', label: 'Spread', sourceId: 'S1', observedAtUtc: new Date(Date.now() + cutoffOffsetSec * 1000).toISOString() },
      { key: 'total', label: 'Total', sourceId: 'S1', observedAtUtc: new Date(Date.now() + cutoffOffsetSec * 1000).toISOString() },
      { key: 'weather', label: 'Weather', sourceId: 'W1', observedAtUtc: new Date(Date.now() + cutoffOffsetSec * 1000).toISOString() },
    ],
    pricingCutoffUtc: new Date().toISOString(),
    snapshotHash: 'x',
  });
  const model = { coverage: 'none' as const, modelName: null, modelVersion: null, probability: null, uncertainty: null, calibrationStatus: 'none' as const, limitations: [], dataFreshnessUtc: null, corpusGames: null };
  const now = new Date().toISOString();
  const cmp = (odds: number, ageSec: number) => ({
    provider: 'P', book: 'B', overAmericanOdds: odds, underAmericanOdds: -105,
    capturedAtUtc: new Date(Date.now() - ageSec * 1000).toISOString(), licensed: true,
  });

  it('AT hurdle within band', () => {
    const r = runHurdleRouter({ sport: 'NFL', league: 'NFL', market: 'player_reception_yds', selection: 'over', line: 52.5, enteredAmericanOdds: -115, comparison: cmp(-114, 20), provenance: prov(), model, mode: 'market', nowUtc: now });
    expect(r.assessment).toBe('PRICE AT MARKET HURDLE');
  });
  it('BELOW hurdle when worse', () => {
    const r = runHurdleRouter({ sport: 'NFL', league: 'NFL', market: 'player_reception_yds', selection: 'over', line: 52.5, enteredAmericanOdds: -125, comparison: cmp(-110, 20), provenance: prov(), model, mode: 'market', nowUtc: now });
    expect(r.assessment).toBe('PRICE BELOW MARKET HURDLE');
  });
  it('stale quote fails closed', () => {
    const r = runHurdleRouter({ sport: 'NFL', league: 'NFL', market: 'player_reception_yds', selection: 'over', line: 52.5, enteredAmericanOdds: -115, comparison: cmp(-110, 400), provenance: prov(), model, mode: 'market', nowUtc: now });
    expect(r.assessment).toBe('STALE QUOTE');
  });
  it('unverified context fails closed', () => {
    const r = runHurdleRouter({ sport: 'NFL', league: 'NFL', market: 'player_reception_yds', selection: 'over', line: 52.5, enteredAmericanOdds: -115, comparison: cmp(-110, 20), provenance: { ...prov(), inputs: prov().inputs.filter((i) => i.key !== 'weather') }, model, mode: 'market', nowUtc: now });
    expect(r.assessment).toBe('UNVERIFIED CONTEXT');
  });
  it('no comparison -> insufficient market data', () => {
    const r = runHurdleRouter({ sport: 'UFC', league: 'UFC', market: 'fighter_prize_money', selection: 'over', line: 2.5, enteredAmericanOdds: -110, comparison: null, provenance: prov(), model, mode: 'market', nowUtc: now });
    expect(r.assessment).toBe('INSUFFICIENT MARKET DATA');
  });
});

describe('smoke: stats + gate', () => {
  it('bootstrap deterministic with fixed seed', () => {
    const vals = Array.from({ length: 40 }, (_, i) => (i % 2 === 0 ? 1.2 : -0.8));
    const clusters = vals.map((_, i) => `g${Math.floor(i / 2)}`);
    const a = clusterBootstrapMean(vals, clusters, { seed: 20261024 });
    const b = clusterBootstrapMean(vals, clusters, { seed: 20261024 });
    expect(a.lowerBoundOneSided0125).toBe(b.lowerBoundOneSided0125);
  });
  it('shrinkage', () => {
    expect(shrunkMean([1, 1, 1], 100)).toBeCloseTo(3 / 103, 9);
  });
  it('gate rejects cross-sport pooling', () => {
    expect(() => evaluateGateAttempt('NFL', 1, [{ signalId: 'x', sport: 'NBA', gameClusterId: 'g', playerId: 'p', clvPp: 1, evaluable: true, reasonCode: null, modelVersion: null, recordedAtUtc: '2026-11-01T00:00:00Z' }], '2026-11-01T00:00:00Z')).toThrow(CrossSportPoolingError);
  });
});

describe('smoke: ledger immutability', () => {
  it('creates entry with genesis revision and verifies chain', () => {
    const { entry, initialRevision } = createLedgerEntry({
      userId: 'u1', sourceType: 'manual_entry', sport: 'NFL', league: 'NFL', eventId: 'e1', playerId: 'p1',
      playerName: 'WR X', market: 'player_reception_yds', selection: 'over', line: 52.5,
      enteredAmericanOdds: -115, enteredCounterpartOdds: -105, enteredImpliedProbability: 0.5349, breakEvenProbability: 0.5349,
      book: 'user_entered', capturedAtUtc: '2026-11-08T18:04:22Z', snapshotHash: 'abc', modelVersion: 'REC-V4',
      modelCoverage: 'calibrated', modelProbability: 0.561, modelUncertaintyLower: 0.531, modelUncertaintyUpper: 0.590,
      priceAssessment: 'PRICE AT MARKET HURDLE', provenanceJson: '{}',
    }, '2026-11-08T18:05:00Z');
    expect(initialRevision.revisionNo).toBe(0);
    expect(verifyEntryChain(entry, [initialRevision]).ok).toBe(true);
    const rev = buildRevision(entry, initialRevision, { reasonCode: 'PLAYER_NAME_TYPO', reasonText: 'Name spelled incorrectly', actor: 'u1', changedFields: { playerName: 'WR Y' }, nowUtc: '2026-11-08T19:00:00Z' });
    expect(verifyEntryChain(entry, [initialRevision, rev]).ok).toBe(true);
  });
});

describe('smoke: copy lint', () => {
  it('catches prohibited phrasing', () => {
    expect(lintCopy('This is a clear edge, take it now').length).toBeGreaterThan(0);
    expect(lintCopy('Lean Over 52.5').length).toBeGreaterThan(0);
    expect(lintCopy('This is not a betting recommendation').length).toBe(0);
  });
});

describe('smoke: tokens', () => {
  it('issues, verifies, revokes', () => {
    const { token, claims } = issueToken('u1', 'pro', ['slips:write']);
    expect(verifyToken(token).ok).toBe(true);
    revocationStore.revoke(claims.jti, claims.exp);
    expect(verifyToken(token)).toEqual({ ok: false, reason: 'revoked' });
  });
});
