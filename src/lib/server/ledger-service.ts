/**
 * PropStein — ledger service (append-only persistence).
 *
 * There is deliberately NO function that updates a LedgerEntry row's core
 * fields. Corrections append to LedgerRevision; settlement and closing
 * references are child records. Immutability is enforced by absence of a
 * mutation path plus hash-chain verification.
 */

import { db } from '@/lib/db';
import { createLedgerEntry, buildRevision, verifyEntryChain, computeEntryHash } from '@/lib/domain/ledger';
import { closingReference, settle } from '@/lib/domain/sim-market';
import { fairProbabilityForSide, impliedProbability, breakEvenProbability } from '@/lib/domain/odds';
import { gradeEntry, priceClvPp } from '@/lib/domain/grading';
import { canonicalJson, isoUtc, snapshotHash, sha256hex } from '@/lib/domain/determinism';
import { FRESHNESS_THRESHOLDS } from '@/lib/domain/freshness';
import { MODEL_FEED_PROVIDER } from '@/lib/domain/model-registry';
import type { AssessmentBundle, ConfirmedSlip, DemoScenario } from './assessment-service';
import type { ClvOutcome, LedgerRevisionRecord } from '@/lib/domain/types';
import type { LedgerEntryRecord } from '@/lib/domain/ledger';

export class ImmutableLedgerError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'ImmutableLedgerError';
  }
}

function toEntryRecord(row: {
  ledgerId: string;
  userId: string;
  sourceType: string;
  sport: string;
  league: string;
  eventId: string;
  gameClusterId: string;
  playerId: string;
  playerName: string;
  market: string;
  selection: string;
  line: number;
  enteredAmericanOdds: number;
  enteredCounterpartOdds: number;
  enteredImpliedProbability: number;
  breakEvenProbability: number;
  book: string;
  capturedAtUtc: Date;
  snapshotHash: string;
  modelVersion: string | null;
  modelCoverage: string;
  modelProbability: number | null;
  modelUncertaintyLower: number | null;
  modelUncertaintyUpper: number | null;
  priceAssessment: string;
  provenanceJson: string;
  createdAtUtc: Date;
  entryHash: string;
  duplicateOfLedgerId: string | null;
  correlationGroup: string | null;
  correlationReason: string | null;
}): LedgerEntryRecord {
  return {
    ledgerId: row.ledgerId,
    userId: row.userId,
    sourceType: row.sourceType as LedgerEntryRecord['sourceType'],
    sport: row.sport,
    league: row.league,
    eventId: row.eventId,
    gameClusterId: row.gameClusterId,
    playerId: row.playerId,
    playerName: row.playerName,
    market: row.market,
    selection: row.selection as 'over' | 'under',
    line: row.line,
    enteredAmericanOdds: row.enteredAmericanOdds,
    enteredCounterpartOdds: row.enteredCounterpartOdds,
    enteredImpliedProbability: row.enteredImpliedProbability,
    breakEvenProbability: row.breakEvenProbability,
    book: row.book,
    capturedAtUtc: row.capturedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    snapshotHash: row.snapshotHash,
    modelVersion: row.modelVersion,
    modelCoverage: row.modelCoverage as 'calibrated' | 'uncalibrated' | 'none',
    modelProbability: row.modelProbability,
    modelUncertaintyLower: row.modelUncertaintyLower,
    modelUncertaintyUpper: row.modelUncertaintyUpper,
    priceAssessment: row.priceAssessment,
    provenanceJson: row.provenanceJson,
    createdAtUtc: row.createdAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    entryHash: row.entryHash,
    duplicateOfLedgerId: row.duplicateOfLedgerId,
    correlationGroup: row.correlationGroup,
    correlationReason: row.correlationReason,
  };
}

export interface SaveFromAssessmentOptions {
  userId: string;
  bundle: AssessmentBundle;
  sourceType: 'manual_entry' | 'screenshot_upload' | 'extension_observation';
  slipUploadId?: string | null;
  wagerAmount?: number | null;
  scenario?: DemoScenario;
}

