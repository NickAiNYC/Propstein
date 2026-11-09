/**
 * PropStein — Immutable Ledger (module 3).
 *
 * Append-only by construction:
 *   - The LedgerRepository interface exposes NO update/delete for entries.
 *   - Corrections append a revision (reason, actor, timestamp, prior hash,
 *     new hash) and are materialized as a view — the original row never
 *     changes.
 *   - Settlement and closing references are child records, not mutations.
 *   - Duplicate / correlated entries are flagged, never merged.
 */

import { canonicalJson, sha256hex, uuid } from './determinism';
import type { LedgerRevisionRecord, LedgerSourceType } from './types';

/** Core fields that participate in the entry hash (immutable set). */
export interface LedgerEntryCore {
  ledgerId: string;
  userId: string;
  sourceType: LedgerSourceType;
  sport: string;
  league: string;
  eventId: string;
  gameClusterId: string;
  playerId: string;
  playerName: string;
  market: string;
  selection: 'over' | 'under';
  line: number;
  enteredAmericanOdds: number;
  enteredCounterpartOdds: number;
  enteredImpliedProbability: number;
  breakEvenProbability: number;
  book: string;
  capturedAtUtc: string;
  snapshotHash: string;
  modelVersion: string | null;
  modelCoverage: 'calibrated' | 'uncalibrated' | 'none';
  modelProbability: number | null;
  modelUncertaintyLower: number | null;
  modelUncertaintyUpper: number | null;
  priceAssessment: string;
  provenanceJson: string;
}

export interface LedgerEntryRecord extends LedgerEntryCore {
  createdAtUtc: string;
  entryHash: string;
  /** Flags — set at creation or by an appended revision, never silently. */
  duplicateOfLedgerId: string | null;
  correlationGroup: string | null;
  correlationReason: string | null;
}

export interface NewLedgerEntryInput {
  userId: string;
  sourceType: LedgerSourceType;
  sport: string;
  league: string;
  eventId: string;
  gameClusterId?: string;
  playerId: string;
  playerName: string;
  market: string;
  selection: 'over' | 'under';
  line: number;
  enteredAmericanOdds: number;
  enteredCounterpartOdds: number;
  enteredImpliedProbability: number;
  breakEvenProbability: number;
  book: string;
  capturedAtUtc: string;
  snapshotHash: string;
  modelVersion: string | null;
  modelCoverage: 'calibrated' | 'uncalibrated' | 'none';
  modelProbability: number | null;
  modelUncertaintyLower: number | null;
  modelUncertaintyUpper: number | null;
  priceAssessment: string;
  provenanceJson: string;
  duplicateOfLedgerId?: string | null;
  correlationGroup?: string | null;
  correlationReason?: string | null;
}

/** The hash covers the immutable core + the prior hash (chain per entry). */
export function computeEntryHash(core: LedgerEntryCore, priorHash: string | null): string {
  return sha256hex(
    canonicalJson({
      core,
      priorHash,
    }),
  );
}

export function createLedgerEntry(input: NewLedgerEntryInput, nowUtc: string): {
  entry: LedgerEntryRecord;
  initialRevision: LedgerRevisionRecord;
} {
  const core: LedgerEntryCore = {
    ledgerId: uuid(),
    userId: input.userId,
    sourceType: input.sourceType,
    sport: input.sport,
    league: input.league,
    eventId: input.eventId,
    gameClusterId: input.gameClusterId ?? `${input.sport}:${input.eventId}`,
    playerId: input.playerId,
    playerName: input.playerName,
    market: input.market,
    selection: input.selection,
    line: input.line,
    enteredAmericanOdds: input.enteredAmericanOdds,
    enteredCounterpartOdds: input.enteredCounterpartOdds,
    enteredImpliedProbability: input.enteredImpliedProbability,
    breakEvenProbability: input.breakEvenProbability,
    book: input.book,
    capturedAtUtc: input.capturedAtUtc,
    snapshotHash: input.snapshotHash,
    modelVersion: input.modelVersion,
    modelCoverage: input.modelCoverage,
    modelProbability: input.modelProbability,
    modelUncertaintyLower: input.modelUncertaintyLower,
    modelUncertaintyUpper: input.modelUncertaintyUpper,
    priceAssessment: input.priceAssessment,
    provenanceJson: input.provenanceJson,
  };

  const entryHash = computeEntryHash(core, null);
  const entry: LedgerEntryRecord = {
    ...core,
    createdAtUtc: nowUtc,
    entryHash,
    duplicateOfLedgerId: input.duplicateOfLedgerId ?? null,
    correlationGroup: input.correlationGroup ?? null,
    correlationReason: input.correlationReason ?? null,
  };

  const initialRevision: LedgerRevisionRecord = {
    revisionNo: 0,
    reasonCode: 'ENTRY_CREATED',
    reasonText: 'Ledger entry created from a confirmed assessment. Append-only record starts here.',
    actor: input.userId,
    changedFields: [],
    priorHash: 'GENESIS',
    newHash: entryHash,
    createdAtUtc: nowUtc,
  };

  return { entry, initialRevision };
}

export interface CorrectionInput {
  reasonCode: string;
  reasonText: string;
  actor: string;
  changedFields: Record<string, unknown>;
  nowUtc: string;
}

