"use client";

/* ============================================================
   PropStein — market board (Phase 4)
   Desktop: professional research table — aligned mono numerals,
   subtle separators, one status vocabulary, evidence near data.
   Mobile: native-feeling research cards with the same hierarchy.
   Clicking a market opens a detail sheet WITHOUT destroying
   filter state or scroll position.
   ============================================================ */

import { useEffect, useMemo, useRef } from "react";
import { useApp } from "@/lib/propstein/router";
import { getBoard, getBoardFor, BoardRow } from "@/lib/propstein/derive";
import { gameFor } from "@/lib/propstein/data";
import {
  EVIDENCE_STATUS_META,
  EvidenceStatus,
  MARKET_KEYS_BY_SPORT,
  MARKET_META,
  SPORT_META,
  type MarketKey,
  type Sport,
} from "@/lib/propstein/types";
import { fmt, fmtSigned, fmtOdds, formatAge } from "@/lib/propstein/format";
import { StatusChip, TeamMark, Panel } from "./primitives";
import { MarketDetailSheet } from "./MarketDetailSheet";
import { cn } from "@/lib/utils";
import {
  ArrowDownUp,
  Star,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";

/* ---------- filter bar ---------- */

function marketTabsFor(sport: Sport): Array<{ key: MarketKey | "all"; label: string }> {
  return [
    { key: "all", label: "All markets" },
    ...MARKET_KEYS_BY_SPORT[sport].map((m) => ({ key: m, label: MARKET_META[m].label })),
  ];
}

const STATUS_FILTERS: EvidenceStatus[] = [
  "VERIFIED",
  "OBSERVED_UNVERIFIED",
  "STALE",
  "MODEL_ONLY",
  "UNAVAILABLE",
];

function BoardFilters() {
  const { filters, setFilters, route } = useApp();
  const sport: Sport = route.sport ?? "nfl";
  const marketTabs = marketTabsFor(sport);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* market type */}
        <div
          role="tablist"
          aria-label="Market type"
          className="flex overflow-hidden rounded-[6px] border border-hairline"
        >
          {marketTabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={filters.market === t.key}
              onClick={() => setFilters({ market: t.key })}
              className={cn(
                "min-h-[38px] px-3.5 py-2 text-xs font-medium transition-colors",
                filters.market === t.key
                  ? "bg-sapphire-surface text-sapphire"
                  : "bg-panel text-text-muted hover:text-text"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* search — the board-local facet of the unified search; ⌘K remains global */}
        <label className="relative flex h-8 min-w-0 flex-1 items-center gap-2 rounded-[6px] border border-hairline bg-panel px-2.5 sm:max-w-[240px]">
          <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
          <input
            ref={inputRef}
            value={filters.query}
            onChange={(e) => setFilters({ query: e.target.value })}
            placeholder="Filter players, teams…"
            aria-label="Filter board by player or team"
            className="h-full min-w-0 flex-1 bg-transparent text-xs text-text outline-none placeholder:text-text-muted"
          />
          {filters.query ? (
            <button
              type="button"
              onClick={() => setFilters({ query: "" })}
              aria-label="Clear filter"
              className="text-text-muted hover:text-text"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          ) : null}
        </label>

        <BoardSortControl />
      </div>

      {/* status chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <SlidersHorizontal className="h-3.5 w-3.5 text-text-muted" aria-hidden />
        {STATUS_FILTERS.map((s) => {
          const active = filters.statuses.has(s);
          return (
            <button
              key={s}
              type="button"
              aria-pressed={active}
              onClick={() => {
                const next = new Set(filters.statuses);
                if (active) next.delete(s);
                else next.add(s);
                setFilters({ statuses: next });
              }}
              className={cn(
                "inline-flex min-h-[34px] items-center gap-1.5 rounded-[6px] border px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                active ? "text-text" : "text-text-muted hover:text-text"
              )}
              style={{
                borderColor: active
                  ? `color-mix(in srgb, ${EVIDENCE_STATUS_META[s].color} 45%, var(--ps-border))`
                  : "var(--ps-border)",
                background: active
                  ? `color-mix(in srgb, ${EVIDENCE_STATUS_META[s].color} 8%, transparent)`
                  : "transparent",
                color: active ? EVIDENCE_STATUS_META[s].color : undefined,
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: EVIDENCE_STATUS_META[s].color }}
                aria-hidden
              />
              {EVIDENCE_STATUS_META[s].label}
            </button>
          );
        })}
        {filters.statuses.size > 0 ? (
          <button
            type="button"
            onClick={() => setFilters({ statuses: new Set() })}
            className="ml-1 text-[11px] text-text-muted underline decoration-dotted underline-offset-4 hover:text-text"
          >
            clear
          </button>
        ) : null}
      </div>
    </div>
  );
}

function BoardSortControl() {
  const { filters, setFilters } = useApp();
  const options: Array<{ key: typeof filters.sortKey; label: string }> = [
    { key: "divergence", label: "Divergence" },
    { key: "volume", label: "Volume" },
    { key: "player", label: "Player" },
    { key: "status", label: "Status" },
  ];
  return (
    <div className="ml-auto flex h-8 items-center overflow-hidden rounded-[6px] border border-hairline">
      <span className="flex items-center gap-1 border-r border-hairline bg-workspace px-2 text-[10px] font-medium uppercase tracking-wider text-text-muted">
        <ArrowDownUp className="h-3 w-3" aria-hidden /> Sort
      </span>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={filters.sortKey === o.key}
          onClick={() =>
            setFilters({
              sortKey: o.key,
              sortDir: filters.sortKey === o.key && filters.sortDir === "desc" ? "asc" : "desc",
            })
          }
          className={cn(
            "h-full px-2.5 text-[11px] font-medium transition-colors",
            filters.sortKey === o.key ? "bg-sapphire-surface text-sapphire" : "bg-panel text-text-muted hover:text-text"
          )}
        >
          {o.label}
          {filters.sortKey === o.key ? (
            <span className="ml-1 font-data">{filters.sortDir === "desc" ? "↓" : "↑"}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/* ---------- desktop table ---------- */

function BoardTable({ rows }: { rows: BoardRow[] }) {
  const { openDrawer, savedPlayers, toggleSaved } = useApp();

  if (rows.length === 0) return <BoardEmpty />;

  return (
    <div className="overflow-x-auto rounded-[10px] border border-hairline">
      <table className="w-full min-w-[860px] border-collapse text-[13px]">
        <caption className="sr-only">
          Player-prop markets. Fair is the model median; volume is the model mean; divergence is
          model fair minus captured line. Statuses: model only, observed-unverified, verified, stale,
          unavailable.
        </caption>
        <thead>
          <tr className="bg-workscreen text-left">
            <th scope="col" className="w-8 px-2 py-2.5" aria-label="Save" />
            <th scope="col" className="px-2 py-2.5 text-left text-[11px] font-medium tracking-wide text-text-muted">Player</th>
            <th scope="col" className="px-2 py-2.5 text-left text-[11px] font-medium tracking-wide text-text-muted">Matchup</th>
            <th scope="col" className="px-2 py-2.5 text-left text-[11px] font-medium tracking-wide text-text-muted">Market</th>
            <th scope="col" className="px-3 py-2.5 text-right text-[11px] font-medium tracking-wide text-text-muted">Fair (median)</th>
            <th scope="col" className="px-3 py-2.5 text-right text-[11px] font-medium tracking-wide text-text-muted">Volume (mean)</th>
            <th scope="col" className="px-3 py-2.5 text-right text-[11px] font-medium tracking-wide text-text-muted">Captured line</th>
            <th scope="col" className="px-3 py-2.5 text-right text-[11px] font-medium tracking-wide text-text-muted">Divergence</th>
            <th scope="col" className="px-3 py-2.5 text-left text-[11px] font-medium tracking-wide text-text-muted">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const game = gameFor(row.player.gameId);
            const home = game.home === row.player.team;
            const opp = home ? game.away : game.home;
            const saved = savedPlayers.includes(row.player.id);
            return (
              <tr
                key={row.key}
                tabIndex={0}
                onClick={() => openDrawer(row.player.id, row.market)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openDrawer(row.player.id, row.market);
                  }
                }}
                className="hairline-t cursor-pointer border-hairline bg-panel transition-colors hover:bg-workscreen focus-visible:bg-workscreen"
              >
                <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => toggleSaved(row.player.id)}
                    aria-label={saved ? `Remove ${row.player.name} from saved` : `Save ${row.player.name}`}
                    aria-pressed={saved}
                    className="flex h-6 w-6 items-center justify-center rounded-[2px] text-text-muted transition-colors hover:text-sapphire"
                  >
                    <Star
                      className={cn("h-3.5 w-3.5", saved && "fill-sapphire text-sapphire")}
                      aria-hidden
                    />
                  </button>
                </td>
                <td className="whitespace-nowrap px-2 py-2">
                  <span className="flex items-center gap-2">
                    <TeamMark abbr={row.player.team} size={24} />
                    <span className="font-medium text-text">{row.player.name}</span>
                    <span className="font-data text-[10px] text-text-muted">{row.player.pos}</span>
                    {row.player.injury !== "OK" ? (
                      <span
                        className="rounded-[2px] bg-caution/10 px-1 py-px font-data text-[9px] font-medium text-caution"
                        title={row.player.injuryNote ?? "Questionable"}
                      >
                        Q
                      </span>
                    ) : null}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-xs text-text-muted">
                  <span className="font-data">
                    {home ? "vs" : "@"} {opp}
                  </span>
                  <span className="ml-1.5 text-[10px]">
                    {new Date(game.kickoff).toLocaleDateString("en-US", { weekday: "short" })}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-xs text-text">
                  {MARKET_META[row.market].label}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-data text-sapphire">
                  {fmt(row.fairLine, row.fairLine % 1 === 0 ? 0 : 1)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-data text-text">
                  {fmt(row.projectedVolume, 1)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-data text-text">
                  {row.quote ? (
                    <span>
                      {row.quote.line}
                      <span className="ml-1.5 text-[10px] text-text-muted">
                        {fmtOdds(row.quote.overOdds)}
                      </span>
                    </span>
                  ) : (
                    <span
                      className="text-text-muted"
                      title={row.status === "UNAVAILABLE" ? (row.unavailableReason ?? "Market data unavailable") : "No quote captured — model output only"}
                    >
                      —
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {row.comparison.standardizedDivergence !== null ? (
                    <span
                      className={cn(
                        "font-data",
                        Math.abs(row.comparison.standardizedDivergence) >= 0.15
                          ? "text-sapphire-hover"
                          : "text-text"
                      )}
                      title={`Fair ${fmt(row.fairLine, 1)} − line ${row.quote!.line} = ${fmtSigned(row.comparison.lineDivergence, 1)} (${fmtSigned(row.comparison.standardizedDivergence, 2)}σ)`}
                    >
                      {fmtSigned(row.comparison.lineDivergence, 1)}
                    </span>
                  ) : (
                    <span className="font-data text-text-muted">—</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <StatusChip status={row.status} />
                  {row.status === "STALE" && row.quote ? (
                    <span
                      className="ml-1.5 font-data text-[10px] text-text-muted"
                      title={`Captured ${formatAge(row.quote.capturedAt)} before snapshot — archived context, not current`}
                    >
                      ·{formatAge(row.quote.capturedAt)}
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- mobile cards ---------- */

function BoardCards({ rows }: { rows: BoardRow[] }) {
  const { openDrawer, savedPlayers, toggleSaved } = useApp();

  if (rows.length === 0) return <BoardEmpty />;

  return (
    <div role="list" className="flex flex-col gap-2">
      {rows.map((row) => {
        const game = gameFor(row.player.gameId);
        const home = game.home === row.player.team;
        const opp = home ? game.away : game.home;
        const saved = savedPlayers.includes(row.player.id);
        return (
          <button
            key={row.key}
            type="button"
            role="listitem"
            onClick={() => openDrawer(row.player.id, row.market)}
            className="rounded-[10px] border border-hairline bg-panel p-3 text-left transition-colors active:bg-workscreen"
          >
            <div className="flex items-center gap-2">
              <TeamMark abbr={row.player.team} size={26} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 truncate text-sm font-medium text-text">
                  {row.player.name}
                  {row.player.injury !== "OK" ? (
                    <span className="rounded-[3px] bg-caution/10 px-1 font-data text-[9px] text-caution">Q</span>
                  ) : null}
                </p>
                <p className="truncate text-[11px] text-text-muted">
                  {row.player.pos} · {home ? "vs" : "@"} {opp} · {MARKET_META[row.market].label}
                </p>
              </div>
              <StatusChip status={row.status} />
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-hairline pt-2.5">
              <div>
                <p className="label-micro">Fair</p>
                <p className="font-data text-sm text-sapphire">
                  {fmt(row.fairLine, row.fairLine % 1 === 0 ? 0 : 1)}
                </p>
              </div>
              <div>
                <p className="label-micro">Mean</p>
                <p className="font-data text-sm text-text">{fmt(row.projectedVolume, 1)}</p>
              </div>
              <div>
                <p className="label-micro">{row.quote ? "Line" : "Divergence"}</p>
                <p className="font-data text-sm text-text">
                  {row.quote
                    ? `${row.quote.line} (${fmtOdds(row.quote.overOdds)})`
                    : row.comparison.standardizedDivergence !== null
                      ? fmtSigned(row.comparison.lineDivergence, 1)
                      : "—"}
                </p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

/* ---------- empty state ---------- */

function BoardEmpty() {
  const { setFilters, route } = useApp();
  const sport: Sport = route.sport ?? "nfl";
  const total = getBoardFor(sport).length;
  const quoted = getBoardFor(sport).filter((r) => r.quote).length;
  return (
    <div className="flex flex-col items-center gap-3 rounded-[10px] border border-dashed border-hairline px-6 py-16 text-center">
      <p className="text-sm text-text">No markets match the current filters</p>
      <p className="max-w-xs text-xs leading-relaxed text-text-muted">
        Try clearing a status filter or searching a different player or team. All {total}{" "}
        {SPORT_META[sport].label} markets are modeled; quotes exist for {quoted}.
      </p>
      <button
        type="button"
        onClick={() =>
          setFilters({ query: "", market: "all", statuses: new Set() })
        }
        className="rounded-[6px] border border-hairline bg-panel px-3 py-1.5 text-xs font-medium text-text transition-colors hover:border-sapphire/50"
      >
        Reset filters
      </button>
    </div>
  );
}

/* ---------- the board ---------- */

export function MarketBoard() {
  const { filters, route, drawer, boardScrollY, setBoardScrollY } = useApp();
  const boardRef = useRef<HTMLDivElement>(null);
  const restoredRef = useRef(false);
  const sport: Sport = route.sport ?? "nfl";
  const sportBoard = useMemo(() => getBoardFor(sport), [sport]);

  const rows = useMemo(() => {
    let list = sportBoard;
    const q = filters.query.trim().toLowerCase();
    if (filters.market !== "all") list = list.filter((r) => r.market === filters.market);
    if (q) {
      list = list.filter((r) => {
        const game = gameFor(r.player.gameId);
        const opp = game.home === r.player.team ? game.away : game.home;
        return (
          r.player.name.toLowerCase().includes(q) ||
          r.player.team.toLowerCase().includes(q) ||
          opp.toLowerCase().includes(q) ||
          r.player.pos.toLowerCase().includes(q)
        );
      });
    }
    if (filters.statuses.size > 0) {
      list = list.filter((r) => filters.statuses.has(r.status));
    }
    const dir = filters.sortDir === "desc" ? -1 : 1;
    const sorted = [...list].sort((a, b) => {
      switch (filters.sortKey) {
        case "player":
          return a.player.name.localeCompare(b.player.name) * -dir;
        case "volume":
          return (a.projectedVolume - b.projectedVolume) * dir;
        case "status": {
          const order: EvidenceStatus[] = [
            "VERIFIED",
            "OBSERVED_UNVERIFIED",
            "STALE",
            "MODEL_ONLY",
            "UNAVAILABLE",
            "ARCHIVED",
          ];
          return (order.indexOf(a.status) - order.indexOf(b.status)) * -dir;
        }
        default: {
          const az = Math.abs(a.comparison.standardizedDivergence ?? -1);
          const bz = Math.abs(b.comparison.standardizedDivergence ?? -1);
          return (az - bz) * dir;
        }
      }
    });
    return sorted;
  }, [filters, sportBoard]);

  // keep deep-linked market tab in sync (#/markets/receiving_yards); reset
  // the market filter when the league context changes and it no longer applies
  useEffect(() => {
    if (route.boardMarket && route.boardMarket !== filters.market) {
      useApp.getState().setFilters({ market: route.boardMarket });
    } else if (
      filters.market !== "all" &&
      !MARKET_KEYS_BY_SPORT[sport].includes(filters.market as MarketKey)
    ) {
      useApp.getState().setFilters({ market: "all" });
    }
  }, [route.boardMarket, filters.market, sport]);

  // record scroll while the board is visible (drawer keeps it mounted)
  useEffect(() => {
    const onScroll = () => setBoardScrollY(window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [setBoardScrollY]);

  // restore scroll when returning from a player page
  useEffect(() => {
    if (!restoredRef.current && !drawer) {
      restoredRef.current = true;
      if (boardScrollY > 0) {
        requestAnimationFrame(() => window.scrollTo({ top: boardScrollY }));
      }
    }
  }, [boardScrollY, drawer]);

  return (
    <div ref={boardRef} className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="label-micro">NFL · Week 9 · snapshot data</p>
          <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text">
            Market board
          </h1>
        </div>
        <p className="text-xs leading-relaxed text-text-muted">
          Fair = model median · Volume = model mean · Divergence = fair − captured line
          <span className="block text-[10px]">
            No bet recommendations are made anywhere in this terminal.
          </span>
        </p>
      </header>
      <BoardFilters />
      <div className="hidden lg:block">
        <BoardTable rows={rows} />
      </div>
      <div className="lg:hidden">
        <BoardCards rows={rows} />
      </div>
      <p className="text-[11px] leading-relaxed text-text-muted">
        Showing <span className="font-data text-text">{rows.length}</span> of 72 Week 9 markets ·
        every figure derives from the published distribution parameters and captured-quote state.
      </p>
      {drawer ? <MarketDetailSheet playerId={drawer.playerId} market={drawer.market} /> : null}
    </div>
  );
}
