/**
 * POST /api/alerts/evaluate — run the alert evaluation worker on demand
 * (production: background worker). Respects preferences, mutes, the daily
 * push cap, and the freshness gate (STALE QUOTE or suppression).
 */

import { evaluateAlerts, getFeed } from '@/lib/server/alerts-service';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST() {
  const user = await getSessionUser();
  const requestId = newRequestId();
  const result = await evaluateAlerts(user.id);
  await audit(requestId, user.id, 'ALERT_EVALUATE', 'User', user.id, {
    created: result.created,
    suppressed: result.suppressed.length,
  });
  const feed = await getFeed(user.id);
  return ok({ created: result.created, suppressed: result.suppressed, feed });
}
