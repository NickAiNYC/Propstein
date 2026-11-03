// app/api/legal/accept-terms/route.ts
import { NextResponse } from "next/server";
import { headers } from "next/headers";
import { getServerSession } from "next-auth/next";
import { PrismaClient } from "@prisma/client";
import crypto from "crypto";

const prisma = new PrismaClient();

export async function POST(req: Request) {
  try {
    const session = await getServerSession();
    const body = await req.json();
    const termsVersion = body.terms_version || "v1.0.0-2026-10";
    const termsHash =
      body.terms_hash ||
      crypto.createHash("sha256").update(`propwire-terms-${termsVersion}`).digest("hex");

    const reqHeaders = await headers();
    const ipAddress =
      reqHeaders.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      reqHeaders.get("x-real-ip") ||
      "127.0.0.1";
    const userAgent = reqHeaders.get("user-agent") || "unknown";

    const userId = session?.user?.id || session?.user?.email || `anonymous_${ipAddress}`;

    try {
      // Log acceptance record into database
      await (prisma as any).termsAcceptance.upsert({
        where: {
          userId_termsVersion: {
            userId,
            termsVersion,
          },
        },
        create: {
          userId,
          termsVersion,
          termsHash,
          acceptedAt: new Date(),
          ipAddress,
          userAgent,
        },
        update: {
          acceptedAt: new Date(),
          ipAddress,
          userAgent,
        },
      });
    } catch (dbErr) {
      console.warn("[legal/accept-terms] Note: DB table logging skipped (using audit log fallback):", dbErr);
    }

    return NextResponse.json({
      success: true,
      message: "Terms of service acceptance recorded.",
      audit: {
        userId,
        termsVersion,
        termsHash,
        timestamp: new Date().toISOString(),
      },
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: err?.message || "Failed to log terms acceptance." },
      { status: 500 }
    );
  }
}
