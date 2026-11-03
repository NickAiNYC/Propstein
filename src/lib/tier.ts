// Propstein 2.0 — subscription tier resolution (Free / Pro gating)
//
// Production wiring (single repo, Supabase Auth):
//   `session.user.isPro` mirrors a `subscription_tier` claim set by the
//   Stripe billing webhook. Configure SUPABASE_URL + SUPABASE_ANON_KEY and
//   the /api/auth route exchanges the Supabase session for the tier cookie.
//
// Sandbox/preview wiring:
//   a `propstein_tier` cookie is flipped by the tier toggle in the sidebar.
//   Default tier: free — exactly what an anonymous visitor sees.

import { cookies } from "next/headers";

export type Tier = "free" | "pro";

export const FREE_TEASER_ROWS = 3;
/** Free tier sees lines with a 15-minute publication delay. */
export const FREE_DELAY_MINUTES = 15;

export async function getTier(): Promise<Tier> {
  const jar = await cookies();
  return jar.get("propstein_tier")?.value === "pro" ? "pro" : "free";
}

export async function isPro(): Promise<boolean> {
  return (await getTier()) === "pro";
}
