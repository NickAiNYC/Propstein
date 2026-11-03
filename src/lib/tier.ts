// Propstein 2.0 — subscription tier resolution (Free / Pro gating)
//
// Production source of truth (single repo, Supabase Auth):
//   a signed Supabase session claim (user.subscription_tier, written by
//   the Stripe billing webhook). Until auth is configured, EVERY
//   production request resolves to free — a client-settable cookie must
//   never grant Pro.
//
// Preview/demo wiring:
//   the sidebar tier toggle flips a `propstein_tier` cookie via
//   POST /api/tier. Enabled only outside production, or in production
//   when ALLOW_TIER_DEMO=1 is explicitly set (e.g. a staging deploy).

import { cookies } from "next/headers";

export type Tier = "free" | "pro";

export const FREE_TEASER_ROWS = 3;
/** Free tier sees lines with a 15-minute publication delay. */
export const FREE_DELAY_MINUTES = 15;

/**
 * Self-serve tier switching is preview-only (audit fix 2026-11-03):
 * previously anyone could POST {"tier":"pro"} and elevate themselves.
 */
export const DEMO_TIER =
  process.env.NODE_ENV !== "production" || process.env.ALLOW_TIER_DEMO === "1";

export async function getTier(): Promise<Tier> {
  if (!DEMO_TIER) return "free";
  const jar = await cookies();
  return jar.get("propstein_tier")?.value === "pro" ? "pro" : "free";
}

export async function isPro(): Promise<boolean> {
  return (await getTier()) === "pro";
}
