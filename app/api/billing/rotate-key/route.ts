// app/api/billing/rotate-key/route.ts
import { NextResponse } from "next/server";
import { getServerSession } from "next-auth/next";
import { PrismaClient } from "@prisma/client";
import crypto from "crypto";
import { Resend } from "resend";

const prisma = new PrismaClient();
const resend = new Resend(process.env.RESEND_API_KEY);

export async function POST() {
  try {
    const session = await getServerSession();
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const userId = session.user.id || session.user.email;
    const sub = await prisma.userSubscription.findUnique({
      where: { userId },
    });

    if (!sub || sub.status !== "ACTIVE") {
      return NextResponse.json(
        { error: "Active subscription required to generate or rotate API keys." },
        { status: 403 }
      );
    }

    // Rate-limit: Maximum 1 rotation per 24 hours per account to prevent email flooding & namespace abuse
    const lastRotated = (sub as any).lastRotatedAt ? new Date((sub as any).lastRotatedAt).getTime() : 0;
    if (lastRotated > 0) {
      const hoursSince = (Date.now() - lastRotated) / 36e5;
      if (hoursSince < 24) {
        const remainingHours = Math.ceil(24 - hoursSince);
        return NextResponse.json(
          { error: `Key rotation locked. Maximum 1 rotation per 24 hours. Try again in ${remainingHours}h.` },
          { status: 429 }
        );
      }
    }

    // Generate new key and replace hash
    const rawApiKey = `pw_live_${crypto.randomBytes(24).toString("hex")}`;
    const apiKeyHash = crypto.createHash("sha256").update(rawApiKey).digest("hex");

    await prisma.userSubscription.update({
      where: { userId },
      data: {
        apiKeyHash,
        lastRotatedAt: new Date(),
        updatedAt: new Date(),
      } as any,
    });

    // Email new key to account owner
    if (process.env.RESEND_API_KEY && session.user.email) {
      await resend.emails.send({
        from: "PropWire Security <terminal@propwire.io>",
        to: session.user.email,
        subject: "Your Rotated PropWire API Key",
        html: `
          <div style="font-family: monospace; background: #080d14; color: #e2e8f0; padding: 24px; border-radius: 8px;">
            <h3 style="color: #38bdf8;">API Key Rotated Successfully</h3>
            <p>Your previous API key has been invalidated.</p>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; margin: 16px 0;">
              <code>${rawApiKey}</code>
            </div>
            <p style="font-size: 11px; color: #94a3b8;">If you did not request this rotation, review your security settings immediately.</p>
          </div>
        `,
      });
    }

    return NextResponse.json({
      success: true,
      message: "API key rotated successfully. A copy has been dispatched to your verified email.",
      key_prefix: rawApiKey.slice(0, 12) + "…",
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: err?.message || "Key rotation failed." },
      { status: 500 }
    );
  }
}
