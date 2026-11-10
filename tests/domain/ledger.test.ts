/**
 * PropStein — contract tests: ledger immutability.
 *
 * Spec test obligations:
 *   5. Post-registration mutation is rejected (no mutation path exists; the
 *      guard throws; forbidden fields are rejected in corrections).
 */

import { describe, expect, it } from 'vitest';
import type { LedgerEntryCore } from '../../src/lib/domain/ledger';
import { buildRevision, computeEntryHash, createLedgerEntry, isDuplicateOf, correlationGroupFor, verifyEntryChain } from '../../src/lib/domain/ledger';
import { mutateLedgerEntryCore } from '../../src/lib/server/ledger-service';

const BASE_INPUT = {
  userId: 'u1',
  sourceType: 'manual_entry' as const,
  sport: 'NFL',
  league: 'NFL',
  eventId: 'e1',
  gameClusterId: 'NFL:e1',
  playerId: 'p1',
  playerName: 'WR X',
  market: 'player_reception_yds',
  selection: 'over' as const,
  line: 52.5,
  enteredAmericanOdds: -115,
  enteredCounterpartOdds: -105,
  enteredImpliedProbability: 0.5349,
  breakEvenProbability: 0.5349,
  book: 'user_entered',
  capturedAtUtc: '2026-11-08T18:04:22Z',
  snapshotHash: 'snap-1',
  modelVersion: 'REC-V4',
  modelCoverage: 'calibrated' as const,
  modelProbability: 0.561,
  modelUncertaintyLower: 0.531,
  modelUncertaintyUpper: 0.590,
  priceAssessment: 'PRICE AT MARKET HURDLE',
  provenanceJson: '{}',
};

