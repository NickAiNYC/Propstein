/**
 * GET /api/copy-compliance — lint report over the product copy registry.
 * The report is part of the product surface: transparency about language
 * standards is a feature.
 */

import { lintCopyBatch } from '@/lib/domain/copy-lint';
import { COPY } from '@/lib/domain/copy';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

function flatten(prefix: string, obj: unknown, out: { id: string; text: string }[]): void {
  if (typeof obj === 'string') {
    out.push({ id: prefix, text: obj });
    return;
  }
  if (typeof obj === 'function') {
    // template functions: sample their output
    try {
      const produced = (obj as (...a: string[]) => string)('1.0', '9');
      out.push({ id: prefix, text: produced });
    } catch {
      /* skip */
    }
    return;
  }
  if (obj && typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      flatten(`${prefix}.${k}`, v, out);
    }
  }
}

export async function GET() {
  const items: { id: string; text: string }[] = [];
  flatten('copy', COPY, items);
  const violations = lintCopyBatch(items);
  return ok({
    scannedStrings: items.length,
    violations,
    status: violations.length === 0 ? 'COMPLIANT' : 'VIOLATIONS FOUND',
    checkedAtUtc: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  });
}
