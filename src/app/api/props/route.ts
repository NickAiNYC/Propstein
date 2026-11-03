import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getTier, FREE_TEASER_ROWS, FREE_DELAY_MINUTES } from "@/lib/tier";

export const dynamic = "force-dynamic";

const CACHE = "public, s-maxage=60, stale-while-revalidate=300";

// GET /api/props?slate=2026-W08&league=NFL
//
// FREE: top teaser rows per slate, direction only (side + lean),
//       lines delayed 15 minutes, model numbers stripped.
// PRO:  full join-flattened feed — fair line, prob, fair odds, EV, Kelly,
//       every book — feeds the comparison calculator and slip export.
export async function GET(req: NextRequest) {
  try {
    const sp = req.nextUrl.searchParams;
    const slate = sp.get("slate") ?? undefined;
    const league = sp.get("league")?.toUpperCase();
    const tier = await getTier();
    const pro = tier === "pro";

    const where: Record<string, unknown> = {};
    if (slate) where.slate = slate;
    if (league) where.league = league;

    let rows = await db.prop.findMany({
      where,
      orderBy: [{ slate: "desc" }, { kelly: "desc" }],
      take: 500,
      include: {
        player: {
          select: { id: true, name: true, team: true, position: true, headshot: true, league: true },
        },
        game: {
          select: { id: true, startTime: true, state: true, homeTeam: true, awayTeam: true, slug: true },
        },
      },
    });

    // latest slate when none requested
    if (!slate && rows.length > 0) {
      const latest = rows[0].slate;
      rows = rows.filter((r) => r.slate === latest);
    }

    // FREE: hold back lines fresher than the delay window — free users
    // receive lines as they were FREE_DELAY_MINUTES ago, not live moves.
    const cutoff = new Date(Date.now() - FREE_DELAY_MINUTES * 60_000);
    if (!pro) rows = rows.filter((r) => r.observedAt <= cutoff);

    const total = rows.length;
    const teaser = !pro && rows.length > FREE_TEASER_ROWS;
    if (teaser) rows = rows.slice(0, FREE_TEASER_ROWS);

    const props = rows.map((r) => {
      const base = {
        id: r.id,
        slate: r.slate,
        league: r.league,
        market: r.market,
        line: r.line,
        book: r.book,
        overOdds: r.overOdds,
        underOdds: r.underOdds,
        bestSide: r.bestSide,
        lean: r.lean,
        verified: r.verified,
        observedAt: r.observedAt,
        player: r.player,
        game: r.game,
      };
      if (!pro) return base; // direction only — numbers stripped
      return {
        ...base,
        fairLine: r.fairLine,
        probWin: r.probWin,
        fairOdds: r.fairOdds,
        ev: r.ev,
        kelly: r.kelly,
      };
    });

    return NextResponse.json(
      {
        tier,
        slate: rows[0]?.slate ?? slate ?? null,
        count: props.length,
        totalForSlate: total,
        teaser,
        delayMinutes: pro ? 0 : FREE_DELAY_MINUTES,
        exportEnabled: pro,
        props,
      },
      { headers: { "Cache-Control": CACHE } },
    );
  } catch (err) {
    console.error("[api/props]", err);
    return NextResponse.json({ error: "props query failed" }, { status: 500 });
  }
}
