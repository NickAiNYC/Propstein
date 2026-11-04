/**
 * POST /api/alerts/preferences — opt-in by alert type.
 */

import { getPreferences, setPreferences } from '@/lib/server/alerts-service';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { fail, ok, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  const user = await getSessionUser();
  const prefs = await getPreferences(user.id);
  return ok({ preferences: prefs, dailyPushCap: 3 });
}

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();
  const body = await readJson<{ enabled?: Record<string, boolean> }>(req);
  if (!body?.enabled || typeof body.enabled !== 'object') {
    return fail(400, 'BAD_REQUEST', 'Expected { enabled: { <alertType>: boolean } }.');
  }
  const prefs = await setPreferences(user.id, body.enabled);
  await audit(requestId, user.id, 'ALERT_PREFS', 'User', user.id, { types: Object.keys(body.enabled).length });
  return ok({ preferences: prefs, dailyPushCap: 3 });
}
