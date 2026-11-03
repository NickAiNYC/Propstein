import { NextRequest, NextResponse } from "next/server";
import { getTier, DEMO_TIER } from "@/lib/tier";

export const dynamic = "force-dynamic";

// GET /api/tier — current tier + whether the preview demo switch is on.
// Audit fix 2026-11-03: the previous version listed up to 10 account
// email addresses from the user table — removed. This route returns
// tier state only, never account data.
export async function GET() {
  return NextResponse.json({ tier: await getTier(), demoTier: DEMO_TIER });
}

// POST /api/tier  { tier: "free" | "pro" }
// Preview-only demo switch. Returns 403 in production unless
// ALLOW_TIER_DEMO=1 — audit fix 2026-11-03: self-elevating to Pro via a
// public endpoint bypassed the paywall. Production tier comes from the
// Supabase session claim (billing webhook -> user.subscription_tier).
export async function POST(req: NextRequest) {
  if (!DEMO_TIER) {
    return NextResponse.json(
      { error: "tier switching is not available — sign in with a Pro account" },
      { status: 403 },
    );
  }
  const body = await req.json().catch(() => null);
  const tier = body?.tier === "pro" ? "pro" : "free";
  const res = NextResponse.json({ tier });
  res.cookies.set("propstein_tier", tier, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
