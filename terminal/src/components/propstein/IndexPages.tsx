"use client";

/* PropStein — player research index (public, SEO-shaped)
   and the saved research list. Both share the board's
   card hierarchy and status vocabulary. The index follows
   the league context; the saved list spans both leagues. */

import { useMemo, useState } from "react";
import { useApp } from "@/lib/propstein/router";
import { getBoard, type BoardRow } from "@/lib/propstein/derive";
import { gameFor, TEAMS } from "@/lib/propstein/data";
import {
  MARKET_KEYS_BY_SPORT,
  MARKET_META,
  SPORT_META,
  type MarketKey,
  type Sport,
} from "@/lib/propstein/types";
import { fmt, formatKickoff } from "@/lib/propstein/format";
import { Panel, TeamMark, StatusChip } from "./primitives";
import { cn } from "@/lib/utils";
import { Search, Star, X, AlertTriangle } from "lucide-react";

const POS_BY_SPORT: Record<Sport, string[]> = {
  nfl: ["WR", "TE", "RB"],
  nba: ["PG", "SG", "SF", "PF", "C"],
};

export function PlayerIndexPage() {
  const { setRoute, route } = useApp();
  const sport: Sport = route.sport ?? "nfl";
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState<string>("ALL");

  const players = useMemo(() => {
    const primary = MARKET_KEYS_BY_SPORT[sport][0];
    const board = getBoard().filter((r) => r.player.sport === sport && r.market === primary);
    const q = query.trim().toLowerCase();
    return board.filter((r) => {
      if (posFilter !== "ALL" && r.player.pos !== posFilter) return false;
      if (!q) return true;
      const game = gameFor(r.player.gameId);
      const opp = game.home === r.player.team ? game.away : game.home;
      return (
        r.player.name.toLowerCase().includes(q) ||
        r.player.team.toLowerCase().includes(q) ||
        opp.toLowerCase().includes(q)
      );
    });
  }, [query, posFilter, sport]);

  const markets = MARKET_KEYS_BY_SPORT[sport];

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="label-micro">
            {SPORT_META[sport].label} · {sport === "nfl" ? "Week 9" : "Friday Nov 6 slate"} · public index
          </p>
          <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text">
            Player research
          </h1>
          <p className="mt-1 text-xs text-text-muted">
            {players.length} modeled players · each with full distribution research for{" "}
            {markets.map((m) => MARKET_META[m].label.toLowerCase()).join(", ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded-[6px] border border-hairline" role="tablist" aria-label="Position filter">
            {["ALL", ...POS_BY_SPORT[sport]].map((p) => (
              <button
                key={p}
                role="tab"
                type="button"
                aria-selected={posFilter === p}
                onClick={() => setPosFilter(p)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors",
                  posFilter === p ? "bg-sapphire-surface text-sapphire" : "bg-panel text-text-muted hover:text-text"
                )}
              >
                {p}
              </button>
            ))}
          </div>
          <label className="flex h-8 w-full items-center gap-2 rounded-[6px] border border-hairline bg-panel px-2.5 sm:w-56">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Player or team…"
              aria-label="Filter players"
              className="h-full min-w-0 flex-1 bg-transparent text-xs text-text outline-none placeholder:text-text-muted"
            />
            {query ? (
              <button type="button" onClick={() => setQuery("")} aria-label="Clear" className="text-text-muted hover:text-text">
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            ) : null}
          </label>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {players.map((row) => (
          <PlayerIndexCard key={row.player.id} row={row} markets={markets} />
        ))}
      </div>

      {players.length === 0 ? (
        <Panel className="flex flex-col items-center gap-2 p-10 text-center">
          <p className="text-sm text-text">No players match the filter</p>
          <p className="text-xs text-text-muted">Try a different name, team, or position.</p>
        </Panel>
      ) : null}
    </div>
  );
}

