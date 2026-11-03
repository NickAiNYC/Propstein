// Propstein 2.0 seed — real data only.
//
//   NBA games     ESPN scoreboard (last 3 days)
//   NBA players   ESPN box-score summaries (canonical espn-nba-{id})
//                 + nba_api registry (nba-{statsId}) merged by nameKey —
//                 ESPN wins, registry row retired. THE v2 id fix.
//   NFL/NHL games ESPN scoreboard (live)
//   NFL props     v1 snapshot live-odds feed (Polymarket quotes, real
//                 players/odds; synthetic demo fixtures are skipped)
//   Users         demo free + pro accounts for tier gating
//
// Run: bun scripts/seed.ts

import { db } from "../src/lib/db";
import { computeEdge } from "../src/lib/ev";
import { readFileSync } from "node:fs";

const SNAPSHOT_DIR = "/home/z/my-project/propstein-live-sniper/viewer";

/* ── helpers ─────────────────────────────────────────────────────── */

function nameKey(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z]/g, "");
}

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10).replace(/-/g, "");
}

async function jget(url: string, retries = 2): Promise<any> {
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, { headers: { "User-Agent": "propstein-seed/2.0" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (i === retries) throw e;
      await new Promise((r) => setTimeout(r, 800 * (i + 1)));
    }
  }
}

/* ── ESPN games ──────────────────────────────────────────────────── */

interface GameUpsert {
  id: string;
  league: string;
  season: number;
  week: number | null;
  slug: string | null;
  startTime: Date;
  state: string;
  detail: string | null;
  homeTeam: string;
  homeScore: number | null;
  awayTeam: string;
  awayScore: number | null;
  venue: string | null;
  broadcast: string | null;
  oddsLine: string | null;
  rawPayload: unknown;
}

function mapEvent(league: string, ev: any): GameUpsert {
  const comp = ev.competitions?.[0] ?? {};
  const home = (comp.competitors ?? []).find((c: any) => c.homeAway === "home");
  const away = (comp.competitors ?? []).find((c: any) => c.homeAway === "away");
  const odds = comp.odds?.[0];
  const oddsLine = odds ? `${odds.details ?? ""}${odds.overUnder ? ` · O/U ${odds.overUnder}` : ""}`.trim() : null;
  return {
    id: `espn-${league.toLowerCase()}-${ev.id}`,
    league,
    season: ev.season?.year ?? 2026,
    week: ev.week?.number ?? null,
    slug: null,
    startTime: new Date(ev.date),
    state: ev.status?.type?.state ?? "pre",
    detail: ev.status?.type?.shortDetail ?? null,
    homeTeam: home?.team?.abbreviation ?? "—",
    homeScore: home?.score != null ? Number(home.score) : null,
    awayTeam: away?.team?.abbreviation ?? "—",
    awayScore: away?.score != null ? Number(away.score) : null,
    venue: comp.venue?.fullName ?? null,
    broadcast: comp.broadcasts?.[0]?.names?.join(", ") ?? null,
    oddsLine: oddsLine || null,
    rawPayload: { espnEventId: ev.id, name: ev.shortName },
  };
}

async function ingestScoreboard(league: string, path: string, dates: string[]): Promise<GameUpsert[]> {
  const out: GameUpsert[] = [];
  for (const d of dates) {
    try {
      const data = await jget(`https://site.api.espn.com/apis/site/v2/sports/${path}/scoreboard?dates=${d}`);
      for (const ev of data.events ?? []) out.push(mapEvent(league, ev));
    } catch (e) {
      console.warn(`  ! ${league} scoreboard ${d} failed:`, (e as Error).message);
    }
  }
  // dedupe by id
  const seen = new Map<string, GameUpsert>();
  for (const g of out) seen.set(g.id, g);
  return [...seen.values()];
}

/* ── ESPN NBA players from box scores ────────────────────────────── */

interface GameLog {
  espnId: string;
  gameId: string;
  date: string;
  opponent: string;
  stats: Record<string, number>;
}

