"use client";

// Players panel — directory + season stats (FREE), rolling form (PRO).
// Form column blurs behind the paywall for the free tier.

import { PlayerDTO, Tier } from "./data-hooks";
import { cn } from "@/lib/utils";
import { Lock } from "lucide-react";

const FORM_KEYS = ["PTS", "REB", "AST"] as const;

export function PlayersPanel({
  players,
  loading,
  tier,
  search,
  onSearch,
}: {
  players: PlayerDTO[];
  loading: boolean;
  tier: Tier;
  search: string;
  onSearch: (v: string) => void;
}) {
  const pro = tier === "pro";
  return (
    <section className="space-y-3" aria-label="player directory">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">players</h2>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] text-zinc-600">
            {players.length} shown · ids deduped by espn-nba-* canonical
          </span>
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="search player…"
            className="h-7 w-40 rounded-md border border-zinc-700/60 bg-zinc-900/60 px-2 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-700 focus:outline-none"
            aria-label="search players"
          />
        </div>
      </header>
      <div className="glass overflow-hidden rounded-lg">
        <div className="max-h-[420px] overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="sticky top-0 bg-zinc-950/95 text-left text-[10px] uppercase tracking-wider text-zinc-500 backdrop-blur">
              <tr>
                <th className="px-3 py-2 font-medium">player</th>
                <th className="px-3 py-2 font-medium">pos</th>
                <th className="px-3 py-2 text-right font-medium">season ppg</th>
                <th className="px-3 py-2 text-right font-medium">rpg</th>
                <th className="px-3 py-2 text-right font-medium">apg</th>
                <th className="px-3 py-2 font-medium">rolling form (L3)</th>
              </tr>
            </thead>
            <tbody>
              {loading && players.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-8 text-center text-zinc-500">
                    loading registry…
                  </td>
                </tr>
              ) : players.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-8 text-center text-zinc-500">
                    no players match
                  </td>
                </tr>
              ) : (
                players.slice(0, 40).map((p) => {
                  const s = p.statsSummary ?? {};
                  const form = pro ? p.formSummary : null;
                  return (
                    <tr key={p.id} className="border-t border-zinc-800/50 hover:bg-zinc-900/50">
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-2">
                          {p.headshot ? (
                            <img src={p.headshot} alt="" className="h-6 w-6 rounded-sm bg-zinc-800 object-cover" />
                          ) : (
                            <span className="h-6 w-6 rounded-sm bg-zinc-800" />
                          )}
                          <span className="text-zinc-200">{p.name}</span>
                          <span className="text-zinc-600">{p.team ?? "—"}</span>
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-zinc-400">{p.position?.slice(0, 2) ?? "—"}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">
                        {s.PTS != null ? s.PTS.toFixed(1) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">
                        {s.REB != null ? s.REB.toFixed(1) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">
                        {s.AST != null ? s.AST.toFixed(1) : "—"}
                      </td>
                      <td className="px-3 py-1.5">
                        {form && form.length > 0 ? (
                          <span className="flex items-center gap-1.5">
                            {form.slice(0, 3).map((f, i) => (
                              <span
                                key={i}
                                className={cn(
                                  "rounded-sm border px-1.5 py-0.5 tabular-nums",
                                  (Number(f.PTS) ?? 0) >= (Number(f.seasonAvgPTS) ?? 0)
                                    ? "border-emerald-800/60 bg-emerald-950/40 text-emerald-400"
                                    : "border-zinc-700/60 bg-zinc-900 text-zinc-400",
                                )}
                                title={`vs ${String(f.opponent ?? "—")}`}
                              >
                                {String(f.PTS ?? "–")}
                              </span>
                            ))}
                          </span>
                        ) : (
                          <span className="relative inline-flex items-center gap-1.5">
                            <span className="paywall-blur inline-flex gap-1.5" aria-hidden="true">
                              <span className="rounded-sm border border-zinc-700/60 bg-zinc-900 px-1.5 py-0.5 text-zinc-400">18</span>
                              <span className="rounded-sm border border-zinc-700/60 bg-zinc-900 px-1.5 py-0.5 text-zinc-400">9</span>
                              <span className="rounded-sm border border-zinc-700/60 bg-zinc-900 px-1.5 py-0.5 text-zinc-400">24</span>
                            </span>
                            <span className="absolute inset-0 flex items-center justify-center gap-1 text-[10px] text-amber-400/90">
                              <Lock size={10} /> PRO
                            </span>
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
