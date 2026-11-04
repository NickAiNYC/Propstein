/**
 * GET /api/records/luck-meter
 */

import { getLuckMeter } from '@/lib/server/record-service';
import { getSessionUser } from '@/lib/server/session';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  const user = await getSessionUser();
  const report = await getLuckMeter(user.id);
  return ok({ report });
}
