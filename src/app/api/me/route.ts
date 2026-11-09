/**
 * GET /api/me — session info for the app shell (pseudonym, plan).
 */

import { getSessionUser } from '@/lib/server/session';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  const user = await getSessionUser();
  return ok({ user });
}