/**
 * Append a correction revision. The ORIGINAL entry is untouched; the caller
 * receives a "head" hash that downstream records must reference.
 */
export function buildRevision(
  entry: LedgerEntryRecord,
  latestRevision: LedgerRevisionRecord,
  correction: CorrectionInput,
): LedgerRevisionRecord {
  if (!correction.reasonText || correction.reasonText.trim().length < 3) {
    throw new Error('CORRECTION_REASON_REQUIRED: every revision must carry a reason.');
  }
  if (Object.keys(correction.changedFields).length === 0) {
    throw new Error('CORRECTION_EMPTY: revisions must change at least one field.');
  }
  const forbidden = new Set(['ledgerId', 'entryHash', 'createdAtUtc', 'snapshotHash']);
  for (const k of Object.keys(correction.changedFields)) {
    if (forbidden.has(k)) {
      throw new Error(`CORRECTION_FORBIDDEN_FIELD: ${k} is immutable and cannot be revised.`);
    }
  }
  const newHash = sha256hex(
    canonicalJson({
      priorHash: latestRevision.newHash,
      reasonCode: correction.reasonCode,
      changedFields: correction.changedFields,
      at: correction.nowUtc,
    }),
  );
  return {
    revisionNo: latestRevision.revisionNo + 1,
    reasonCode: correction.reasonCode,
    reasonText: correction.reasonText,
    actor: correction.actor,
    changedFields: Object.keys(correction.changedFields),
    priorHash: latestRevision.newHash,
    newHash,
    createdAtUtc: correction.nowUtc,
  };
}

/**
 * Verify an entry's hash chain. Returns ok=false if any stored core no longer
 * matches its recorded hash (tamper detection) or the chain is discontinuous.
 */
export function verifyEntryChain(
  entry: LedgerEntryRecord,
  revisions: LedgerRevisionRecord[],
): { ok: boolean; problems: string[] } {
  const problems: string[] = [];
  // Recompute over exactly the immutable core fields (order irrelevant; canonicalJson sorts).
  const core: LedgerEntryCore = {
    ledgerId: entry.ledgerId,
    userId: entry.userId,
    sourceType: entry.sourceType,
    sport: entry.sport,
    league: entry.league,
    eventId: entry.eventId,
    gameClusterId: entry.gameClusterId,
    playerId: entry.playerId,
    playerName: entry.playerName,
    market: entry.market,
    selection: entry.selection,
    line: entry.line,
    enteredAmericanOdds: entry.enteredAmericanOdds,
    enteredCounterpartOdds: entry.enteredCounterpartOdds,
    enteredImpliedProbability: entry.enteredImpliedProbability,
    breakEvenProbability: entry.breakEvenProbability,
    book: entry.book,
    capturedAtUtc: entry.capturedAtUtc,
    snapshotHash: entry.snapshotHash,
    modelVersion: entry.modelVersion,
    modelCoverage: entry.modelCoverage,
    modelProbability: entry.modelProbability,
    modelUncertaintyLower: entry.modelUncertaintyLower,
    modelUncertaintyUpper: entry.modelUncertaintyUpper,
    priceAssessment: entry.priceAssessment,
    provenanceJson: entry.provenanceJson,
  };
  const recomputed = computeEntryHash(core, null);
  if (recomputed !== entry.entryHash) {
    problems.push('entry core does not match its recorded hash (record may have been altered)');
  }
  if (revisions.length === 0) {
    problems.push('missing genesis revision');
    return { ok: false, problems };
  }
  if (revisions[0].revisionNo !== 0 || revisions[0].newHash !== entry.entryHash) {
    problems.push('genesis revision does not bind to the entry hash');
  }
  for (let i = 1; i < revisions.length; i++) {
    if (revisions[i].revisionNo !== revisions[i - 1].revisionNo + 1) {
      problems.push(`revision numbering breaks at ${revisions[i].revisionNo}`);
    }
    if (revisions[i].priorHash !== revisions[i - 1].newHash) {
      problems.push(`hash chain discontinuity at revision ${revisions[i].revisionNo}`);
    }
  }
  return { ok: problems.length === 0, problems };
}

/**
 * Duplicate detection: identical (user, event, player, market, selection,
 * line, book, capturedAt) already in the ledger -> flag as duplicate, retain
 * the record, exclude from the confirmatory count.
 */
export function isDuplicateOf(
  candidate: NewLedgerEntryInput,
  existing: NewLedgerEntryInput,
): boolean {
  return (
    candidate.userId === existing.userId &&
    candidate.eventId === existing.eventId &&
    candidate.playerId === existing.playerId &&
    candidate.market === existing.market &&
    candidate.selection === existing.selection &&
    candidate.line === existing.line &&
    candidate.book === existing.book &&
    candidate.capturedAtUtc === existing.capturedAtUtc
  );
}

/**
 * Correlation detection: same game cluster AND same player, or same game
 * cluster with overlapping markets -> same correlation group (cluster
 * dependence is preserved for statistics; entries are flagged not merged).
 */
export function correlationGroupFor(
  a: { gameClusterId: string; playerId: string },
  b: { gameClusterId: string; playerId: string },
): string | null {
  if (a.gameClusterId === b.gameClusterId && a.playerId === b.playerId) {
    return `corr:${a.gameClusterId}:${a.playerId}`;
  }
  return null;
}
