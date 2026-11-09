/**
 * GET /api/assessments/{id}
 */

import { loadAssessment } from '@/lib/server/assessment-service';
import { fail, ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const bundle = await loadAssessment(id);
  if (!bundle) return fail(404, 'NOT_FOUND', 'Assessment not found.');
  return ok({ bundle });
}
