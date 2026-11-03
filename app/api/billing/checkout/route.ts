// app/api/billing/checkout/route.ts
import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getServerSession } from "next-auth/next";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2025-08-27.acacia" as any,
});

const PRICE_TIERS: Record<string, string> = {
  pro: process.env.STRIPE_PRICE_ID_PRO || "price_pro_29_mo",
  quant: process.env.STRIPE_PRICE_ID_QUANT || "price_quant_299_mo",
};

export async function POST(req: Request) {
  try {
    // 1. Authenticate user server-side (prevent identity spoofing)
    const session = await getServerSession();
    if (!session?.user?.email) {
      return NextResponse.json(
        { error: "Unauthorized: Active authenticated session required." },
        { status: 401 }
      );
    }

    const body = await req.json();
    const tier = (body?.tier || "").toLowerCase();
    const priceId = PRICE_TIERS[tier];

    if (!priceId) {
      return NextResponse.json(
        { error: "Invalid subscription tier. Must be 'pro' ($29/mo) or 'quant' ($299/mo)." },
        { status: 400 }
      );
    }

    const appUrl = process.env.NEXT_PUBLIC_APP_URL || "https://propstein.com";

    const checkout = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      mode: "subscription",
      customer_email: session.user.email,
      line_items: [{ price: priceId, quantity: 1 }],
      metadata: {
        propwire_user_id: session.user.id || session.user.email,
        tier,
      },
      subscription_data: {
        metadata: {
          propwire_user_id: session.user.id || session.user.email,
          tier,
        },
      },
      success_url: `${appUrl}/terminal?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${appUrl}/pricing?checkout=cancelled`,
    });

    return NextResponse.json({ url: checkout.url });
  } catch (err: any) {
    return NextResponse.json(
      { error: err?.message || "Stripe checkout session creation failed." },
      { status: 500 }
    );
  }
}
