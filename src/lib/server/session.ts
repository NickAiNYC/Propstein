/**
 * PropStein — server session & audit helpers.
 *
 * Web sessions are pseudonymous by construction: the terminal provisions a
 * random pseudonym (e.g. PS-7F3K9) on first use. No sportsbook credentials,
 * cookies, balances, or account data are ever accepted or stored by any
 * surface in this codebase.
 */

import { cookies } from 'next/headers';
import { db } from '@/lib/db';
import { issueToken, verifyToken, revocationStore } from '@/lib/domain/tokens';
import { randomUUID } from 'crypto';

export const SESSION_COOKIE = 'pst_sess';

export interface SessionUser {
  id: string;
  pseudonym: string;
  plan: 'free' | 'pro';
}

function randomPseudonym(): string {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  let s = '';
  for (let i = 0; i < 5; i++) s += alphabet[Math.floor(Math.random() * alphabet.length)];
  return `PS-${s}`;
}

const DEMO_PSEUDONYM = 'PS-DEMO1';

/** Get the session user, attaching to the seeded demo identity when present
 * (single-user reference deployment). Production uses real authentication. */
export async function getSessionUser(): Promise<SessionUser> {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (token) {
    const v = verifyToken(token);
    if (v.ok) {
      const user = await db.user.findUnique({ where: { id: v.claims.sub } });
      if (user) {
        return { id: user.id, pseudonym: user.pseudonym, plan: (user.plan as 'free' | 'pro') ?? 'pro' };
      }
    }
  }
  // Reference deployment: attach to the seeded demo user if present.
  const demo = await db.user.findUnique({ where: { pseudonym: DEMO_PSEUDONYM } });
  const user = demo ?? (await db.user.create({ data: { pseudonym: randomPseudonym(), plan: 'pro' } }));
  const { token: newToken, claims } = issueToken(user.id, (user.plan as 'free' | 'pro') ?? 'pro', ['slips:write', 'ledger:write', 'record:read', 'alerts:write']);
  jar.set(SESSION_COOKIE, newToken, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60,
  });
  const existingSession = await db.sessionToken.findUnique({ where: { jti: claims.jti } });
  if (!existingSession) {
    await db.sessionToken.create({
      data: {
        jti: claims.jti,
        userId: user.id,
        kind: 'web',
        scopes: claims.scope.join(' '),
        expiresAtUtc: new Date(claims.exp * 1000),
      },
    });
  }
  return { id: user.id, pseudonym: user.pseudonym, plan: (user.plan as 'free' | 'pro') ?? 'pro' };
}

/** Revoke the current web session (logout). */
export async function revokeCurrentSession(): Promise<boolean> {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (!token) return false;
  const v = verifyToken(token);
  if (!v.ok) return false;
  revocationStore.revoke(v.claims.jti, v.claims.exp);
  await db.sessionToken.updateMany({
    where: { jti: v.claims.jti },
    data: { revokedAtUtc: new Date() },
  });
  jar.delete(SESSION_COOKIE);
  return true;
}

// ---------------------------------------------------------------------------
// Structured logging with request id
// ---------------------------------------------------------------------------

export function newRequestId(): string {
  return randomUUID().slice(0, 8);
}

export async function audit(
  requestId: string,
  actorId: string,
  action: string,
  targetType: string,
  targetId: string | null,
  metadata: Record<string, unknown> = {},
): Promise<void> {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    requestId,
    actor: actorId,
    action,
    targetType,
    targetId,
    ...metadata,
  });
  console.log(`[audit] ${line}`);
  try {
    await db.auditEvent.create({
      data: {
        actorId,
        action,
        targetType,
        targetId,
        requestId,
        metadataJson: JSON.stringify(metadata),
      },
    });
  } catch {
    // Audit persistence failure must not break the request; the log line above stands.
  }
}

// ---------------------------------------------------------------------------
// Entitlement verification (server-side only)
// ---------------------------------------------------------------------------

export async function hasEntitlement(
  userId: string,
  surface: string,
  scope: string,
): Promise<boolean> {
  const rows = await db.entitlement.findMany({ where: { userId, surface } });
  const now = Date.now();
  return rows.some(
    (r) =>
      (r.scope === scope || r.scope === '*') &&
      r.status === 'active' &&
      (r.expiresAtUtc === null || r.expiresAtUtc.getTime() > now),
  );
}
