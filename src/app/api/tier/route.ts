import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

// POST /api/tier  { tier: "free" | "pro" }
// Sandbox/preview tier switch (sets the propstein_tier cookie).
// In production this route is replaced by the Supabase auth callback +
// Stripe billing webhook that writes `user.subscription_tier` -> `isPro`.
export async function POST(req: NextRequest) {
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

export async function GET() {
  const users = await db.user
    .findMany({ take: 10, select: { email: true, isPro: true, subscriptionTier: true } })
    .catch(() => []);
  return NextResponse.json({ accounts: users });
}
