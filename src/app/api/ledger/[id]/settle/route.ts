/**
 * POST /api/ledger/{id}/settle — settle and grade.
 *
 * Settlement statuses: settled | push | void | canceled | dnp. Pushes, voids,
 * cancellations and DNPs are retained with reason codes and excluded from
 * CLV — never counted as losses or zeros.
 */

import { settleLedgerEntry } from '@/lib/server/ledger-service';
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
    body?.scenario && ['none', 'push', 'void', 'canceled', 'dnp'].includes(body.scenario)
      ? (body.scenario as 'none' | 'push' | 'void' | 'canceled' | 'dnp')
      : 'none';

  try {
    const result = await settleLedgerEntry(id, scenario);
    await audit(requestId, user.id, 'SETTLE_GRADE', 'LedgerEntry', id, {
      status: result.status,
      evaluable: result.evaluable,
      reasonCode: result.reasonCode,
    });
    return ok({
      ...result,
      note: result.evaluable
        ? 'Entry graded. CLV recorded from de-vigged entry and closing fair probabilities.'
        : 'Entry retained with an explicit reason code and excluded from CLV. It is never counted as a loss or a zero.',
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'unknown';
    return fail(400, 'SETTLE_FAILED', msg);
  }
}