export async function saveLedgerEntryFromAssessment(
  opts: SaveFromAssessmentOptions,
): Promise<{ ledgerId: string; duplicateOfLedgerId: string | null; correlationGroup: string | null }> {
  const { bundle } = opts;
  const slip: ConfirmedSlip = bundle.slip;
  const nowUtc = isoUtc();

  // Duplicate detection: same user, event, player, market, selection, line,
  // book, capturedAt -> flag, retain, exclude.
  const dupCandidates = await db.ledgerEntry.findMany({
    where: {
      userId: opts.userId,
      eventId: slip.eventId,
      playerId: slip.playerId,
      market: slip.market,
      selection: slip.selection,
      line: slip.line,
      book: slip.book,
      capturedAtUtc: new Date(slip.capturedAtUtc),
    },
  });
  const duplicateOfLedgerId = dupCandidates.length > 0 ? dupCandidates[0].ledgerId : null;

  // Correlation detection: same game cluster + player, different record.
  const corrCandidates = await db.ledgerEntry.findMany({
    where: { userId: opts.userId, gameClusterId: `${slip.sport}:${slip.eventId}`, playerId: slip.playerId },
  });
  const correlationGroup = corrCandidates.length > 0 ? `corr:${slip.sport}:${slip.eventId}:${slip.playerId}` : null;

  const provenancePayload = {
    provenance: bundle.provenance,
    comparison: bundle.comparison,
    scenario: bundle.scenario,
    assessmentId: bundle.assessmentId,
  };

  const { entry, initialRevision } = createLedgerEntry(
    {
      userId: opts.userId,
      sourceType: opts.sourceType,
      sport: slip.sport,
      league: slip.league,
      eventId: slip.eventId,
      gameClusterId: `${slip.sport}:${slip.eventId}`,
      playerId: slip.playerId,
      playerName: slip.playerName,
      market: slip.market,
      selection: slip.selection,
      line: slip.line,
      enteredAmericanOdds: slip.enteredAmericanOdds,
      enteredCounterpartOdds: slip.enteredCounterpartOdds,
      enteredImpliedProbability: Number(impliedProbability(slip.enteredAmericanOdds).toFixed(4)),
      breakEvenProbability: Number(breakEvenProbability(slip.enteredAmericanOdds).toFixed(4)),
      book: slip.book,
      capturedAtUtc: slip.capturedAtUtc,
      snapshotHash: snapshotHash(provenancePayload),
      modelVersion: bundle.model.modelVersion,
      modelCoverage: bundle.model.coverage === 'unavailable' ? 'none' : bundle.model.coverage,
      modelProbability: bundle.model.probability,
      modelUncertaintyLower: bundle.model.uncertainty?.lower ?? null,
      modelUncertaintyUpper: bundle.model.uncertainty?.upper ?? null,
      priceAssessment: bundle.hurdle.assessment,
      provenanceJson: canonicalJson(provenancePayload),
      duplicateOfLedgerId,
      correlationGroup,
      correlationReason: correlationGroup ? 'Same game cluster and player as an existing record' : null,
    },
    nowUtc,
  );

  await db.ledgerEntry.create({
    data: {
      ...entry,
      capturedAtUtc: new Date(entry.capturedAtUtc),
      assessmentId: bundle.assessmentId,
      wagerAmount: opts.wagerAmount ?? null,
      revisions: {
        create: {
          revisionNo: initialRevision.revisionNo,
          reasonCode: initialRevision.reasonCode,
          reasonText: initialRevision.reasonText,
          actor: initialRevision.actor,
          changedFieldsJson: '[]',
          priorHash: initialRevision.priorHash,
          newHash: initialRevision.newHash,
        },
      },
    },
  });

  // Persist the comparison snapshot alongside the entry.
  if (bundle.comparison) {
    await db.marketSnapshot.create({
      data: {
        ledgerEntryId: entry.ledgerId,
        assessmentId: bundle.assessmentId,
        provider: bundle.comparison.provider,
        book: bundle.comparison.book,
        sport: slip.sport,
        market: slip.market,
        selection: slip.selection,
        line: slip.line,
        overAmericanOdds: bundle.comparison.overAmericanOdds,
        underAmericanOdds: bundle.comparison.underAmericanOdds,
        capturedAtUtc: new Date(bundle.comparison.capturedAtUtc),
        rawRef: bundle.comparison.rawRef ?? null,
        snapshotHash: sha256hex(canonicalJson(bundle.comparison)),
      },
    });
  }

  return { ledgerId: entry.ledgerId, duplicateOfLedgerId, correlationGroup };
}

