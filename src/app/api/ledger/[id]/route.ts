/**
 * GET /api/ledger/{id} — full entry detail: core record, Evidence DNA
 * (provenance/model/market), revision history, closing reference,
 * settlement, CLV grade, and hash-chain integrity status.
 */

import { db } from '@/lib/db';
import { getSessionUser } from '@/lib/server/session';
import { verifyLedgerIntegrity, buildOutcomesForUser } from '@/lib/server/ledger-service';
import { fail, ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getSessionUser();

  const row = await db.ledgerEntry.findUnique({
    where: { ledgerId: id },
    include: { revisions: { orderBy: { revisionNo: 'asc' } }, closingReference: true, settlement: true, snapshots: true, alerts: true },
  });
  if (!row || row.userId !== user.id) return fail(404, 'NOT_FOUND', 'Ledger entry not found.');

  const integrity = await verifyLedgerIntegrity(id);
  const outcomes = (await buildOutcomesForUser(user.id)).filter((o) => o.ledgerId === id);
  const outcome = outcomes[0] ?? null;

  const provenance = JSON.parse(row.provenanceJson || '{}');
  const revisions = row.revisions.map((r) => ({
    revisionNo: r.revisionNo,
    reasonCode: r.reasonCode,
    reasonText: r.reasonText,
    actor: r.actor,
    changedFields: JSON.parse(r.changedFieldsJson),
    priorHash: r.priorHash,
    newHash: r.newHash,
    createdAtUtc: r.createdAtUtc.toISOString(),
  }));

  return ok({
    entry: {
      ledgerId: row.ledgerId,
      sourceType: row.sourceType,
      sport: row.sport,
      league: row.league,
      eventId: row.eventId,
      gameClusterId: row.gameClusterId,
      playerId: row.playerId,
      playerName: row.playerName,
      market: row.market,
      selection: row.selection,
      line: row.line,
      enteredAmericanOdds: row.enteredAmericanOdds,
      enteredCounterpartOdds: row.enteredCounterpartOdds,
      enteredImpliedProbability: row.enteredImpliedProbability,
      breakEvenProbability: row.breakEvenProbability,
      book: row.book,
      capturedAtUtc: row.capturedAtUtc.toISOString(),
      snapshotHash: row.snapshotHash,
      entryHash: row.entryHash,
      modelVersion: row.modelVersion,
      modelCoverage: row.modelCoverage,
      modelProbability: row.modelProbability,
      modelUncertaintyLower: row.modelUncertaintyLower,
      modelUncertaintyUpper: row.modelUncertaintyUpper,
      priceAssessment: row.priceAssessment,
      wagerAmount: row.wagerAmount,
      duplicateOfLedgerId: row.duplicateOfLedgerId,
      correlationGroup: row.correlationGroup,
      correlationReason: row.correlationReason,
      createdAtUtc: row.createdAtUtc.toISOString(),
    },
    provenance,
    revisions,
    closingReference: row.closingReference
      ? {
          provider: row.closingReference.provider,
          capturedAtUtc: row.closingReference.capturedAtUtc?.toISOString() ?? null,
          overAmericanOdds: row.closingReference.overAmericanOdds,
          underAmericanOdds: row.closingReference.underAmericanOdds,
          americanOdds: row.closingReference.americanOdds,
          impliedProbability: row.closingReference.impliedProbability,
          fairProbability: row.closingReference.fairProbability,
          quality: row.closingReference.quality,
          secondSource: row.closingReference.secondSourceJson ? JSON.parse(row.closingReference.secondSourceJson) : null,
          independenceVerified: row.closingReference.independenceVerified,
          integrityHash: row.closingReference.integrityHash,
        }
      : null,
    settlement: row.settlement
      ? {
          status: row.settlement.status,
          result: row.settlement.result,
          reasonCode: row.settlement.reasonCode,
          actualValue: row.settlement.actualValue,
          source: row.settlement.source,
          settledAtUtc: row.settlement.settledAtUtc?.toISOString() ?? null,
        }
      : { status: 'pending', result: null, reasonCode: null, actualValue: null, source: null, settledAtUtc: null },
    grade: outcome,
    integrity,
    marketSnapshots: row.snapshots.map((s) => ({
      provider: s.provider,
      book: s.book,
      overAmericanOdds: s.overAmericanOdds,
      underAmericanOdds: s.underAmericanOdds,
      capturedAtUtc: s.capturedAtUtc.toISOString(),
      snapshotHash: s.snapshotHash,
    })),
  });
}
