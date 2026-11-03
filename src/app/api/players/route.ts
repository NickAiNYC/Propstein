import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getTier } from "@/lib/tier";

export const dynamic = "force-dynamic";

const CACHE = "public, s-maxage=60, stale-while-revalidate=300";

// GET /api/players?league=NBA&team=CLE&search=lebron&limit=50
// Directory + season stats are FREE. Rolling box-score form is PRO-only.
export async function GET(req: NextRequest) {
  try {
    const sp = req.nextUrl.searchParams;
    const league = (sp.get("league") ?? "NBA").toUpperCase();
    const team = sp.get("team")?.toUpperCase();
    const search = sp.get("search")?.trim();
    const limit = Math.min(Number(sp.get("limit") ?? 60) || 60, 200);
    const tier = await getTier();

    const where: Record<string, unknown> = { league };
    if (team) where.team = team;
    if (search) where.nameKey = { contains: search.toLowerCase().replace(/\s+/g, "") };

    const players = await db.player.findMany({
      where,
      // 'espn' < 'nba_registry' < 'snapshot_v1' alphabetically — canonical first
      orderBy: [{ source: "asc" }, { team: "asc" }, { nameKey: "asc" }],
      take: Math.min(limit * 4, 400),
      select: {
        id: true,
        league: true,
        name: true,
        team: true,
        position: true,
        jersey: true,
        headshot: true,
        source: true,
        statsSummary: true,
        formSummary: tier === "pro",
      },
    });

    // richest rows first, then honor the requested limit
    players.sort((a, b) => {
      const rank = (p: { source: string; statsSummary: unknown }) =>
        p.source === "espn" && p.statsSummary ? 0 : p.source === "espn" ? 1 : 2;
      return rank(a) - rank(b);
    });
    players.splice(Math.max(limit, 0));

    return NextResponse.json(
      {
        tier,
        league,
        count: players.length,
        formIncluded: tier === "pro",
        players,
      },
      { headers: { "Cache-Control": CACHE } },
    );
  } catch (err) {
    console.error("[api/players]", err);
    return NextResponse.json({ error: "players query failed" }, { status: 500 });
  }
}
