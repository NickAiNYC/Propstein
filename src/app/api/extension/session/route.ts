/**
 * POST /api/extension/session
 *
 * Issues a short-lived, read-only extension session token. Scopes are fixed
 * to market.observe.readonly + ledger.append; bet placement / credential
 * scopes are not issuable by design. Kill switch active -> explicit refusal.
 */

import { issueExtensionSession, EXTENSION_SCOPES, killSwitchActive } from '@/lib/domain/tokens';
import { db } from '@/lib/db';
import { getSessionUser, audit, newRequestId } from '@/lib/server/session';
import { fail, ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function POST() {
  const user = await getSessionUser();
  const requestId = newRequestId();

  if (killSwitchActive('extension')) {
    await audit(requestId, user.id, 'EXTENSION_SESSION_DENIED', 'User', user.id, { reason: 'KILL_SWITCH_ACTIVE' });
    return fail(503, 'KILL_SWITCH_ACTIVE', 'The extension surface is disabled by a kill switch. The state is explicit, not silent.');
  }

  const issued = issueExtensionSession(user.id, user.plan);
  if (!issued.ok) {
    return fail(503, 'KILL_SWITCH_ACTIVE', 'The extension surface is disabled by a kill switch.');
  }

  await db.sessionToken.create({
    data: {
      jti: issued.claims.jti,
      userId: user.id,
      kind: 'extension',
      scopes: issued.claims.scope.join(' '),
      expiresAtUtc: new Date(issued.claims.exp * 1000),
    },
  });

  await audit(requestId, user.id, 'EXTENSION_SESSION_ISSUED', 'SessionToken', issued.claims.jti, {
    scopes: issued.claims.scope,
  });

  return ok({
    token: issued.token,
    claims: issued.claims,
    posture: {
      readOnly: true,
      scopes: EXTENSION_SCOPES,
      betPlacement: 'not supported by design',
      credentialCollection: 'not supported by design',
      antiBotBypass: 'not supported by design',
      observationOnly: 'visible-market quotes only',
      perOriginPermissions: 'opt-in per origin',
      adapterVersioning: 'versioned adapters with selector-drift monitoring',
    },
  });
}
