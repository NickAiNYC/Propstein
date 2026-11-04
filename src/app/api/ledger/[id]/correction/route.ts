/**
 * POST /api/ledger/{id}/correction — append a revision.
 *
 * The entry itself is immutable: this appends a revision with reason, actor,
 * timestamp, prior hash, and new hash. Forbidden fields (ledgerId, entryHash,
 * createdAtUtc, snapshotHash) are rejected.
 */

import { appendCorrection } from '@/lib/server/ledger-service';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { db } from '@/lib/db';
import { fail, ok, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getSessionUser();
  const requestId = newRequestId();

  const row = await db.ledgerEntry.findUnique({ where: { ledgerId: id } });
  if (!row || row.userId !== user.id) return fail(404, 'NOT_FOUND', 'Ledger entry not found.');

  const body = await readJson<{ reasonCode?: string; reasonText?: string; changedFields?: Record<string, unknown> }>(req);
  if (!body?.reasonCode || !body.reasonText || !body.changedFields) {
    return fail(400, 'CORRECTION_INCOMPLETE', 'Expected { reasonCode, reasonText, changedFields }.');
  }
  if (Object.keys(body.changedFields).length === 0) {
    return fail(400, 'CORRECTION_EMPTY', 'A revision must change at least one field.');
  }

  try {
    const revision = await appendCorrection(id, body.reasonCode, body.reasonText, user.id, body.changedFields);
    await audit(requestId, user.id, 'REVISION_APPEND', 'LedgerEntry', id, {
      revisionNo: revision.revisionNo,
      reasonCode: body.reasonCode,
    });
    return ok({ revision }, { status: 201 });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'unknown';
    if (msg.includes('FORBIDDEN_FIELD')) return fail(400, 'CORRECTION_FORBIDDEN_FIELD', msg);
    if (msg.includes('REASON_REQUIRED')) return fail(400, 'CORRECTION_REASON_REQUIRED', msg);
    return fail(400, 'CORRECTION_FAILED', msg);
  }
}
