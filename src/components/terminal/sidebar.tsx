"use client";

// Sidebar — league nav, feed status, tier switch (sandbox preview of
// the Supabase-authenticated Free/Pro gate).

import { cn } from "@/lib/utils";
import { Activity, Eye, EyeOff, Radio } from "lucide-react";
import { Tier } from "./data-hooks";

const LEAGUES = ["NBA", "NFL", "NHL"] as const;

export function Sidebar({
  league,
  onLeague,
  tier,
  onTier,
  pending,
}: {
  league: string;
  onLeague: (l: string) => void;
  tier: Tier;
  onTier: (t: Tier) => void;
  pending: boolean;
}) {
  return (
    <aside className="hidden w-52 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/60 backdrop-blur md:flex" aria-label="terminal nav">
      <div className="flex items-center gap-2 px-4 py-4">
        <span className="flex h-7 w-7 items-center justify-center rounded-md border border-emerald-800/60 bg-emerald-950/40 font-mono text-sm font-bold text-emerald-400">
          P
        </span>
        <div>
          <div className="font-mono text-sm font-bold tracking-tight text-zinc-100">propstein</div>
          <div className="font-mono text-[9px] uppercase tracking-widest text-zinc-600">live prop terminal</div>
        </div>
      </div>

      <nav className="space-y-0.5 px-2">
        <div className="px-2 pb-1 pt-2 font-mono text-[9px] uppercase tracking-widest text-zinc-600">leagues</div>
        {LEAGUES.map((l) => (
          <button
            key={l}
            onClick={() => onLeague(l)}
            className={cn(
              "flex w-full items-center justify-between rounded-md px-2.5 py-1.5 font-mono text-xs transition-colors",
              league === l
                ? "border border-emerald-900/50 bg-emerald-950/30 text-emerald-300"
                : "border border-transparent text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-200",
            )}
          >
            {l}
            <Radio size={11} className={league === l ? "text-emerald-500" : "text-zinc-700"} />
          </button>
        ))}
      </nav>

      <div className="mt-auto space-y-2 p-3">
        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2.5 font-mono text-[10px] leading-relaxed text-zinc-500">
          <div className="flex items-center gap-1.5 text-zinc-400">
            <Activity size={10} className="text-emerald-500" /> ingest: GH actions cron
          </div>
          <div>espn public json · nba_api</div>
          <div>$0/mo · no api keys</div>
        </div>

        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2.5">
          <div className="mb-1.5 font-mono text-[9px] uppercase tracking-widest text-zinc-600">account tier</div>
          <div className="flex gap-1">
            <button
              onClick={() => onTier("free")}
              disabled={pending}
              className={cn(
                "flex-1 rounded-sm border px-2 py-1 font-mono text-[10px] transition-colors disabled:opacity-50",
                tier === "free"
                  ? "border-zinc-600 bg-zinc-800 text-zinc-200"
                  : "border-zinc-800 bg-zinc-900/40 text-zinc-500 hover:text-zinc-300",
              )}
            >
              <EyeOff size={10} className="mr-1 inline" /> free
            </button>
            <button
              onClick={() => onTier("pro")}
              disabled={pending}
              className={cn(
                "flex-1 rounded-sm border px-2 py-1 font-mono text-[10px] transition-colors disabled:opacity-50",
                tier === "pro"
                  ? "border-emerald-700 bg-emerald-950/50 text-emerald-300"
                  : "border-zinc-800 bg-zinc-900/40 text-zinc-500 hover:text-emerald-400",
              )}
            >
              <Eye size={10} className="mr-1 inline" /> pro
            </button>
          </div>
          <div className="mt-1.5 font-mono text-[9px] leading-snug text-zinc-600">
            {tier === "pro"
              ? "supabase auth: session.user.isPro = true"
              : "supabase auth: session.user.isPro = false"}
          </div>
        </div>
      </div>
    </aside>
  );
}
