/**
 * PropStein — deterministic primitives.
 *
 * Everything stochastic in the demo data plane is derived from these seeded
 * functions so that every stored number is reproducible from a snapshot, a
 * model version, a seed, and provenance (definition of done).
 */

import { createHash } from 'crypto';

/** FNV-1a 32-bit string hash. */
export function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Deterministic 32-bit seed from any tuple of strings. */
export function seedFrom(...parts: (string | number)[]): number {
  return fnv1a(parts.join('|'));
}

/** mulberry32 PRNG — small, fast, deterministic. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Standard normal draw from a uniform stream (Box–Muller). */
export function gauss(rand: () => number): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Standard normal CDF. */
export function normalCdf(x: number): number {
  // Abramowitz & Stegun 7.1.26 via erf approximation
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

/** Standard normal PDF. */
export function normalPdf(x: number): number {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}

function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-ax * ax);
  return sign * y;
}

/** SHA-256 hex digest. */
export function sha256hex(data: string): string {
  return createHash('sha256').update(data, 'utf8').digest('hex');
}

/**
 * Canonical JSON for hashing: sorted keys, no insignificant whitespace,
 * numbers serialized with fixed precision to avoid float drift.
 */
export function canonicalJson(value: unknown): string {
  const walk = (v: unknown): unknown => {
    if (v === null || v === undefined) return null;
    if (Array.isArray(v)) return v.map(walk);
    if (typeof v === 'object') {
      const entries = Object.entries(v as Record<string, unknown>)
        .filter(([, val]) => val !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
      const obj: Record<string, unknown> = {};
      for (const [k, val] of entries) obj[k] = walk(val);
      return obj;
    }
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) return v.toString();
      return Number(v.toFixed(6));
    }
    return v;
  };
  return JSON.stringify(walk(value));
}

/** Snapshot hash over a record. */
export function snapshotHash(record: unknown): string {
  return sha256hex(canonicalJson(record));
}

/** UUID v4 (for ledger ids) — random; the hash chain provides integrity. */
export function uuid(): string {
  return crypto.randomUUID();
}

/** ISO-8601 UTC timestamp. */
export function isoUtc(date: Date = new Date()): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/** Parse-or-null helper. */
export function parseIso(s: string): Date | null {
  const d = Date.parse(s);
  return Number.isFinite(d) ? new Date(d) : null;
}
