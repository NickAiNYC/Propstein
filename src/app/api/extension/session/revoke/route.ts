/**
 * POST /api/extension/session/revoke
 */

import { db } from '@/lib/db';
import { revocationStore, decodeToken } from '@/lib/domain/tokens';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { fail, ok, readJson } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST(req: Request) {
  const user = await getSessionUser();
  const requestId = newRequestId();
  const body = await readJson<{ token?: string; jti?: string }>(req);

  let jti = body?.jti ?? null;
  if (!jti && body?.token) {
    const claims = decodeToken(body.token);
    jti = claims?.jti ?? null;
  }
  if (!jti) return fail(400, 'TOKEN_REQUIRED', 'Expected { token } or { jti }.');

  const row = await db.sessionToken.findUnique({ where: { jti } });
  if (!row || row.userId !== user.id) return fail(404, 'NOT_FOUND', 'Session not found.');

  const exp = row.expiresAtUtc.getTime() / 1000;
  revocationStore.revoke(jti, exp);
  await db.sessionToken.update({ where: { jti }, data: { revokedAtUtc: new Date() } });
  await audit(requestId, user.id, 'EXTENSION_SESSION_REVOKED', 'SessionToken', jti, {});

  return ok({ revoked: true, jti });
}
