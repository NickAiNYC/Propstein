/**
 * POST /api/slips/upload
 *
 * Two extraction paths feed the SAME confirmation screen:
 *   1. paste text   — JSON body { text }  -> paste-parser-v1 (deterministic)
 *   2. screenshot   — multipart FormData (file, retain) -> vlm-extract-v1
 *                     (vision extraction, DATA EXTRACTION ONLY — the model
 *                     never computes probabilities or assessments; charter
 *                     rule 9)
 *
 * NOTHING is analyzed here: extraction results are returned for explicit
 * user confirmation (/api/slips/confirm). Screenshot bytes are stored only
 * when retention is opted in (rawCaptureRef); otherwise only the extracted
 * fields persist. Low-confidence extractions force manual confirmation.
 *
 * Fail closed: any failure returns an explicit error envelope — the UI never
 * invents fields.
 */

import { mkdir, writeFile } from 'fs/promises';
import path from 'path';
import { db } from '@/lib/db';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { fail, ok, rateLimited } from '@/lib/server/api';
import { extractSlipFromImage, parsePastedSlipText } from '@/lib/server/slip-parse';

export const runtime = 'nodejs';

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const ALLOWED_MIME = new Set(['image/png', 'image/jpeg', 'image/webp']);
const CAPTURE_DIR = path.join(process.cwd(), 'db', 'slip-captures');

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();

  const rl = rateLimited(req, 'slips:upload', 10, 60);
  if (rl.limited) {
    return fail(429, 'RATE_LIMITED', 'Too many upload attempts. Try again shortly.', { retryAfterSeconds: rl.retryAfterSeconds });
  }

  const contentType = req.headers.get('content-type') ?? '';

  // ------------------------------------------------------------------ paste
  if (contentType.includes('application/json')) {
    let body: { text?: unknown };
    try {
      body = (await req.json()) as { text?: unknown };
    } catch {
      return fail(400, 'BAD_JSON', 'Expected a JSON body with a text field.');
    }
    const text = typeof body.text === 'string' ? body.text : '';
    if (text.trim().length < 8) {
      return fail(400, 'NO_TEXT', 'Slip text is empty or too short to parse. Nothing was analyzed.');
    }

    const extraction = parsePastedSlipText(text);

    const record = await db.slipUpload.create({
      data: {
        userId: user.id,
        sourceType: 'manual_entry',
        ocrProvider: extraction.provider,
        ocrConfidence: extraction.confidence,
        extractedJson: JSON.stringify({
          provider: extraction.provider,
          confidence: extraction.confidence,
          fieldConfidence: extraction.fieldConfidence,
          fields: extraction.fields,
          needsManualConfirmation: extraction.needsManualConfirmation,
        }),
        retained: false,
      },
    });

    await audit(requestId, user.id, 'SLIP_UPLOAD', 'SlipUpload', record.id, {
      provider: extraction.provider,
      confidence: extraction.confidence,
      needsManualConfirmation: extraction.needsManualConfirmation,
    });

    return ok({
      slipUploadId: record.id,
      provider: extraction.provider,
      confidence: extraction.confidence,
      fieldConfidence: extraction.fieldConfidence,
      needsManualConfirmation: extraction.needsManualConfirmation,
      fields: extraction.fields,
    });
  }

  // ------------------------------------------------------------- screenshot
  if (!contentType.includes('multipart/form-data')) {
    return fail(400, 'BAD_CONTENT_TYPE', 'Expected JSON (paste text) or multipart/form-data (screenshot).');
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return fail(400, 'BAD_FORM', 'The upload form could not be read.');
  }

  const file = form.get('file');
  if (!(file instanceof File)) {
    return fail(400, 'NO_FILE', 'No screenshot file was received. Nothing was analyzed.');
  }
  if (!ALLOWED_MIME.has(file.type)) {
    return fail(415, 'BAD_FILE_TYPE', 'Screenshots must be PNG, JPEG, or WebP. Nothing was analyzed.');
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return fail(413, 'FILE_TOO_LARGE', 'Screenshots must be under 5 MB. Nothing was analyzed.');
  }

  const retain = String(form.get('retain') ?? 'false') === 'true';

  const bytes = Buffer.from(await file.arrayBuffer());
  const base64 = bytes.toString('base64');
  const extraction = await extractSlipFromImage(base64, file.type);

  // Optional retention: store the capture only when the user opted in.
  let rawCaptureRef: string | null = null;
  if (retain) {
    try {
      await mkdir(CAPTURE_DIR, { recursive: true });
      const ext = file.type === 'image/png' ? 'png' : file.type === 'image/webp' ? 'webp' : 'jpg';
      const key = `slip-captures/${user.id}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}.${ext}`;
      await writeFile(path.join('db', key), bytes);
      rawCaptureRef = key;
    } catch {
      rawCaptureRef = null; // retention failed -> record stays, capture does not
    }
  }

  const record = await db.slipUpload.create({
    data: {
      userId: user.id,
      sourceType: 'screenshot_upload',
      ocrProvider: extraction.provider,
      ocrConfidence: extraction.confidence,
      extractedJson: JSON.stringify({
        provider: extraction.provider,
        confidence: extraction.confidence,
        fieldConfidence: extraction.fieldConfidence,
        fields: extraction.fields,
        needsManualConfirmation: extraction.needsManualConfirmation,
      }),
      rawCaptureRef,
      retained: retain && rawCaptureRef !== null,
    },
  });

  await audit(requestId, user.id, 'SLIP_UPLOAD', 'SlipUpload', record.id, {
    provider: extraction.provider,
    confidence: extraction.confidence,
    retained: retain && rawCaptureRef !== null,
    needsManualConfirmation: extraction.needsManualConfirmation,
  });

  return ok({
    slipUploadId: record.id,
    provider: extraction.provider,
    confidence: extraction.confidence,
    fieldConfidence: extraction.fieldConfidence,
    needsManualConfirmation: extraction.needsManualConfirmation,
    fields: extraction.fields,
    retained: record.retained,
  });
}