// ---------------------------------------------------------------------------
// Closing reference capture (background worker action)
// ---------------------------------------------------------------------------

export async function captureClosingReference(
  ledgerId: string,
  scenario: 'none' | 'stale_close' | 'conflicting_close' | 'missing_close' = 'none',
): Promise<{ quality: string; reason?: string }> {
  const entry = await db.ledgerEntry.findUnique({ where: { ledgerId } });
  if (!entry) throw new Error('ENTRY_NOT_FOUND');
  const existing = await db.closingReference.findUnique({ where: { ledgerEntryId: ledgerId } });
  if (existing) {
    return { quality: existing.quality, reason: 'ALREADY_CAPTURED (append-only; recapture requires a new revision context)' };
  }

  const close = closingReference({
    sport: entry.sport,
    eventId: entry.eventId,
    playerId: entry.playerId,
    market: entry.market,
    line: entry.line,
    selection: entry.selection as 'over' | 'under',
    entryOverOdds: entry.enteredAmericanOdds,
    entryUnderOdds: entry.enteredCounterpartOdds,
    capturedAtUtc: entry.capturedAtUtc.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    nowUtc: isoUtc(),
    scenario,
  });

  const integrityHash = sha256hex(
    canonicalJson({ ledgerId, close, modelFeed: MODEL_FEED_PROVIDER, independence: close.independenceVerified }),
  );

  await db.closingReference.create({
    data: {
      ledgerEntryId: ledgerId,
      provider: close.provider,
      capturedAtUtc: close.capturedAtUtc ? new Date(close.capturedAtUtc) : null,
      overAmericanOdds: close.overAmericanOdds,
      underAmericanOdds: close.underAmericanOdds,
      americanOdds: close.overAmericanOdds,
      impliedProbability: close.impliedProbability,
      fairProbability: close.fairProbability,
      quality: close.quality,
      secondSourceJson: close.secondSource ? JSON.stringify(close.secondSource) : null,
      independenceVerified: close.independenceVerified,
      integrityHash,
    },
  });

  return { quality: close.quality };
}

// ---------------------------------------------------------------------------
// Settlement (background worker action)
// ---------------------------------------------------------------------------

