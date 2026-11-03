// app/api/webhooks/stripe/route.ts
import { NextResponse } from "next/server";
import { headers } from "next/headers";
import Stripe from "stripe";
import { PrismaClient } from "@prisma/client";
import crypto from "crypto";
import { Resend } from "resend";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2025-08-27.acacia" as any,
});
const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;
const prisma = new PrismaClient();
const resend = new Resend(process.env.RESEND_API_KEY);

export async function POST(req: Request) {
  const bodyText = await req.text();
  const reqHeaders = await headers();
  const signature = reqHeaders.get("Stripe-Signature");

  if (!signature || !webhookSecret) {
    return NextResponse.json(
      { error: "Missing webhook signature or STRIPE_WEBHOOK_SECRET." },
      { status: 400 }
    );
  }

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(bodyText, signature, webhookSecret);
  } catch (err: any) {
    return NextResponse.json(
      { error: `Webhook signature verification failed: ${err.message}` },
      { status: 400 }
    );
  }

  // 1. IDEMPOTENCY: Guard against duplicated Stripe webhook delivery
  const existingEvent = await prisma.stripeEvent.findUnique({
    where: { eventId: event.id },
  });
  if (existingEvent) {
    return NextResponse.json({ received: true, status: "already_processed" });
  }

  try {
    // 2. SUBSCRIPTION PROVISIONING: checkout.session.completed
    if (event.type === "checkout.session.completed") {
      const session = event.data.object as Stripe.Checkout.Session;
      const userId = session.metadata?.propwire_user_id;
      const tier = session.metadata?.tier || "pro";
      const email = session.customer_email || session.customer_details?.email;

      if (!userId || !email) {
        return NextResponse.json({ error: "Missing required checkout metadata." }, { status: 400 });
      }

      // Generate cryptographically random API key
      const rawApiKey = `pw_live_${crypto.randomBytes(24).toString("hex")}`;
      const apiKeyHash = crypto.createHash("sha256").update(rawApiKey).digest("hex");

      await prisma.$transaction([
        prisma.userSubscription.upsert({
          where: { userId },
          create: {
            userId,
            email,
            tier: tier.toUpperCase(),
            apiKeyHash,
            status: "ACTIVE",
            stripeCustomerId: session.customer as string,
            stripeSubscriptionId: session.subscription as string,
            updatedAt: new Date(),
          },
          update: {
            tier: tier.toUpperCase(),
            apiKeyHash,
            status: "ACTIVE",
            stripeCustomerId: session.customer as string,
            stripeSubscriptionId: session.subscription as string,
            updatedAt: new Date(),
          },
        }),
        prisma.stripeEvent.create({
          data: {
            eventId: event.id,
            type: event.type,
            processedAt: new Date(),
          },
        }),
      ]);

      // Secure key delivery via email (Resend)
      if (process.env.RESEND_API_KEY) {
        await resend.emails.send({
          from: "PropWire Terminal <terminal@propwire.io>",
          to: email,
          subject: `Your PropWire ${tier.toUpperCase()} Access & API Key`,
          html: `
            <div style="font-family: monospace; background: #080d14; color: #e2e8f0; padding: 24px; border-radius: 8px;">
              <h2 style="color: #4ade80; margin-top: 0;">Subscription Activated: ${tier.toUpperCase()} Tier</h2>
              <p>Your fail-closed sports analytics feed is ready.</p>
              <div style="background: #0f172a; padding: 16px; border: 1px solid #334155; border-radius: 6px; margin: 20px 0;">
                <p style="margin: 0 0 8px 0; font-size: 11px; text-transform: uppercase; color: #94a3b8;">Your Live API Key</p>
                <code style="font-size: 14px; color: #38bdf8; word-break: break-all;">${rawApiKey}</code>
              </div>
              <p style="font-size: 12px; color: #94a3b8;">
                ⚠️ This key is displayed only once. If you misplace it, rotate it via the terminal dashboard.
              </p>
            </div>
          `,
        });
      }
    }

    // 3. CHURN REVOCATION: customer.subscription.deleted
    if (event.type === "customer.subscription.deleted") {
      const subscription = event.data.object as Stripe.Subscription;
      const customerId = subscription.customer as string;

      // Revoke Discord @Quant Syndicate Verified role immediately upon churn
      const sub = await prisma.userSubscription.findFirst({
        where: { stripeCustomerId: customerId },
      });
      if (
        (sub as any)?.discordId &&
        process.env.DISCORD_GUILD_ID &&
        process.env.DISCORD_QUANT_ROLE_ID &&
        process.env.DISCORD_BOT_TOKEN
      ) {
        try {
          await fetch(
            `https://discord.com/api/v10/guilds/${process.env.DISCORD_GUILD_ID}/members/${(sub as any).discordId}/roles/${process.env.DISCORD_QUANT_ROLE_ID}`,
            {
              method: "DELETE",
              headers: { Authorization: `Bot ${process.env.DISCORD_BOT_TOKEN}` },
            }
          );
        } catch (discordErr) {
          console.error("[stripe-webhook] Failed to strip Discord Quant role on churn:", discordErr);
        }
      }

      await prisma.$transaction([
        prisma.userSubscription.updateMany({
          where: { stripeCustomerId: customerId },
          data: {
            status: "CANCELED",
            apiKeyHash: null, // Nullify SHA-256 hash immediately to revoke API access
            updatedAt: new Date(),
          },
        }),
        prisma.stripeEvent.create({
          data: {
            eventId: event.id,
            type: event.type,
            processedAt: new Date(),
          },
        }),
      ]);
    }

    // 4. PLAN UPDATES: customer.subscription.updated
    if (event.type === "customer.subscription.updated") {
      const subscription = event.data.object as Stripe.Subscription;
      const customerId = subscription.customer as string;
      const newStatus = subscription.status === "active" ? "ACTIVE" : "PAST_DUE";

      await prisma.$transaction([
        prisma.userSubscription.updateMany({
          where: { stripeCustomerId: customerId },
          data: {
            status: newStatus,
            updatedAt: new Date(),
          },
        }),
        prisma.stripeEvent.create({
          data: {
            eventId: event.id,
            type: event.type,
            processedAt: new Date(),
          },
        }),
      ]);
    }

    return NextResponse.json({ received: true });
  } catch (err: any) {
    return NextResponse.json(
      { error: `Webhook handling error: ${err.message}` },
      { status: 500 }
    );
  }
}
