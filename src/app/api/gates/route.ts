/**
 * GET /api/gates — gate monitor view for all sports.
 */

import { getGateStatuses } from '@/lib/server/gate-service';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  const statuses = await getGateStatuses();
  return ok({ statuses });
}
