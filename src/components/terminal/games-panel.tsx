"use client";

// Games panel — live scoreboard. Full scores are FREE for everyone.

import { GameDTO } from "./data-hooks";
import { cn } from "@/lib/utils";

function timeLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function GameRow({ g }: { g: GameDTO }) {
  const live = g.state === "in";
  const final = g.state === "post";
  const homeWin = final && (g.homeScore ?? 0) > (g.awayScore ?? 0);
  const awayWin = final && (g.awayScore ?? 0) > (g.homeScore ?? 0);
  return (
    <div className="glass glass-hover scanline rounded-lg p-3 transition-colors">
      <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider">
        <span className="flex items-center gap-1.5">
          {live ? (
            <span className="flex items-center gap-1 text-rose-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-500" /> live
            </span>
          ) : final ? (
            <span className="text-zinc-500">final</span>
          ) : (
            <span className="text-emerald-400">{timeLabel(g.startTime)}</span>
          )}
          <span className="text-zinc-600">{g.detail && !final ? g.detail : ""}</span>
        </span>
        <span className="text-zinc-600">{g.venue ?? ""}</span>
      </div>
      <div className="space-y-1 font-mono">
        <div className="flex items-center justify-between">
          <span className={cn("text-sm", awayWin ? "font-semibold text-zinc-100" : "text-zinc-300")}>{g.awayTeam}</span>
          <span className={cn("tabular-nums", awayWin ? "text-emerald-400" : "text-zinc-400")}>{g.awayScore ?? "—"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className={cn("text-sm", homeWin ? "font-semibold text-zinc-100" : "text-zinc-300")}>{g.homeTeam}</span>
          <span className={cn("tabular-nums", homeWin ? "text-emerald-400" : "text-zinc-400")}>{g.homeScore ?? "—"}</span>
        </div>
      </div>
      {g.oddsLine ? (
        <div className="mt-2 border-t border-zinc-800/60 pt-1.5 font-mono text-[10px] text-zinc-500">{g.oddsLine}</div>
      ) : null}
    </div>
  );
}

export function GamesPanel({ games, loading }: { games: GameDTO[]; loading: boolean }) {
  const live = games.filter((g) => g.state === "in");
  const rest = games.filter((g) => g.state !== "in");
  const ordered = [...live, ...rest];

  return (
    <section className="space-y-3" aria-label="live scoreboard">
      <header className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">scoreboard</h2>
        <span className="font-mono text-[10px] text-zinc-600">
          {live.length} live · {games.length} total · s-maxage=60
        </span>
      </header>
      {loading && games.length === 0 ? (
        <div className="glass rounded-lg p-8 text-center font-mono text-xs text-zinc-500">pulling scoreboard…</div>
      ) : ordered.length === 0 ? (
        <div className="glass rounded-lg p-8 text-center font-mono text-xs text-zinc-500">no games for this league yet</div>
      ) : (
        <div className="grid max-h-[420px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
          {ordered.map((g) => (
            <GameRow key={g.id} g={g} />
          ))}
        </div>
      )}
    </section>
  );
}
