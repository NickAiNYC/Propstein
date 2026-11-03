import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

const CACHE = "public, s-maxage=60, stale-while-revalidate=300";

// GET /api/games?league=NBA&limit=50
// Full live scoreboard — FREE for everyone (scores are always free).
export async function GET(req: NextRequest) {
  try {
    const league = (req.nextUrl.searchParams.get("league") ?? "NBA").toUpperCase();
    const limit = Math.min(Number(req.nextUrl.searchParams.get("limit") ?? 100) || 100, 200);

    const games = await db.game.findMany({
      where: { league },
      orderBy: { startTime: "desc" },
      take: limit,
      select: {
        id: true,
        league: true,
        season: true,
        week: true,
        startTime: true,
        state: true,
        detail: true,
        homeTeam: true,
        homeScore: true,
        awayTeam: true,
        awayScore: true,
        venue: true,
        broadcast: true,
        oddsLine: true,
      },
    });

    return NextResponse.json(
      { league, count: games.length, generatedAt: new Date().toISOString(), games },
      { headers: { "Cache-Control": CACHE } },
    );
  } catch (err) {
    console.error("[api/games]", err);
    return NextResponse.json({ error: "games query failed" }, { status: 500 });
  }
}