export async function settleLedgerEntry(
  ledgerId: string,
  scenario: 'none' | 'push' | 'void' | 'canceled' | 'dnp' = 'none',
): Promise<{ status: string; result: string | null; clvPp: number | null; evaluable: boolean; reasonCode: string | null }> {
  const entryRow = await db.ledgerEntry.findUnique({ where: { ledgerId }, include: { closingReference: true, settlement: true } });
  if (!entryRow) throw new Error('ENTRY_NOT_FOUND');
  if (entryRow.settlement && entryRow.settlement.status !== 'pending') {
    return {
      status: entryRow.settlement.status,
      result: entryRow.settlement.result,
      clvPp: null,
      evaluable: false,
      reasonCode: 'ALREADY_SETTLED',
    };
  }

  const entry = toEntryRecord(entryRow);
  // Win probability for the demo settlement engine: model probability where
  // calibrated, otherwise the entry fair probability.
  const winProb =
    entry.modelCoverage === 'calibrated' && entry.modelProbability !== null
      ? entry.modelProbability
      : fairProbabilityForSide(entry.enteredAmericanOdds, entry.enteredCounterpartOdds, entry.selection);

  const sim = settle({
    sport: entry.sport,
    eventId: entry.eventId,
    playerId: entry.playerId,
    market: entry.market,
    line: entry.line,
    selection: entry.selection,
    winProbability: winProb,
    scenario,
  });

  const status = await db.settlement.upsert({
    where: { ledgerEntryId: ledgerId },
    create: {
      ledgerEntryId: ledgerId,
      status: sim.status,
      result: sim.result,
      reasonCode: sim.reasonCode,
      actualValue: sim.actualValue,
      source: 'DEMO-SETTLE-1 (simulated)',
      settledAtUtc: new Date(),
    },
    update: {
      status: sim.status,
      result: sim.result,
      reasonCode: sim.reasonCode,
      actualValue: sim.actualValue,
      settledAtUtc: new Date(),
    },
  });

  // Grade immediately with whatever closing reference exists (possibly none).
  const graded = gradeFromRow(entryRow, status.status, status.result, sim.status);
  return {
    status: sim.status,
    result: sim.result,
    clvPp: graded.clvPp,
    evaluable: graded.evaluable,
    reasonCode: graded.reasonCode,
  };
}

function gradeFromRow(
  entryRow: { closingReference: { quality: string; fairProbability: number | null; independenceVerified: boolean } | null },
  status: string,
  result: string | null,
  simStatus: string,
): { clvPp: number | null; evaluable: boolean; reasonCode: string | null } {
  const entry = toEntryRecord(entryRow as never);
  if (simStatus === 'push' || simStatus === 'void' || simStatus === 'canceled' || simStatus === 'dnp') {
    return { clvPp: null, evaluable: false, reasonCode: simStatus.toUpperCase() };
  }
  const r = priceClvPp(entry, {
    quality: (entryRow.closingReference?.quality ?? 'missing') as 'fresh' | 'stale' | 'missing' | 'conflicting',
    fairProbability: entryRow.closingReference?.fairProbability ?? null,
    independenceVerified: entryRow.closingReference?.independenceVerified ?? false,
    provider: null,
  });
  return { clvPp: r.clvPp, evaluable: r.reason === null, reasonCode: r.reason };
}

// ---------------------------------------------------------------------------
// Corrections (append-only revisions)
// ---------------------------------------------------------------------------

export async function appendCorrection(
  ledgerId: string,
  reasonCode: string,
  reasonText: string,
  actor: string,
  changedFields: Record<string, unknown>,
): Promise<LedgerRevisionRecord> {
  const entryRow = await db.ledgerEntry.findUnique({ where: { ledgerId } });
  if (!entryRow) throw new Error('ENTRY_NOT_FOUND');
  const entry = toEntryRecord(entryRow);
  const revisions = await db.ledgerRevision.findMany({
    where: { ledgerEntryId: ledgerId },
    orderBy: { revisionNo: 'asc' },
  });
  const latest: LedgerRevisionRecord = {
    revisionNo: revisions[revisions.length - 1].revisionNo,
    reasonCode: revisions[revisions.length - 1].reasonCode,
    reasonText: revisions[revisions.length - 1].reasonText,
    actor: revisions[revisions.length - 1].actor,
    changedFields: JSON.parse(revisions[revisions.length - 1].changedFieldsJson),
    priorHash: revisions[revisions.length - 1].priorHash,
    newHash: revisions[revisions.length - 1].newHash,
    createdAtUtc: revisions[revisions.length - 1].createdAtUtc.toISOString(),
  };
  const revision = buildRevision(entry, latest, {
    reasonCode,
    reasonText,
    actor,
    changedFields,
    nowUtc: isoUtc(),
  });
  await db.ledgerRevision.create({
    data: {
      ledgerEntryId: ledgerId,
      revisionNo: revision.revisionNo,
      reasonCode: revision.reasonCode,
      reasonText: revision.reasonText,
      actor: revision.actor,
      changedFieldsJson: JSON.stringify(changedFields),
      priorHash: revision.priorHash,
      newHash: revision.newHash,
    },
  });
  return revision;
}