describe('ledger immutability contracts', () => {
  it('creates an entry with a genesis revision bound to the entry hash', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    expect(initialRevision.revisionNo).toBe(0);
    expect(initialRevision.reasonCode).toBe('ENTRY_CREATED');
    expect(initialRevision.priorHash).toBe('GENESIS');
    expect(initialRevision.newHash).toBe(entry.entryHash);
    expect(verifyEntryChain(entry, [initialRevision]).ok).toBe(true);
  });

  it('hash depends on every core field (tamper detection)', () => {
    const a = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    const b = createLedgerEntry({ ...BASE_INPUT, line: 53.5 }, '2026-11-08T18:06:00Z');
    expect(a.entry.entryHash).not.toBe(b.entry.entryHash);
    const c = createLedgerEntry({ ...BASE_INPUT, playerName: 'WR Y' }, '2026-11-08T18:06:00Z');
    expect(a.entry.entryHash).not.toBe(c.entry.entryHash);
    const d = createLedgerEntry({ ...BASE_INPUT, capturedAtUtc: '2026-11-08T18:05:00Z' }, '2026-11-08T18:06:00Z');
    expect(a.entry.entryHash).not.toBe(d.entry.entryHash);
  });

  it('verifyEntryChain detects a tampered core (record no longer matches its hash)', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    const tampered = { ...entry, line: 99 };
    const result = verifyEntryChain(tampered, [initialRevision]);
    expect(result.ok).toBe(false);
    expect(result.problems.some((p) => p.includes('altered'))).toBe(true);
  });

  it('verifyEntryChain detects a hash-chain discontinuity', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    const rev1 = buildRevision(entry, initialRevision, {
      reasonCode: 'PLAYER_NAME_TYPO',
      reasonText: 'Spelling corrected from source slip.',
      actor: 'u1',
      changedFields: { playerName: 'WR Y' },
      nowUtc: '2026-11-08T19:00:00Z',
    });
    const broken = { ...rev1, priorHash: '0'.repeat(64) };
    const result = verifyEntryChain(entry, [initialRevision, broken]);
    expect(result.ok).toBe(false);
    expect(result.problems.some((p) => p.includes('discontinuity'))).toBe(true);
  });

  it('test 5: post-registration mutation is rejected by the service guard', async () => {
    await expect(mutateLedgerEntryCore()).rejects.toThrow('APPEND_ONLY_VIOLATION');
  });

  it('corrections require a substantive reason', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    expect(() =>
      buildRevision(entry, initialRevision, {
        reasonCode: 'X',
        reasonText: '  ',
        actor: 'u1',
        changedFields: { playerName: 'WR Y' },
        nowUtc: '2026-11-08T19:00:00Z',
      }),
    ).toThrow('CORRECTION_REASON_REQUIRED');
  });

  it('corrections must change at least one field', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    expect(() =>
      buildRevision(entry, initialRevision, {
        reasonCode: 'X',
        reasonText: 'no-op',
        actor: 'u1',
        changedFields: {},
        nowUtc: '2026-11-08T19:00:00Z',
      }),
    ).toThrow('CORRECTION_EMPTY');
  });

  it('corrections cannot touch immutable fields (ledgerId, entryHash, createdAtUtc, snapshotHash)', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    for (const field of ['ledgerId', 'entryHash', 'createdAtUtc', 'snapshotHash']) {
      expect(() =>
        buildRevision(entry, initialRevision, {
          reasonCode: 'X',
          reasonText: 'attempt',
          actor: 'u1',
          changedFields: { [field]: 'new' },
          nowUtc: '2026-11-08T19:00:00Z',
        }),
      ).toThrow(`CORRECTION_FORBIDDEN_FIELD: ${field}`);
    }
  });

  it('a valid correction appends a chained revision and the chain still verifies', () => {
    const { entry, initialRevision } = createLedgerEntry(BASE_INPUT, '2026-11-08T18:06:00Z');
    const rev1 = buildRevision(entry, initialRevision, {
      reasonCode: 'PLAYER_NAME_TYPO',
      reasonText: 'Spelling corrected from source slip.',
      actor: 'u1',
      changedFields: { playerName: 'WR Y' },
      nowUtc: '2026-11-08T19:00:00Z',
    });
    const rev2 = buildRevision(entry, rev1, {
      reasonCode: 'EVENT_ID_NORMALIZED',
      reasonText: 'Event identifier normalized to the provider key.',
      actor: 'u1',
      changedFields: { eventId: 'e1-normalized' },
      nowUtc: '2026-11-08T20:00:00Z',
    });
    expect(rev1.revisionNo).toBe(1);
    expect(rev2.revisionNo).toBe(2);
    expect(rev2.priorHash).toBe(rev1.newHash);
    expect(rev1.priorHash).toBe(initialRevision.newHash);
    const result = verifyEntryChain(entry, [initialRevision, rev1, rev2]);
    expect(result.ok).toBe(true);
  });

  it('duplicate detection keys on user, event, player, market, selection, line, book, capturedAt', () => {
    const a = { ...BASE_INPUT };
    const b = { ...BASE_INPUT };
    expect(isDuplicateOf(a, b)).toBe(true);
    const c = { ...BASE_INPUT, line: 53.5 };
    expect(isDuplicateOf(a, c)).toBe(false);
    const d = { ...BASE_INPUT, capturedAtUtc: '2026-11-08T18:04:23Z' };
    expect(isDuplicateOf(a, d)).toBe(false);
  });

  it('correlation groups are same game cluster + same player', () => {
    expect(correlationGroupFor({ gameClusterId: 'NFL:e1', playerId: 'p1' }, { gameClusterId: 'NFL:e1', playerId: 'p1' })).toBe('corr:NFL:e1:p1');
    expect(correlationGroupFor({ gameClusterId: 'NFL:e1', playerId: 'p1' }, { gameClusterId: 'NFL:e1', playerId: 'p2' })).toBeNull();
    expect(correlationGroupFor({ gameClusterId: 'NFL:e1', playerId: 'p1' }, { gameClusterId: 'NFL:e2', playerId: 'p1' })).toBeNull();
  });

  it('computeEntryHash is stable across key order (canonical JSON)', () => {
    const core1: LedgerEntryCore = {
      ledgerId: 'x', userId: 'u', sourceType: 'manual_entry', sport: 'NFL', league: 'NFL', eventId: 'e',
      gameClusterId: 'g', playerId: 'p', playerName: 'P', market: 'm', selection: 'over' as const, line: 1.5,
      enteredAmericanOdds: -110, enteredCounterpartOdds: -110, enteredImpliedProbability: 0.5238,
      breakEvenProbability: 0.5238, book: 'b', capturedAtUtc: 't', snapshotHash: 's', modelVersion: null,
      modelCoverage: 'none' as const, modelProbability: null, modelUncertaintyLower: null,
      modelUncertaintyUpper: null, priceAssessment: 'SETTLED', provenanceJson: '{}',
    };
    const core2 = Object.fromEntries(Object.entries(core1).reverse()) as typeof core1;
    expect(computeEntryHash(core1, null)).toBe(computeEntryHash(core2, null));
  });
});
