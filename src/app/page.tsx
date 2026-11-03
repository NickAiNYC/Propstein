"use client";

// Propstein 2.0 — live prop terminal.
// Free tier: full scores, player directory + season stats, 3 teaser props
// with direction only. Pro tier: exact EV, fair odds, Kelly, exports.

import { useMemo, useState } from "react";
import { Sidebar } from "@/components/terminal/sidebar";
import { ScoreTicker } from "@/components/terminal/ticker";
import { StatCards } from "@/components/terminal/stat-cards";
import { GamesPanel } from "@/components/terminal/games-panel";
import { PlayersPanel } from "@/components/terminal/players-panel";
import { PropsPanel } from "@/components/terminal/props-panel";
import { useGames, usePlayers, useProps, useTier } from "@/components/terminal/data-hooks";

export default function TerminalPage() {
  const [league, setLeague] = useState("NBA");
  const [search, setSearch] = useState("");
  const { tier, setTier, pending, demoTier } = useTier();

  const games = useGames(league, tier);
  const players = usePlayers(league, search, tier);
  const propsFeed = useProps(null, tier);

  const gamesLive = games.data?.games.filter((g) => g.state === "in").length ?? 0;
  const gamesToday = games.data?.games.filter((g) => {
    const d = new Date(g.startTime);
    const now = new Date();
    return d.toDateString() === now.toDateString();
  }).length ?? 0;
  const topEdge = useMemo(() => {
    if (tier !== "pro") return null;
    const evs = propsFeed.data?.props.map((p) => p.ev).filter((v): v is number => v != null) ?? [];
    return evs.length > 0 ? Math.max(...evs) : null;
  }, [propsFeed.data, tier]);

  // ticker mixes all leagues
  const nbaGames = useGames("NBA", tier);
  const tickerGames = useMemo(() => {
    const all = [...(nbaGames.data?.games ?? []), ...(games.data?.games ?? [])];
    return all.slice(0, 24);
  }, [nbaGames.data, games.data]);

  const slate = propsFeed.data?.slate ?? null;

  // honest feed state — "live" only when a panel actually has data;
  // empty database or a failed poll is shown as what it is.
  // Props honesty: an unqualified "feed live" is only allowed when the props
  // API explicitly declares a live book source. The bundled v1 snapshot
  // (dataSource "bundled_v1_snapshot", the current default) renders as a
  // static-snapshot status — never as "feed live".
  const gamesCount = games.data?.count ?? 0;
  const propsCount = propsFeed.data?.count ?? 0;
  const propsSnapshot = propsCount > 0 && propsFeed.data?.dataSource !== "live_books";
  const snapshotTitle = `Static v1 snapshot quotes — last observed ${
    propsFeed.data?.lastObservedAt
      ? new Date(propsFeed.data.lastObservedAt).toLocaleString()
      : "—"
  } · ${propsFeed.data?.verifiedCount ?? 0} verified. Not a live odds feed.`;
  const feedState: "live" | "connecting" | "empty" | "down" =
    games.error || propsFeed.error
      ? "down"
      : gamesCount > 0 || propsCount > 0
        ? "live"
        : games.loading || propsFeed.loading
          ? "connecting"
          : "empty";

  return (
    <div className="flex min-h-screen bg-zinc-950 text-zinc-100">
      <Sidebar league={league} onLeague={setLeague} tier={tier} onTier={setTier} pending={pending} demoTier={demoTier} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/70 px-4 backdrop-blur">
          <div className="flex items-center gap-3 font-mono text-xs text-zinc-500">
            {feedState === "live" && (gamesCount > 0 && propsSnapshot ? (
              <span className="flex items-center gap-1.5" title={snapshotTitle}>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> scores live
                </span>
                <span className="text-zinc-700">·</span>
                <span className="flex items-center gap-1.5 text-amber-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> props static snapshot — not live
                </span>
              </span>
            ) : propsSnapshot ? (
              <span className="flex items-center gap-1.5 text-amber-400" title={snapshotTitle}>
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> static snapshot — not live
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-emerald-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> feed live
              </span>
            ))}
            {feedState === "connecting" && (
              <span className="flex items-center gap-1.5 text-amber-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" /> connecting…
              </span>
            )}
            {feedState === "empty" && (
              <span className="flex items-center gap-1.5 text-zinc-500">
                <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" /> no feed yet — ingest has not run
              </span>
            )}
            {feedState === "down" && (
              <span className="flex items-center gap-1.5 text-red-400">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> feed unreachable
              </span>
            )}
            <span className="text-zinc-700">|</span>
            <span>slate {slate ?? "—"}</span>
            <span className="text-zinc-700">|</span>
            <span className={tier === "pro" ? "text-emerald-400" : "text-amber-400"}>tier: {tier}</span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-zinc-600">
            free gets the direction · pro gets the number
          </div>
        </header>

        <ScoreTicker games={tickerGames} />

        <main className="flex-1 space-y-5 overflow-x-auto p-4 pb-16 lg:p-6">
          <StatCards
            gamesLive={gamesLive}
            gamesToday={gamesToday}
            playersTracked={players.data?.count ?? 0}
            propsInSlate={propsFeed.data?.count ?? 0}
            topEdge={topEdge}
            pro={tier === "pro"}
          />

          <GamesPanel games={games.data?.games ?? []} loading={games.loading} />

          <PropsPanel
            props={propsFeed.data?.props ?? []}
            resp={propsFeed.data}
            tier={tier}
            loading={propsFeed.loading}
          />

          <PlayersPanel
            players={players.data?.players ?? []}
            loading={players.loading}
            tier={tier}
            search={search}
            onSearch={setSearch}
          />
        </main>

        <footer className="mt-auto border-t border-zinc-800/80 bg-zinc-950/80 px-4 py-2.5 font-mono text-[10px] text-zinc-600 backdrop-blur">
          propstein 2.0 · data: espn public json + nba_api (no keys, $0/mo) · ingest: github actions cron ·
          build: next.js + prisma · <a className="underline decoration-zinc-700 hover:text-zinc-400" href="/performance">track record</a> ·
          projections are estimates, not betting advice
        </footer>
      </div>
    </div>
  );
}
