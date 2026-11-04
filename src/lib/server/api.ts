/**
 * PropStein — API helpers: fail-closed JSON envelopes, rate limiting.
 */

import { NextResponse } from 'next/server';
import { rateLimiter } from '@/lib/domain/tokens';

export function ok<T>(data: T, init?: ResponseInit): NextResponse {
  return NextResponse.json({ ok: true, ...data }, init);
}

export function fail(
  status: number,
  code: string,
  detail: string,
  extra: Record<string, unknown> = {},
): NextResponse {
  return NextResponse.json({ ok: false, code, detail, ...extra }, { status });
}

export function clientIp(req: Request): string {
  return req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'local';
}

/** Sliding-window rate limit gate. */
export function rateLimited(
  req: Request,
  key: string,
  limit: number,
  windowSeconds: number,
): { limited: false } | { limited: true; retryAfterSeconds: number } {
  const decision = rateLimiter.allow(`${key}:${clientIp(req)}`, limit, windowSeconds);
  if (decision.allowed) return { limited: false };
  return { limited: true, retryAfterSeconds: decision.retryAfterSeconds };
}

export async function readJson<T>(req: Request): Promise<T | null> {
  try {
    return (await req.json()) as T;
  } catch {
    return null;
  }
}