/**
 * Attempted direct mutation — always rejected. Exists so tests can prove the
 * guard, and so future contributors get an explicit error instead of a path.
 */
export async function mutateLedgerEntryCore(): Promise<never> {
  throw new ImmutableLedgerError(
    'APPEND_ONLY_VIOLATION: ledger entries cannot be mutated. Corrections must create a new revision with a reason and integrity hash.',
  );
}

// ---------------------------------------------------------------------------
// Integrity verification
// ---------------------------------------------------------------------------

export async function verifyLedgerIntegrity(ledgerId: string): Promise<{ ok: boolean; problems: string[] }> {
  const entryRow = await db.ledgerEntry.findUnique({ where: { ledgerId } });
  if (!entryRow) return { ok: false, problems: ['entry not found'] };
  const entry = toEntryRecord(entryRow);
  const revisions = await db.ledgerRevision.findMany({
    where: { ledgerEntryId: ledgerId },
    orderBy: { revisionNo: 'asc' },
  });
  return verifyEntryChain(
    entry,
    revisions.map((r) => ({
      revisionNo: r.revisionNo,
      reasonCode: r.reasonCode,
      reasonText: r.reasonText,
      actor: r.actor,
      changedFields: JSON.parse(r.changedFieldsJson),
      priorHash: r.priorHash,
      newHash: r.newHash,
      createdAtUtc: r.createdAtUtc.toISOString(),
    })),
  );
}

// ---------------------------------------------------------------------------
// Record building (feeds the Luck Meter)
// ---------------------------------------------------------------------------

export async function buildOutcomesForUser(userId: string): Promise<ClvOutcome[]> {
  const rows = await db.ledgerEntry.findMany({
    where: { userId },
    include: { closingReference: true, settlement: true },
    orderBy: { createdAtUtc: 'asc' },
  });
  const outcomes: ClvOutcome[] = rows.map((row) => {
    const entry = toEntryRecord(row);
    const settledStatus = row.settlement?.status ?? 'pending';
    const graded = gradeEntry(
      entry,
      row.closingReference
        ? {
            quality: row.closingReference.quality as 'fresh' | 'stale' | 'missing' | 'conflicting',
            fairProbability: row.closingReference.fairProbability,
            independenceVerified: row.closingReference.independenceVerified,
            provider: row.closingReference.provider,
          }
        : null,
      { status: settledStatus as 'pending' | 'settled' | 'void' | 'canceled' | 'push' | 'dnp', result: (row.settlement?.result ?? null) as 'win' | 'loss' | 'push' | 'void' | null },
      { duplicate: Boolean(entry.duplicateOfLedgerId), correlatedExcluded: false },
    );
    return graded;
  });
  return outcomes;
}

export function entryView(row: {
  ledgerId: string;
  sport: string;
  playerName: string;
  market: string;
  selection: string;
  line: number;
  enteredAmericanOdds: number;
  priceAssessment: string;
  capturedAtUtc: Date;
  createdAtUtc: Date;
  settlement?: { status: string; result: string | null } | null;
  closingReference?: { quality: string } | null;
  duplicateOfLedgerId: string | null;
  correlationGroup: string | null;
}) {
  return {
    ledgerId: row.ledgerId,
    sport: row.sport,
    playerName: row.playerName,
    market: row.market,
    selection: row.selection,
    line: row.line,
    enteredAmericanOdds: row.enteredAmericanOdds,
    priceAssessment: row.priceAssessment,
    capturedAtUtc: row.capturedAtUtc.toISOString(),
    createdAtUtc: row.createdAtUtc.toISOString(),
    settlementStatus: row.settlement?.status ?? 'pending',
    settlementResult: row.settlement?.result ?? null,
    closingQuality: row.closingReference?.quality ?? 'missing',
    duplicate: Boolean(row.duplicateOfLedgerId),
    correlated: Boolean(row.correlationGroup),
  };
}
