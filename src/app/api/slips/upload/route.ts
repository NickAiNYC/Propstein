/**
 * POST /api/slips/upload
 *
 * Accepts either:
 *   - multipart/form-data: file (screenshot), retain ("true"|"false")
 *   - application/json: { text } (pasted slip text)
 *
 * Returns the extraction — fields + confidence + provider. NOTHING is
 * analyzed at this stage; analysis requires POST /api/slips/confirm.
 */

import { db } from '@/lib/db';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { extractSlipFromImage, parsePastedSlipText } from '@/lib/server/slip-parse';
import { fail, ok, rateLimited } from '@/lib/server/api';
import { isoUtc } from '@/lib/domain/determinism';
import { mkdir, writeFile } from 'fs/promises';
import { join } from 'path';

export const runtime = 'nodejs';

const MARKET_LABEL_TO_ID: [RegExp, string][] = [
  [/receiving/i, 'player_reception_yds'],
  [/rec\.?\s*yds/i, 'player_reception_yds'],
  [/passing/i, 'player_passing_yds'],
  [/rushing/i, 'player_rushing_yds'],
  [/points/i, 'player_points'],
  [/rebounds/i, 'player_rebounds'],
  [/assists/i, 'player_assists'],
  [/prize/i, 'fighter_prize_money'],
];

function marketIdFromLabel(label: string | null): string | null {
  if (!label) return null;
  const hit = MARKET_LABEL_TO_ID.find(([re]) => re.test(label));
  return hit ? hit[1] : null;
}

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();

  const rl = rateLimited(req, 'slips:upload', 12, 60);
  if (rl.limited) {
    return fail(429, 'RATE_LIMITED', 'Too many uploads. Try again shortly.', { retryAfterSeconds: rl.retryAfterSeconds });
  }

  const contentType = req.headers.get('content-type') ?? '';
  let extraction;
  let sourceType: 'screenshot_upload' | 'manual_entry' = 'screenshot_upload';
  let retained = false;
  let rawCaptureRef: string | null = null;

  try {
    if (contentType.includes('multipart/form-data')) {
      const form = await req.formData();
      const file = form.get('file');
      const retain = String(form.get('retain') ?? 'false') === 'true';
      if (!(file instanceof File)) {
        return fail(400, 'NO_FILE', 'Expected a screenshot file under the "file" field.');
      }
      if (file.size > 8 * 1024 * 1024) {
        return fail(413, 'FILE_TOO_LARGE', 'Screenshot exceeds 8 MB.');
      }
      const buf = Buffer.from(await file.arrayBuffer());
      const mime = file.type || 'image/png';
      extraction = await extractSlipFromImage(buf.toString('base64'), mime);
      retained = retain;
      if (retain) {
        // Object-storage stand-in: local storage folder (production: S3/GCS bucket).
        const dir = join(process.cwd(), 'storage', 'screenshots');
        await mkdir(dir, { recursive: true });
        const key = `slip-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        await writeFile(join(dir, key), buf);
        rawCaptureRef = key;
      }
    } else {
      const body = await req.json().catch(() => null);
      const text = body && typeof body.text === 'string' ? body.text : null;
      if (!text || text.trim().length < 3) {
        return fail(400, 'NO_TEXT', 'Expected {"text": "<pasted slip text>"}.');
      }
      extraction = parsePastedSlipText(text);
      sourceType = 'manual_entry';
    }
  } catch {
    return fail(400, 'UPLOAD_FAILED', 'The upload could not be processed. Nothing was analyzed.');
  }

  // Normalize market label -> market id for downstream confirm.
  const fields = { ...extraction.fields };
  if (!fields.market && fields.marketLabel) {
    fields.market = marketIdFromLabel(fields.marketLabel);
  }

  const row = await db.slipUpload.create({
    data: {
      userId: user.id,
      sourceType,
      rawCaptureRef,
      ocrProvider: extraction.provider,
      ocrConfidence: extraction.confidence,
      extractedJson: JSON.stringify(fields),
      retained,
    },
  });

  await audit(requestId, user.id, 'SLIP_UPLOAD', 'SlipUpload', row.id, {
    provider: extraction.provider,
    confidence: extraction.confidence,
    retained,
  });

  return ok({
    slipUploadId: row.id,
    sourceType,
    provider: extraction.provider,
    confidence: extraction.confidence,
    fieldConfidence: extraction.fieldConfidence,
    needsManualConfirmation: extraction.needsManualConfirmation,
    ocrThreshold: 0.75,
    fields,
    retained,
    createdAtUtc: isoUtc(),
  });
}
