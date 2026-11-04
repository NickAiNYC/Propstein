/**
 * GET /api/ledger — list entries for the session user (filters: sport, status).
 */

import { db } from '@/lib/db';
import { getSessionUser } from '@/lib/server/session';
import { entryView } from '@/lib/server/ledger-service';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET(req: Request) {
  const user = await getSessionUser();
  const url = new URL(req.url);
  const sport = url.searchParams.get('sport');
  const status = url.searchParams.get('status');

  const rows = await db.ledgerEntry.findMany({
    where: {
      userId: user.id,
      ...(sport ? { sport } : {}),
      ...(status ? { settlement: { status } } : {}),
    },
    include: { settlement: true, closingReference: true },
    orderBy: { createdAtUtc: 'desc' },
    take: 200,
  });

  return ok({
    entries: rows.map((r) => entryView(r)),
    counts: {
      total: rows.length,
      settled: rows.filter((r) => r.settlement?.status === 'settled').length,
      pending: rows.filter((r) => !r.settlement || r.settlement.status === 'pending').length,
      excluded: rows.filter((r) => ['push', 'void', 'canceled', 'dnp'].includes(r.settlement?.status ?? '')).length,
    },
  });
}
