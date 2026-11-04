"use client";

/* PropStein — market detail sheet
   Opens from a board row without unmounting the board: filter
   state and scroll survive. Desktop: right-side research panel.
   Mobile: bottom sheet with drag handle and safe-area padding. */

import { useEffect } from "react";
import { useApp } from "@/lib/propstein/router";
import { getRow, invalidationFactors } from "@/lib/propstein/derive";
import { gameFor } from "@/lib/propstein/data";
import { MARKET_KEYS_BY_SPORT, MARKET_META, SPORT_META, type MarketKey } from "@/lib/propstein/types";
import { fmt, fmtPct, fmtOdds, formatAge, formatTimestamp, formatKickoff } from "@/lib/propstein/format";
import { overProb } from "@/lib/propstein/model";
import { StatusChip, TeamMark, DivergenceValue } from "./primitives";
import { SparkDistribution } from "./charts/SparkDistribution";
import { cn } from "@/lib/utils";
import { X, ArrowUpRight, ShieldAlert, Info } from "lucide-react";

export function MarketDetailSheet({ playerId, market }: { playerId: string; market: MarketKey }) {
  const { closeDrawer, setRoute, savedPlayers, toggleSaved } = useApp();
  const row = getRow(playerId, market);
  const otherMarkets = row
    ? MARKET_KEYS_BY_SPORT[row.player.sport].filter((m) => m !== market)
    : [];
  const rowOther = otherMarkets.length > 0 ? getRow(playerId, otherMarkets[0]) : undefined;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [closeDrawer]);

  if (!row) return null;

  const game = gameFor(row.player.gameId);
  const home = game.home === row.player.team;
  const opp = home ? game.away : game.home;
  const saved = savedPlayers.includes(playerId);
  const modelOver = row.quote ? overProb(row.quote.line, row.projection.law) : null;
  const factors = invalidationFactors(row);
  const unit = MARKET_META[market].unit;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center sm:items-stretch sm:justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={`${row.player.name} — ${MARKET_META[market].label} research`}
    >
      <div
        className="absolute inset-0 bg-black/55 backdrop-blur-[1px]"
        onClick={closeDrawer}
        aria-hidden
      />
      <div
        className="relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-[8px] border border-hairline bg-panel shadow-2xl shadow-black/50 sm:mt-14 sm:max-h-none sm:w-[440px] sm:rounded-none sm:rounded-l-[8px] sm:border-y-0 sm:border-r-0"
      >
        {/* header */}
        <div className="hairline-b flex items-start gap-3 border-hairline px-4 py-3.5">
          <TeamMark abbr={row.player.team} size={36} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold text-text">{row.player.name}</h2>
            <p className="truncate text-xs text-text-muted">
              {row.player.pos} · {row.player.team} {home ? "vs" : "@"} {opp} · {formatKickoff(game.kickoff)} ET
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => toggleSaved(playerId)}
              aria-pressed={saved}
              aria-label={saved ? "Remove from saved" : "Save player"}
              className="flex h-8 w-8 items-center justify-center rounded-[3px] text-text-muted hover:text-sapphire"
            >
              <svg viewBox="0 0 24 24" className={cn("h-4 w-4", saved && "fill-sapphire text-sapphire")} fill={saved ? "currentColor" : "none"} stroke="currentColor" strokeWidth={2} aria-hidden>
                <path d="M12 3l2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 16.9l-5.4 2.9 1.1-6.1L3.2 9.4l6.1-.8L12 3z" />
              </svg>
            </button>
            <button
              type="button"
              onClick={closeDrawer}
              aria-label="Close detail"
              className="flex h-8 w-8 items-center justify-center rounded-[3px] text-text-muted hover:text-text"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>

        {/* body */}
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 pb-safe">
          {/* market + status */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-text">
              {MARKET_META[market].label} · {SPORT_META[row.player.sport].label}{" "}
              {row.player.sport === "nfl" ? `WK ${game.week}` : "Nov 6"}
            </p>
            <StatusChip status={row.status} />
          </div>

          {/* headline numbers */}
          <div className="mt-3 grid grid-cols-3 gap-px overflow-hidden rounded-[4px] border border-hairline bg-hairline">
            <div className="bg-workspace px-3 py-2.5">
              <p className="label-micro">Fair (median)</p>
              <p className="mt-0.5 font-data text-lg leading-none text-sapphire">
                {fmt(row.fairLine, row.fairLine % 1 === 0 ? 0 : 1)}
                <span className="ml-1 text-[10px] text-text-muted">{unit}</span>
              </p>
            </div>
            <div className="bg-workspace px-3 py-2.5">
              <p className="label-micro">Volume (mean)</p>
              <p className="mt-0.5 font-data text-lg leading-none text-text">
                {fmt(row.projectedVolume, 1)}
                <span className="ml-1 text-[10px] text-text-muted">{unit}</span>
              </p>
            </div>
            <div className="bg-workspace px-3 py-2.5">
              <p className="label-micro">Captured line</p>
              <p className="mt-0.5 font-data text-lg leading-none text-text">
                {row.quote ? row.quote.line : "—"}
                {row.quote ? (
                  <span className="ml-1 text-[10px] text-text-muted">{fmtOdds(row.quote.overOdds)}</span>
                ) : null}
              </p>
            </div>
          </div>

          {/* mini distribution */}
          <div className="mt-4">
            <p className="label-micro mb-2">Distribution · 80% interval {fmt(row.p10, 0)}–{fmt(row.p90, 0)} {unit}</p>
            <SparkDistribution law={row.projection.law} market={market} quoteLine={row.quote?.line ?? null} />
          </div>

          {/* quote provenance */}
          {row.quote ? (
            <div className="mt-4 rounded-[4px] border border-hairline bg-workspace p-3">
              <p className="label-micro flex items-center gap-1.5">
                <Info className="h-3 w-3" aria-hidden /> Quote provenance
              </p>
              <dl className="mt-2 space-y-1.5 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-text-muted">Source</dt>
                  <dd className="text-right text-text">{row.quote.source}</dd>
                </div>
                {row.quote.verifiedAgainst ? (
                  <div className="flex justify-between gap-3">
                    <dt className="text-text-muted">Verified against</dt>
                    <dd className="text-right text-text">{row.quote.verifiedAgainst}</dd>
                  </div>
                ) : null}
                <div className="flex justify-between gap-3">
                  <dt className="text-text-muted">Captured</dt>
                  <dd className="text-right font-data text-text">
                    {formatTimestamp(row.quote.capturedAt)} · {formatAge(row.quote.capturedAt)} ago
                  </dd>
                </div>
                {modelOver !== null ? (
                  <div className="flex justify-between gap-3">
                    <dt className="text-text-muted">Model P(over {row.quote.line})</dt>
                    <dd className="text-right font-data text-text">{fmtPct(modelOver)}</dd>
                  </div>
                ) : null}
                {row.status === "STALE" ? (
                  <p className="flex items-start gap-1.5 rounded-[3px] bg-caution/10 px-2 py-1.5 text-[11px] leading-snug text-caution">
                    <ShieldAlert className="mt-px h-3 w-3 shrink-0" aria-hidden />
                    Stale capture — {formatAge(row.quote.capturedAt)} old. Treat as archived
                    context, not a current quote.
                  </p>
                ) : null}
              </dl>
            </div>
          ) : (
            <div className="mt-4 rounded-[4px] border border-hairline bg-workspace p-3 text-xs leading-relaxed text-text-muted">
              {row.status === "UNAVAILABLE"
                ? `Market unavailable — ${row.unavailableReason ?? "no line posted"}.`
                : "No quote captured for this market yet. All figures are model output only (MODEL_ONLY)."}
            </div>
          )}

          {/* divergence */}
          {row.quote ? (
            <div className="mt-4 flex items-center justify-between rounded-[4px] border border-hairline bg-workspace px-3 py-2.5">
              <span className="text-xs text-text-muted">Model − market divergence</span>
              <DivergenceValue
                z={row.comparison.standardizedDivergence}
                lineDivergence={row.comparison.lineDivergence}
              />
            </div>
          ) : null}

          {/* invalidation */}
          <div className="mt-4">
            <p className="label-micro mb-2">What could break it</p>
            <ul className="space-y-2">
              {factors.slice(0, 3).map((f) => (
                <li key={f.title} className="rounded-[4px] border border-hairline bg-workspace p-2.5">
                  <p className="flex items-center gap-1.5 text-xs font-medium text-text">
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 rounded-full"
                      style={{
                        background:
                          f.severity === "material"
                            ? "var(--ps-danger)"
                            : f.severity === "moderate"
                              ? "var(--ps-caution)"
                              : "var(--ps-text-muted)",
                      }}
                    />
                    {f.title}
                  </p>
                  <p className="mt-1 text-[11px] leading-snug text-text-muted">{f.detail}</p>
                </li>
              ))}
            </ul>
          </div>

          {/* other markets */}
          {otherMarkets.length > 0 ? (
            <div className="mt-4 flex flex-col gap-2">
              {otherMarkets.map((m) => {
                const r = getRow(playerId, m);
                if (!r) return null;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => useApp.getState().openDrawer(playerId, m)}
                    className="flex w-full items-center justify-between rounded-[6px] border border-hairline bg-workspace px-3 py-2.5 text-left transition-colors hover:border-sapphire/40"
                  >
                    <span className="text-xs text-text-muted">Also modeled: {MARKET_META[m].label}</span>
                    <span className="flex items-center gap-1 font-data text-xs text-sapphire">
                      {fmt(r.fairLine, r.fairLine % 1 === 0 ? 0 : 1)}
                      <ArrowUpRight className="h-3 w-3" aria-hidden />
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}

          {/* full research link */}
          <button
            type="button"
            onClick={() => setRoute({ view: "player", playerId, market })}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-[3px] border border-sapphire/40 bg-sapphire-surface px-3 py-2.5 text-xs font-medium text-sapphire transition-colors hover:border-sapphire/60"
          >
            Open full research page
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
