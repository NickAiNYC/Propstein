"use client";

// Score ticker — marquee of live/final/upcoming games across leagues.

import { GameDTO } from "./data-hooks";
import { cn } from "@/lib/utils";

export function ScoreTicker({ games }: { games: GameDTO[] }) {
  if (games.length === 0) {
    return (
      <div className="flex h-9 items-center gap-2 overflow-hidden border-b border-zinc-800/80 bg-zinc-950/80 px-4 font-mono text-[11px] text-zinc-500 backdrop-blur">
        <span className="text-emerald-400">▮</span> loading feed…
      </div>
    );
  }
  const doubled = [...games, ...games];
  return (
    <div className="relative h-9 overflow-hidden border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur">
      <div className="ticker-track flex h-full w-max items-center gap-8 pl-4 font-mono text-[11px]">
        {doubled.map((g, i) => (
          <span key={`${g.id}-${i}`} className="flex items-center gap-2 whitespace-nowrap">
            <span
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                g.state === "in" ? "animate-pulse bg-rose-500" : g.state === "post" ? "bg-zinc-600" : "bg-emerald-500",
              )}
            />
            <span className="text-zinc-500">{g.league}</span>
            <span className="text-zinc-200">
              {g.awayTeam} <span className="text-zinc-400">{g.awayScore ?? "—"}</span>
            </span>
            <span className="text-zinc-600">@</span>
            <span className="text-zinc-200">
              {g.homeTeam} <span className="text-zinc-400">{g.homeScore ?? "—"}</span>
            </span>
            <span className="text-zinc-600">{g.detail ?? ""}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
