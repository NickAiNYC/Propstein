"use client";

// Props panel — the model edge table.
// FREE: 3 teaser rows/slate, direction (side+lean) only, 15-min delayed
//       lines, model columns blurred behind the upgrade wall, no export.
// PRO:  full join-flattened feed — fair line, fair odds, EV%, Kelly,
//       best-book highlight, slip copy + CSV export.

import { useMemo, useState } from "react";
import { Copy, Download, Lock, Timer, Zap } from "lucide-react";
import { PropDTO, Tier } from "./data-hooks";
import { cn } from "@/lib/utils";

function fmtOdds(a: number | null | undefined): string {
  if (a == null) return "—";
  return a > 0 ? `+${a}` : `${a}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function marketLabel(m: string): string {
  return m.replace(/_/g, " ");
}

function slipLine(p: PropDTO): string {
  const side = p.bestSide ?? "OVER";
  const odds = side === "OVER" ? p.overOdds : p.underOdds;
  return `[${p.slate}] ${p.player.name} (${p.player.team ?? "—"}) ${side} ${p.line} ${marketLabel(p.market)} @ ${fmtOdds(odds)} · ${p.book} · EV ${fmtPct(p.ev)} · kelly ${((p.kelly ?? 0) * 100).toFixed(1)}%`;
}

function csvEsc(s: string): string {
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function PropsPanel({
  props,
  resp,
  tier,
  loading,
}: {
  props: PropDTO[];
  resp: { slate: string | null; teaser: boolean; delayMinutes: number; totalForSlate: number } | null;
  tier: Tier;
  loading: boolean;
}) {
  const pro = tier === "pro";
  const [copied, setCopied] = useState(false);

  // best book per player+market (Pro comparison calculator)
  const bestBookIds = useMemo(() => {
    const best = new Map<string, string>();
    for (const p of props) {
      const key = `${p.player.id}|${p.market}|${p.line}`;
      const cur = props.find((q) => q.id === best.get(key));
      if (!cur || (p.ev ?? -Infinity) > (cur.ev ?? -Infinity)) best.set(key, p.id);
    }
    return new Set(best.values());
  }, [props]);

  const onCopySlips = async () => {
    const text = props.map(slipLine).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };

  const onExportCsv = () => {
    const header = "slate,player,team,position,market,line,book,best_side,over_odds,under_odds,fair_line,fair_odds,prob_win,ev_pct,kelly_frac,lean,verified,observed_at";
    const rows = props.map((p) =>
      [
        p.slate,
        p.player.name,
        p.player.team ?? "",
        p.player.position ?? "",
        p.market,
        p.line,
        p.book,
        p.bestSide ?? "",
        p.overOdds ?? "",
        p.underOdds ?? "",
        p.fairLine ?? "",
        p.fairOdds ?? "",
        p.probWin != null ? p.probWin.toFixed(4) : "",
        p.ev != null ? p.ev.toFixed(2) : "",
        p.kelly != null ? p.kelly.toFixed(4) : "",
        p.lean ?? "",
        p.verified ? 1 : 0,
        p.observedAt,
      ]
        .map(csvEsc)
        .join(","),
    );
    const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `propstein_${resp?.slate ?? "slate"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="space-y-3" aria-label="prop edges">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">
          prop edges <span className="text-zinc-600">· slate {resp?.slate ?? "—"}</span>
        </h2>
        <div className="flex items-center gap-2">
          {!pro && resp ? (
            <span className="flex items-center gap-1 rounded-full border border-amber-800/60 bg-amber-950/30 px-2 py-0.5 font-mono text-[10px] text-amber-400">
              <Timer size={10} /> lines delayed {resp.delayMinutes}m
            </span>
          ) : null}
          {resp?.teaser ? (
            <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 font-mono text-[10px] text-zinc-400">
              teaser · {resp.totalForSlate} on slate
            </span>
          ) : null}
          {pro ? (
            <>
              <button
                onClick={onCopySlips}
                className="flex h-7 items-center gap-1.5 rounded-md border border-emerald-800/60 bg-emerald-950/40 px-2.5 font-mono text-[10px] text-emerald-300 transition-colors hover:bg-emerald-900/50"
              >
                <Copy size={11} /> {copied ? "copied ✓" : "copy for slips"}
              </button>
              <button
                onClick={onExportCsv}
                className="flex h-7 items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-2.5 font-mono text-[10px] text-zinc-300 transition-colors hover:border-zinc-600"
              >
                <Download size={11} /> csv
              </button>
            </>
          ) : null}
        </div>
      </header>

      <div className="glass relative overflow-hidden rounded-lg">
        <div className="max-h-[460px] overflow-x-auto overflow-y-auto">
          <table className="w-full min-w-[760px] font-mono text-[11px]">
            <thead className="sticky top-0 bg-zinc-950/95 text-left text-[10px] uppercase tracking-wider text-zinc-500 backdrop-blur">
              <tr>
                <th className="px-3 py-2 font-medium">player</th>
                <th className="px-3 py-2 font-medium">market</th>
                <th className="px-3 py-2 text-right font-medium">line</th>
                <th className="px-3 py-2 font-medium">side</th>
                <th className="px-3 py-2 font-medium">book</th>
                <th className="px-3 py-2 font-medium">lean</th>
                <th className="px-3 py-2 text-right font-medium text-emerald-500/70">fair line</th>
                <th className="px-3 py-2 text-right font-medium text-emerald-500/70">fair odds</th>
                <th className="px-3 py-2 text-right font-medium text-emerald-500/70">ev%</th>
                <th className="px-3 py-2 text-right font-medium text-emerald-500/70">kelly</th>
              </tr>
            </thead>
            <tbody>
              {loading && props.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-3 py-10 text-center text-zinc-500">
                    crunching edges…
                  </td>
                </tr>
              ) : props.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-3 py-10 text-center text-zinc-500">
                    no props on this slate yet
                  </td>
                </tr>
              ) : (
                props.map((p) => {
                  const isBest = bestBookIds.has(p.id);
                  return (
                    <tr
                      key={p.id}
                      className={cn(
                        "border-t border-zinc-800/50 hover:bg-zinc-900/50",
                        isBest && pro && "bg-emerald-950/20",
                      )}
                    >
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-2">
                          {p.player.headshot ? (
                            <img src={p.player.headshot} alt="" className="h-6 w-6 rounded-sm bg-zinc-800 object-cover" />
                          ) : (
                            <span className="h-6 w-6 rounded-sm bg-zinc-800" />
                          )}
                          <span className="text-zinc-200">{p.player.name}</span>
                          <span className="text-zinc-600">{p.player.team ?? "—"}</span>
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-zinc-400">{marketLabel(p.market)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">{p.line}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={cn(
                            "rounded-sm border px-1.5 py-0.5",
                            p.bestSide === "OVER"
                              ? "border-emerald-800/60 bg-emerald-950/40 text-emerald-400"
                              : "border-rose-800/60 bg-rose-950/40 text-rose-400",
                          )}
                        >
                          {p.bestSide ?? "—"}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-zinc-400">
                        {p.book}
                        {isBest && pro ? <span className="ml-1 text-emerald-500" title="best book for this line">★</span> : null}
                      </td>
                      <td className="px-3 py-1.5">
                        <span
                          className={cn(
                            "rounded-sm px-1.5 py-0.5",
                            p.lean === "WATCH" ? "bg-amber-950/50 text-amber-400" : "bg-zinc-800/60 text-zinc-500",
                          )}
                        >
                          {p.lean ?? "—"}
                        </span>
                      </td>
                      {pro ? (
                        <>
                          <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">{p.fairLine ?? "—"}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">{fmtOdds(p.fairOdds)}</td>
                          <td
                            className={cn(
                              "px-3 py-1.5 text-right font-semibold tabular-nums",
                              (p.ev ?? 0) > 0 ? "text-emerald-400" : "text-rose-400",
                            )}
                          >
                            {fmtPct(p.ev)}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-zinc-300">
                            {p.kelly != null ? `${(p.kelly * 100).toFixed(1)}%` : "—"}
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="relative px-3 py-1.5 text-right">
                            <span className="paywall-blur" aria-hidden="true">8.5</span>
                          </td>
                          <td className="relative px-3 py-1.5 text-right">
                            <span className="paywall-blur" aria-hidden="true">-105</span>
                          </td>
                          <td className="relative px-3 py-1.5 text-right">
                            <span className="paywall-blur" aria-hidden="true">+12.4%</span>
                          </td>
                          <td className="relative px-3 py-1.5 text-right">
                            <span className="paywall-blur" aria-hidden="true">2.1%</span>
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {!pro ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center bg-gradient-to-t from-zinc-950 via-zinc-950/85 to-transparent pb-3 pt-10">
            <div className="pointer-events-auto glass flex max-w-lg items-center gap-3 rounded-lg border-emerald-900/50 px-4 py-2.5">
              <Lock size={14} className="shrink-0 text-emerald-400" />
              <div className="font-mono text-[11px] leading-relaxed text-zinc-300">
                <span className="text-emerald-400">Upgrade to Pro</span> to unlock live edge — fair odds, exact EV,
                Kelly sizing and book comparison across every slate.
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {!pro ? (
        <p className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-600">
          <Zap size={10} className="text-amber-500/70" /> free tier: direction only · teaser rows · 15-min delayed
          lines · exports disabled
        </p>
      ) : (
        <p className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-600">
          <Zap size={10} className="text-emerald-500/70" /> pro feed: exact EV · full-Kelly (quarter-cap 25%) · best
          book ★ · slip + csv export
        </p>
      )}
    </section>
  );
}
