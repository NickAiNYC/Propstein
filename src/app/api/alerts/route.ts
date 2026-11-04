/**
 * GET /api/alerts — the alert feed for the session user.
 */

import { getFeed } from '@/lib/server/alerts-service';
import { getSessionUser } from '@/lib/server/session';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  const user = await getSessionUser();
  const feed = await getFeed(user.id);
  return ok({ feed, dailyPushCap: 3 });
}
