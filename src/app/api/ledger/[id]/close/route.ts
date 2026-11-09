/**
 * POST /api/ledger/{id}/close — capture the closing reference.
 *
 * In production this is a background worker action keyed on the pricing
 * cutoff; the reference deployment exposes it explicitly for the demo loop.
 * Quality states: fresh | stale | missing | conflicting. Missing/stale/
 * conflicting closes make the entry UNEVALUABLE with a reason code — never
 * a silent zero.
 */

import { captureClosingReference } from '@/lib/server/ledger-service';
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

  const body = await readJson<{ scenario?: string }>(req);
  const scenario =
    body?.scenario && ['none', 'stale_close', 'conflicting_close', 'missing_close'].includes(body.scenario)
      ? (body.scenario as 'none' | 'stale_close' | 'conflicting_close' | 'missing_close')
      : 'none';

  try {
    const result = await captureClosingReference(id, scenario);
    await audit(requestId, user.id, 'CLOSE_CAPTURE', 'LedgerEntry', id, { quality: result.quality });
    return ok({
      quality: result.quality,
      note:
        result.quality === 'fresh'
          ? 'Closing reference captured and independent of the model input feed.'
          : 'Closing reference retained with an explicit quality state; the entry becomes UNEVALUABLE for CLV with this reason code.',
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'unknown';
    return fail(400, 'CLOSE_FAILED', msg);
  }
}
