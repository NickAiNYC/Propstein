/**
 * POST /api/gates/recompute — recompute an attempt from stored signals with
 * the preregistered seed. Deterministic: the same stored set always produces
 * the same verdict. This is the reproducibility guarantee made visible.
 */

import { recomputeAttempt } from '@/lib/server/gate-service';
import { fail, ok, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST(req: Request) {
  const body = await readJson<{ sport?: string; attemptNo?: number }>(req);
  const sport = body?.sport ?? 'NFL';
  const attemptNo = body?.attemptNo ?? 1;
  if (!['NFL', 'NBA', 'UFC'].includes(sport)) {
    return fail(400, 'SPORT_INVALID', 'Expected sport NFL, NBA, or UFC.');
  }
  const result = await recomputeAttempt(sport, attemptNo);
  return ok({
    ...result,
    note: 'Recomputed from stored signals with the preregistered seed 20261024. Identical inputs always produce an identical verdict.',
  });
}
