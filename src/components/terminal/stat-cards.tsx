"use client";

// Stat cards — terminal KPI strip.

import { Activity, Database, Layers, TrendingUp } from "lucide-react";

interface StatCardsProps {
  gamesLive: number;
  gamesToday: number;
  playersTracked: number;
  propsInSlate: number;
  topEdge: number | null;
  pro: boolean;
}

function Stat({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="glass glass-hover scanline flex items-center gap-3 rounded-lg px-4 py-3 transition-colors">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md border ${accent ?? "border-zinc-700/60 bg-zinc-900/60 text-emerald-400"}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
        <div className="truncate font-mono text-lg font-semibold text-zinc-100">{value}</div>
        {sub ? <div className="truncate font-mono text-[10px] text-zinc-500">{sub}</div> : null}
      </div>
    </div>
  );
}

export function StatCards({ gamesLive, gamesToday, playersTracked, propsInSlate, topEdge, pro }: StatCardsProps) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Stat
        icon={<Activity size={16} />}
        label="live now"
        value={String(gamesLive)}
        sub={`${gamesToday} on slate`}
        accent={gamesLive > 0 ? "border-rose-800/60 bg-rose-950/40 text-rose-400" : undefined}
      />
      <Stat icon={<Database size={16} />} label="players tracked" value={String(playersTracked)} sub="registry + box feed" />
      <Stat icon={<Layers size={16} />} label="props in slate" value={String(propsInSlate)} />
      <Stat
        icon={<TrendingUp size={16} />}
        label={pro ? "top edge (EV%)" : "top lean"}
        value={pro ? (topEdge != null ? `${topEdge.toFixed(1)}%` : "—") : "WATCH"}
        sub={pro ? "full-Kelly ranked" : "upgrade for exact EV"}
        accent="border-emerald-800/60 bg-emerald-950/40 text-emerald-400"
      />
      <div className="glass flex flex-col justify-center rounded-lg px-4 py-3 lg:col-span-1 col-span-2">
        <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">data stack</div>
        <div className="font-mono text-[11px] leading-relaxed text-zinc-400">
          ESPN public JSON · nba_api · $0/mo · no keys
        </div>
      </div>
    </div>
  );
}
