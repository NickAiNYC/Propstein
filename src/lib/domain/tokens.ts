/**
 * PropStein — session tokens, revocation, rate limits, kill switches.
 *
 * Production mapping: Redis backs the jti revocation set, the sliding-window
 * rate counters, and the kill-switch cache. The reference deployment uses an
 * in-process store with the same interfaces (documented in the deployment
 * notes); entitlement verification is ALWAYS server-side.
 */

import { createHmac, randomUUID } from 'crypto';

const SECRET = process.env.PROPSTEIN_SESSION_SECRET ?? 'demo-hmac-secret-do-not-use-in-production';
const TOKEN_TTL_SECONDS = 15 * 60; // short-lived
export const DAILY_PUSH_CAP = 3;

export interface TokenClaims {
  sub: string;
  plan: 'free' | 'pro';
  iat: number;
  exp: number;
  jti: string;
  scope: string[]; // e.g. ['slips:write','ledger:write','record:read']
}

const b64url = (buf: Buffer | string) =>
  Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const b64urlDecode = (s: string) => Buffer.from(s.replace(/-/g, '+').replace(/_/g, '/'), 'base64');

function sign(data: string): string {
  return b64url(createHmac('sha256', SECRET).update(data).digest());
}

export function issueToken(
  sub: string,
  plan: 'free' | 'pro',
  scope: string[],
  nowEpoch = Math.floor(Date.now() / 1000),
): { token: string; claims: TokenClaims } {
  const claims: TokenClaims = {
    sub,
    plan,
    iat: nowEpoch,
    exp: nowEpoch + TOKEN_TTL_SECONDS,
    jti: randomUUID(),
    scope,
  };
  const body = b64url(JSON.stringify(claims));
  const sig = sign(body);
  return { token: `${body}.${sig}`, claims };
}

export function decodeToken(token: string): TokenClaims | null {
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const [body, sig] = parts;
  const expected = sign(body);
  // constant-time-ish compare
  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  if (diff !== 0) return null;
  try {
    const claims = JSON.parse(b64urlDecode(body).toString('utf8')) as TokenClaims;
    if (!claims.sub || !claims.exp || !claims.jti || !Array.isArray(claims.scope)) return null;
    return claims;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Revocation store (jti) — Redis in production
// ---------------------------------------------------------------------------

export interface RevocationStore {
  revoke(jti: string, expEpoch: number): void;
  isRevoked(jti: string): boolean;
}

class MemoryRevocationStore implements RevocationStore {
  private revoked = new Map<string, number>();
  revoke(jti: string, expEpoch: number): void {
    this.revoked.set(jti, expEpoch);
  }
  isRevoked(jti: string): boolean {
    const exp = this.revoked.get(jti);
    if (exp === undefined) return false;
    if (exp * 1000 < Date.now()) {
      this.revoked.delete(jti); // expired revocations need no storage
      return false;
    }
    return true;
  }
}

const globalForTokens = globalThis as unknown as { __pstRevocation?: RevocationStore };
export const revocationStore: RevocationStore = globalForTokens.__pstRevocation ?? new MemoryRevocationStore();
globalForTokens.__pstRevocation = revocationStore;

export function verifyToken(token: string, nowEpoch = Math.floor(Date.now() / 1000)):
  { ok: true; claims: TokenClaims } | { ok: false; reason: 'malformed' | 'expired' | 'revoked' } {
  const claims = decodeToken(token);
  if (!claims) return { ok: false, reason: 'malformed' };
  if (claims.exp <= nowEpoch) return { ok: false, reason: 'expired' };
  if (revocationStore.isRevoked(claims.jti)) return { ok: false, reason: 'revoked' };
  return { ok: true, claims };
}

// ---------------------------------------------------------------------------
// Sliding-window rate limiter — Redis in production
// ---------------------------------------------------------------------------

export interface RateLimiter {
  allow(key: string, limit: number, windowSeconds: number): { allowed: boolean; retryAfterSeconds: number };
}

class MemoryRateLimiter implements RateLimiter {
  private hits = new Map<string, number[]>();
  allow(key: string, limit: number, windowSeconds: number): { allowed: boolean; retryAfterSeconds: number } {
    const now = Date.now();
    const windowMs = windowSeconds * 1000;
    const list = (this.hits.get(key) ?? []).filter((t) => now - t < windowMs);
    if (list.length >= limit) {
      const retryAfter = Math.ceil((list[0] + windowMs - now) / 1000);
      this.hits.set(key, list);
      return { allowed: false, retryAfterSeconds: Math.max(1, retryAfter) };
    }
    list.push(now);
    this.hits.set(key, list);
    return { allowed: true, retryAfterSeconds: 0 };
  }
}

const globalForRate = globalThis as unknown as { __pstRate?: RateLimiter };
export const rateLimiter: RateLimiter = globalForRate.__pstRate ?? new MemoryRateLimiter();
globalForRate.__pstRate = rateLimiter;

// ---------------------------------------------------------------------------
// Kill switches
// ---------------------------------------------------------------------------

export type KillSwitch = 'extension' | 'market_intelligence';

const globalForKill = globalThis as unknown as { __pstKill?: Set<KillSwitch> };
const killSwitches: Set<KillSwitch> = globalForKill.__pstKill ?? new Set<KillSwitch>();
globalForKill.__pstKill = killSwitches;

export function setKillSwitch(name: KillSwitch, on: boolean): void {
  if (on) killSwitches.add(name);
  else killSwitches.delete(name);
}

export function killSwitchActive(name: KillSwitch): boolean {
  return killSwitches.has(name);
}

// ---------------------------------------------------------------------------
// Extension session policy (read-only posture)
// ---------------------------------------------------------------------------

/** The ONLY scopes an extension session may ever hold. */
export const EXTENSION_SCOPES = ['market.observe.readonly', 'ledger.append'] as const;

/** Scopes that must never be issuable to any client. */
export const FORBIDDEN_SCOPES = [
  'bet.place',
  'bet.prepare',
  'bet.submit',
  'credentials.read',
  'account.read',
  'balance.read',
] as const;

export function issueExtensionSession(sub: string, plan: 'free' | 'pro') {
  if (killSwitchActive('extension')) {
    return { ok: false as const, reason: 'KILL_SWITCH_ACTIVE' };
  }
  return { ok: true as const, ...issueToken(sub, plan, [...EXTENSION_SCOPES]) };
}
