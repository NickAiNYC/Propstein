/**
 * POST /api/ledger/entries
 *
 * Body: { assessmentId: string, wagerAmount?: number | null }
 *
 * Persists the immutable ledger entry from a confirmed assessment. There is
 * deliberately no PUT/PATCH route for entries anywhere in this API.
 */

import { db } from '@/lib/db';
import { loadAssessment } from '@/lib/server/assessment-service';
import { saveLedgerEntryFromAssessment } from '@/lib/server/ledger-service';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { fail, ok, rateLimited, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();

  const rl = rateLimited(req, 'ledger:entries', 30, 60);
  if (rl.limited) {
    return fail(429, 'RATE_LIMITED', 'Rate limit reached. Try again shortly.', { retryAfterSeconds: rl.retryAfterSeconds });
  }

  const body = await readJson<{ assessmentId?: string; wagerAmount?: number | null }>(req);
  if (!body?.assessmentId) return fail(400, 'ASSESSMENT_REQUIRED', 'Expected { assessmentId }.');

  const bundle = await loadAssessment(body.assessmentId);
  if (!bundle) return fail(404, 'ASSESSMENT_NOT_FOUND', 'No assessment with that id.');
  if (bundle.scenario === 'model_outage') {
    // Fail closed: a model-outage assessment cannot be saved with model numbers.
    return fail(503, 'MODEL_UNAVAILABLE', 'The model surface is unavailable; the assessment failed closed and cannot be saved.');
  }

  const existing = await db.ledgerEntry.findFirst({ where: { assessmentId: body.assessmentId } });
  if (existing) {
    return fail(409, 'ALREADY_SAVED', 'This assessment already has a ledger entry (append-only).', {
      ledgerId: existing.ledgerId,
    });
  }

  // Source type follows the bound slip upload when present.
  let sourceType: 'manual_entry' | 'screenshot_upload' | 'extension_observation' = 'manual_entry';
  if (bundle.slipUploadId) {
    const slipRow = await db.slipUpload.findUnique({ where: { id: bundle.slipUploadId } });
    if (slipRow) {
      sourceType = slipRow.sourceType as typeof sourceType;
    }
  }

  const result = await saveLedgerEntryFromAssessment({
    userId: user.id,
    bundle,
    sourceType,
    slipUploadId: bundle.slipUploadId ?? null,
    wagerAmount: body.wagerAmount ?? bundle.slip.wagerAmount ?? null,
  });

  await audit(requestId, user.id, 'LEDGER_APPEND', 'LedgerEntry', result.ledgerId, {
    assessment: bundle.hurdle.assessment,
    duplicate: Boolean(result.duplicateOfLedgerId),
    correlated: Boolean(result.correlationGroup),
  });

  return ok(
    {
      ledgerId: result.ledgerId,
      duplicateOfLedgerId: result.duplicateOfLedgerId,
      correlationGroup: result.correlationGroup,
      note: 'Append-only record created. Corrections require a revision with a reason and integrity hash.',
    },
    { status: 201 },
  );
}
