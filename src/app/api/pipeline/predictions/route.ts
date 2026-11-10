/**
 * PropStein — daily predictions board endpoint (fail closed).
 *
 * Streams the schema-validated data/latest_predictions.json produced by the
 * daily pipeline (see docs/ARCHITECTURE.md). The web layer never recomputes
 * model numbers: it serves the stored artifact. Missing/corrupt store ->
 * explicit unavailable state; the board renders an error boundary state,
 * never a fabricated board.
 */

import { readFile, stat } from 'fs/promises';
import path from 'path';
import { NextResponse } from 'next/server';
import { clientIp, fail, ok, rateLimited } from '@/lib/server/api';

export const dynamic = 'force-dynamic';

const LATEST_PATH = path.join(process.cwd(), 'data', 'latest_predictions.json');

/** Structural guards before serving (cheap, server-side). */
function sanityCheck(doc: Record<string, unknown>): string | null {
  if (!doc || typeof doc !== 'object') return 'artifact is not an object';
  const preds = doc.predictions;
  if (!Array.isArray(preds) || preds.length === 0) return 'predictions missing or empty';
  if (typeof doc.run_date !== 'string') return 'run_date missing';
  if (typeof doc.integrity_hash !== 'string' || doc.integrity_hash.length !== 64) {
    return 'integrity hash missing';
  }
  return null;
}

export async function GET(req: Request) {
  const limited = rateLimited(req, 'pipeline:predictions', 30, 60);
  if (limited.limited) {
    return fail(429, 'RATE_LIMITED', 'Too many board requests; retry shortly.', {
      retryAfterSeconds: limited.retryAfterSeconds,
    });
  }
  void clientIp;

  try {
    const [raw, stats] = await Promise.all([readFile(LATEST_PATH, 'utf8'), stat(LATEST_PATH)]);
    const doc = JSON.parse(raw) as Record<string, unknown>;
    const problem = sanityCheck(doc);
    if (problem) {
      return fail(503, 'PIPELINE_OUTPUT_INVALID', `The stored board artifact failed sanity checks (${problem}).`);
    }
    return ok({ predictions: doc }, {
      headers: {
        'Cache-Control': 'no-store',
        'X-Pipeline-Artifact-Size': String(stats.size),
      },
    });
  } catch {
    return fail(
      503,
      'PIPELINE_OUTPUT_UNAVAILABLE',
      'The daily model run artifact is not available on this deployment. The board fails closed rather than showing assumed numbers.',
    );
  }
}

export function OPTIONS() {
  return NextResponse.json({}, { allow: 'GET, OPTIONS' });
}