async function fetchSummaryPlayers(eventId: string): Promise<{ players: any[]; logs: GameLog[] }> {
  const d = await jget(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=${eventId}`);
  const players: any[] = [];
  const logs: GameLog[] = [];
  const gameId = `espn-nba-${eventId}`;
  const date = d.header?.competitions?.[0]?.date ?? new Date().toISOString();
  for (const team of d.boxscore?.players ?? []) {
    const abbr = team.team?.abbreviation ?? "—";
    const opp = (d.header?.competitions?.[0]?.competitors ?? []).find(
      (c: any) => c.team?.abbreviation !== abbr,
    )?.team?.abbreviation;
    for (const st of team.statistics ?? []) {
      const labels: string[] = st.names ?? st.labels ?? [];
      for (const a of st.athletes ?? []) {
        if (!a.athlete?.id || a.didNotPlay) continue;
        const statMap: Record<string, number> = {};
        (a.stats ?? []).forEach((v: string, i: number) => {
          const n = Number(v);
          if (!Number.isNaN(n)) statMap[labels[i]] = n;
        });
        players.push({
          espnId: String(a.athlete.id),
          name: a.athlete.displayName,
          position: a.athlete.position?.abbreviation ?? null,
          jersey: a.athlete.jersey ? Number(a.athlete.jersey) : null,
          headshot: a.athlete.headshot?.href ?? null,
          team: abbr,
          starter: !!a.starter,
        });
        logs.push({ espnId: String(a.athlete.id), gameId, date, opponent: opp ?? "—", stats: statMap });
      }
    }
  }
  return { players, logs };
}

/* ── main ────────────────────────────────────────────────────────── */

async function main() {
  console.log("▶ propstein seed 2.0 — real data, $0 apis\n");

  await db.prop.deleteMany();
  await db.player.deleteMany();
  await db.game.deleteMany();
  await db.user.deleteMany();

  /* 1. NBA games (last 3 days) + summaries */
  const today = new Date();
  const days = [0, 1, 2].map((n) => {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - n);
    return ymd(d);
  });
  console.log("· NBA scoreboards", days.join(" "));
  const nbaGames = await ingestScoreboard("NBA", "basketball/nba", days);
  for (const g of nbaGames) {
    await db.game.upsert({ where: { id: g.id }, create: g, update: g });
  }
  console.log(`  ${nbaGames.length} games (${nbaGames.filter((g) => g.state === "post").length} final)`);

  const postGames = nbaGames.filter((g) => g.state === "post").slice(0, 18);
  console.log(`· fetching ${postGames.length} box-score summaries…`);
  const logByPlayer = new Map<string, { meta: any; logs: GameLog[] }>();
  for (let i = 0; i < postGames.length; i += 4) {
    const chunk = postGames.slice(i, i + 4);
    const results = await Promise.allSettled(
      chunk.map((g) => fetchSummaryPlayers(g.id.replace("espn-nba-", ""))),
    );
    for (const r of results) {
      if (r.status !== "fulfilled") continue;
      for (const p of r.value.players) {
        const key = `espn-nba-${p.espnId}`;
        const entry = logByPlayer.get(key) ?? { meta: p, logs: [] };
        entry.meta = p; // freshest team/pos
        entry.logs.push(...r.value.logs.filter((l) => l.espnId === p.espnId));
        logByPlayer.set(key, entry);
      }
    }
  }

  // rebuild logs correctly (the chunk above may duplicate) — collect per espnId
  const clean = new Map<string, { meta: any; logs: GameLog[] }>();
  for (const [id, entry] of logByPlayer) {
    const seen = new Set<string>();
    const logs = entry.logs.filter((l) => (seen.has(l.gameId) ? false : (seen.add(l.gameId), true)));
    clean.set(id, { meta: entry.meta, logs });
  }

  let espnPlayers = 0;
  for (const [id, { meta, logs }] of clean) {
    if (logs.length === 0) continue;
    const avg = (k: string) => logs.reduce((s, l) => s + (l.stats[k] ?? 0), 0) / logs.length;
    const statsSummary = {
      GP: logs.length,
      MIN: +avg("MIN").toFixed(1),
      PTS: +avg("PTS").toFixed(1),
      REB: +avg("REB").toFixed(1),
      AST: +avg("AST").toFixed(1),
      STL: +avg("STL").toFixed(1),
      BLK: +avg("BLK").toFixed(1),
    };
    const formSummary = [...logs]
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 3)
      .map((l) => ({
        date: l.date.slice(0, 10),
        opponent: l.opponent,
        PTS: l.stats.PTS ?? 0,
        REB: l.stats.REB ?? 0,
        AST: l.stats.AST ?? 0,
        seasonAvgPTS: statsSummary.PTS,
      }));
    // merge fix: retire registry duplicate by nameKey
    const nk = nameKey(meta.name);
    const dupe = await db.player.findFirst({ where: { league: "NBA", nameKey: nk, NOT: { id } } });
    const data = {
      league: "NBA",
      name: meta.name,
      nameKey: nk,
      team: meta.team,
      position: meta.position,
      jersey: meta.jersey ?? null,
      headshot: meta.headshot,
      espnId: meta.espnId,
      nbaStatsId: dupe?.nbaStatsId ?? null,
      source: "espn",
      statsSummary,
      formSummary,
    };
    if (dupe) {
      await db.player.delete({ where: { id: dupe.id } }).catch(() => {});
    }
    await db.player.upsert({ where: { id }, create: { id, ...data }, update: data });
    espnPlayers++;
  }
  console.log(`  ${espnPlayers} canonical ESPN players (espn-nba-*)`);

  /* 2. nba_api registry (separate nba-{id} namespace, merge-ready) */
  console.log("· nba_api registry (nba-{statsId})…");
  const { execSync } = await import("node:child_process");
  try {
    const raw = execSync(
      `python3 -c "from nba_api.stats.static import players; import json; print(json.dumps(players.get_active_players()))"`,
      { encoding: "utf8", timeout: 60_000 },
    );
    const registry = JSON.parse(raw) as Array<{ id: number; full_name: string }>;
    let inserted = 0;
    for (const p of registry) {
      const nk = nameKey(p.full_name);
      const existsEspn = await db.player.findFirst({ where: { league: "NBA", nameKey: nk, source: "espn" } });
      if (existsEspn) {
        // ESPN already canonical for this person — keep stats, record registry id
        if (!existsEspn.nbaStatsId) {
          await db.player.update({
            where: { id: existsEspn.id },
            data: { nbaStatsId: String(p.id) },
          });
        }
        continue;
      }
      const id = `nba-${p.id}`;
      await db.player.upsert({
        where: { id },
        create: { id, league: "NBA", name: p.full_name, nameKey: nk, source: "nba_registry" },
        update: { name: p.full_name, nameKey: nk },
      });
      inserted++;
    }
    console.log(`  ${inserted} registry-only players (nba-*), ${registry.length} total checked`);
  } catch (e) {
    console.warn("  ! registry unavailable:", (e as Error).message);
  }

  /* 3. NFL + NHL games */
  console.log("· NFL + NHL scoreboards");
  const nfl = await ingestScoreboard("NFL", "football/nfl", days.slice(0, 3));
  const nhl = await ingestScoreboard("NHL", "hockey/nhl", days.slice(0, 3));
  for (const g of [...nfl, ...nhl]) {
    await db.game.upsert({ where: { id: g.id }, create: g, update: g });
  }
  console.log(`  NFL ${nfl.length} · NHL ${nhl.length}`);

  /* 4. v1 snapshot → NFL players + props (real Polymarket quotes only) */
  console.log("· v1 snapshot props (live-odds feed)");
  const quotes = JSON.parse(readFileSync(`${SNAPSHOT_DIR}/live_odds_feed.json`, "utf8")).quotes as any[];
  const picks = JSON.parse(readFileSync(`${SNAPSHOT_DIR}/current_picks.json`, "utf8")) as any;
  const slate = `2026-W${String(picks.week).padStart(2, "0")}`;

  // NFL players from picks (real players, v1 projections as season summary)
  const pickPlayers = new Map<string, any>();
  for (const p of picks.picks) {
    const nk = nameKey(p.player);
    if (!pickPlayers.has(nk)) {
      pickPlayers.set(nk, { name: p.player, team: p.team, position: p.position, proj: p });
    }
  }
  for (const [nk, p] of pickPlayers) {
    const id = `nfl-${nk}`;
    await db.player.upsert({
      where: { id },
      create: {
        id,
        league: "NFL",
        name: p.name,
        nameKey: nk,
        team: p.team,
        position: p.position,
        source: "snapshot_v1",
        statsSummary: {
          projRec: p.proj.proj_rec,
          projYds: p.proj.proj_yards,
          pRecAtFairLine: p.proj.p_rec_at_fair_line,
          v1Rank: p.proj.rank,
        },
      },
      update: {},
    });
  }
  console.log(`  ${pickPlayers.size} NFL players from v1 picks`);

  // props from real quotes (skip synthetic demo fixtures)
  let props = 0;
  const gameStubs = new Map<string, any>();
  for (const q of quotes) {
    if (String(q.book).startsWith("Synthetic")) {
      continue; // demo fixture — not a real player/book
    }
    const nk = nameKey(q.player_name);
    const playerId = `nfl-${nk}`;
    // ensure player exists even if not in picks
    await db.player.upsert({
      where: { id: playerId },
      create: {
        id: playerId,
        league: "NFL",
        name: q.player_name,
        nameKey: nk,
        team: q.team,
        position: q.position ?? null,
        source: "snapshot_v1",
      },
      update: { team: q.team },
    });

    // snapshot game stub
    const gid = q.game_id ? `snap-${q.game_id}` : null;
    if (gid && !gameStubs.has(gid)) {
      const parts = String(q.game_id).split("_"); // 2026_07_NE_CHI
      const stub = {
        id: gid,
        league: "NFL",
        season: Number(parts[0]) || 2026,
        week: Number(parts[1]) || null,
        slug: q.game_id,
        startTime: new Date(q.observed_at),
        state: "post",
        detail: "v1 snapshot slate",
        homeTeam: parts[3] ?? "—",
        homeScore: null,
        awayTeam: parts[2] ?? "—",
        awayScore: null,
        venue: null,
        broadcast: null,
        oddsLine: null,
        rawPayload: { snapshot: true },
      };
      await db.game.upsert({ where: { id: gid }, create: stub, update: stub });
      gameStubs.set(gid, stub);
    }

    const edge = computeEdge({
      fairLine: q.fair_line,
      line: q.line,
      market: q.market,
      overOdds: q.over_odds,
      underOdds: q.under_odds,
    });
    const propId = `${slate}|${playerId}|${q.market}|${q.book}|${q.line}`;
    const data = {
      playerId,
      gameId: gid,
      league: "NFL",
      slate,
      market: q.market,
      line: q.line,
      fairLine: q.fair_line,
      overOdds: q.over_odds,
      underOdds: q.under_odds,
      book: q.book,
      bestSide: edge.bestSide,
      probWin: +edge.probWin.toFixed(4),
      fairOdds: edge.fairOdds,
      ev: +edge.ev.toFixed(2),
      kelly: +edge.kelly.toFixed(4),
      lean: edge.lean,
      verified: q.evaluation?.status === "OBSERVED",
      observedAt: new Date(q.observed_at),
      rawPayload: { quoteId: q.quote_id, evaluation: q.evaluation },
    };
    await db.prop.upsert({ where: { id: propId }, create: { id: propId, ...data }, update: data });
    props++;
  }
  console.log(`  ${props} props from live quotes (synthetic fixtures skipped)`);

  /* 5. demo users */
  await db.user.create({
    data: { email: "free@propstein.dev", displayName: "Free Visitor", isPro: false, subscriptionTier: "free" },
  });
  await db.user.create({
    data: { email: "pro@propstein.dev", displayName: "Pro Subscriber", isPro: true, subscriptionTier: "pro" },
  });

  const counts = {
    games: await db.game.count(),
    players: await db.player.count(),
    props: await db.prop.count(),
    users: await db.user.count(),
    espnPlayers: await db.player.count({ where: { source: "espn" } }),
    registryPlayers: await db.player.count({ where: { source: "nba_registry" } }),
    dupes: await db.player.groupBy({ by: ["league", "nameKey"], _count: true, having: { nameKey: { _count: { gt: 1 } } } }).then((r) => r.length),
  };
  console.log("\n✔ seed complete");
  console.log(JSON.stringify(counts, null, 2));
  await db.$disconnect();
}

main().catch((e) => {
  console.error("seed failed:", e);
  process.exit(1);
});