function PlayerIndexCard({ row, markets }: { row: BoardRow; markets: MarketKey[] }) {
  const { setRoute } = useApp();
  const game = gameFor(row.player.gameId);
  const home = game.home === row.player.team;
  const opp = home ? game.away : game.home;
  const rows = markets.map((m) => getBoard().find((r) => r.key === `${row.player.id}:${m}`)!);
  const cols = markets.length === 2 ? "grid-cols-2" : "grid-cols-3";

  return (
    <button
      type="button"
      onClick={() => setRoute({ view: "player", playerId: row.player.id, market: markets[0] })}
      className="group rounded-[10px] border border-hairline bg-panel p-3.5 text-left transition-colors hover:border-sapphire/40"
    >
      <div className="flex items-center gap-2.5">
        <TeamMark abbr={row.player.team} size={32} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate text-sm font-medium text-text">
            {row.player.name}
            <span className="font-data text-[10px] text-text-muted">{row.player.pos}</span>
          </p>
          <p className="truncate text-[11px] text-text-muted">
            {TEAMS[row.player.team].name} · {home ? "vs" : "@"} {opp} ·{" "}
            {formatKickoff(game.kickoff)}
          </p>
        </div>
        {row.player.injury === "QUESTIONABLE" ? (
          <span
            className="flex items-center gap-1 rounded-[4px] bg-caution/10 px-1 py-px text-[9px] font-medium text-caution"
            title={row.player.injuryNote ?? "Questionable designation"}
          >
            <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
            Q
          </span>
        ) : null}
      </div>
      <div className={cn("mt-3 grid gap-2 border-t border-hairline pt-2.5", cols)}>
        {rows.map(
          (r) =>
            r && (
              <div key={r.market}>
                <p className="label-micro">{MARKET_META[r.market].short} · fair / mean</p>
                <p className="mt-0.5 font-data text-xs text-sapphire">
                  {fmt(r.fairLine, r.fairLine % 1 === 0 ? 0 : 1)}{" "}
                  <span className="text-text-muted">/</span> {fmt(r.projectedVolume, 1)}
                </p>
                <div className="mt-1">
                  <StatusChip status={r.status} size="xs" />
                </div>
              </div>
            )
        )}
      </div>
    </button>
  );
}

export function SavedPage() {
  const { savedPlayers, setRoute, toggleSaved, recentSearches, setSearchOpen } = useApp();
  const board = getBoard();

  const saved = board.filter(
    (r) => r.market === MARKET_KEYS_BY_SPORT[r.player.sport][0] && savedPlayers.includes(r.player.id)
  );

  return (
    <div className="flex flex-col gap-5">
      <header>
        <p className="label-micro">Your research list</p>
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text">
          Saved research
        </h1>
        <p className="mt-1 text-xs text-text-muted">
          Watchlist, alerts, and saved searches — with their current evidence state at a glance
        </p>
      </header>

      {saved.length === 0 ? (
        <Panel className="flex flex-col items-center gap-3 p-12 text-center">
          <Star className="h-5 w-5 text-text-muted" aria-hidden />
          <p className="text-sm text-text">Nothing on the watchlist yet</p>
          <p className="max-w-xs text-xs leading-relaxed text-text-muted">
            Star players from the market board or any research page to follow their distributions,
            quotes, and evidence states here.
          </p>
          <button
            type="button"
            onClick={() => setRoute({ view: "markets" })}
            className="rounded-[6px] border border-sapphire/40 bg-sapphire-surface px-3 py-1.5 text-xs font-medium text-sapphire transition-colors hover:border-sapphire/60"
          >
            Browse the market board
          </button>
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {saved.map((row) => {
            const markets = MARKET_KEYS_BY_SPORT[row.player.sport];
            const rows = markets.map(
              (m) => getBoard().find((r) => r.key === `${row.player.id}:${m}`)!
            );
            return (
              <Panel key={row.player.id} className="p-3.5">
                <div className="flex items-center gap-2.5">
                  <TeamMark abbr={row.player.team} size={30} />
                  <button
                    type="button"
                    onClick={() =>
                      setRoute({ view: "player", playerId: row.player.id, market: markets[0] })
                    }
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-medium text-text transition-colors group-hover:text-sapphire">
                      {row.player.name}
                    </p>
                    <p className="truncate text-[11px] text-text-muted">
                      {SPORT_META[row.player.sport].label} · {row.player.role}
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleSaved(row.player.id)}
                    aria-label={`Remove ${row.player.name} from saved`}
                    className="flex h-7 w-7 items-center justify-center rounded-[6px] text-text-muted hover:text-text"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                <div
                  className={cn(
                    "mt-2.5 grid gap-2 border-t border-hairline pt-2.5 text-[11px]",
                    markets.length === 2 ? "grid-cols-2" : "grid-cols-3"
                  )}
                >
                  {rows.map(
                    (r) =>
                      r && (
                        <span key={r.market} className="flex items-center justify-between gap-1">
                          <span className="text-text-muted">{MARKET_META[r.market].short}</span>
                          <StatusChip status={r.status} size="xs" />
                        </span>
                      )
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
      )}

      {/* saved searches — recent queries from command search */}
      <Panel className="p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-text">Saved searches</h2>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="rounded-[6px] border border-sapphire/40 bg-sapphire-surface px-2.5 py-1 text-[11px] font-medium text-sapphire transition-colors hover:border-sapphire/60"
          >
            New search ⌘K
          </button>
        </div>
        {recentSearches.length === 0 ? (
          <p className="mt-2 text-xs leading-relaxed text-text-muted">
            No saved searches yet. Queries you run through command search are kept here for this
            session.
          </p>
        ) : (
          <ul className="mt-2.5 flex flex-wrap gap-2">
            {recentSearches.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => setSearchOpen(true)}
                  className="rounded-[6px] border border-hairline bg-workspace px-2.5 py-1 font-data text-[11px] text-text transition-colors hover:border-sapphire/40 hover:text-sapphire"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
