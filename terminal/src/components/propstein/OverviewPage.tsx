"use client";

/* ============================================================
   PropStein — Overview (player-first research homepage)
   First viewport is research content, not infrastructure:
   sport context → Player Research heading → prominent search →
   market tabs → scheduled games → player research cards →
   compact model status. League context follows the route.
   ============================================================ */

import { useEffect, useState } from "react";
import { useApp } from "@/lib/propstein/router";
import { boardSummary, largestDivergences, getBoardFor, type BoardRow } from "@/lib/propstein/derive";
import { gamesForSport, gameFor, TEAMS } from "@/lib/propstein/data";
import {
  GOVERNANCE,
  MARKET_KEYS_BY_SPORT,
  MARKET_META,
  SPORT_META,
  type MarketKey,
  type Sport,
} from "@/lib/propstein/types";
import { ARCHIVE_COHORT } from "@/lib/propstein/archive";
import { fmt, fmtSigned, fmtOdds, fmtPct, formatAge, formatKickoff, formatKickoffShort } from "@/lib/propstein/format";
import { overProb, breakEvenProb } from "@/lib/propstein/model";
import { Panel, SectionHeading, TeamMark, StatusChip } from "./primitives";
import { SparkDistribution } from "./charts/SparkDistribution";
import { cn } from "@/lib/utils";
import {
  Search,
  ArrowRight,
  BookOpen,
  LineChart,
  Sigma,
  ShieldCheck,
  GitCommitHorizontal,
  Clock,
  Snowflake,
} from "lucide-react";

export function OverviewPage() {
  const { route, setRoute, setSearchOpen, setSport } = useApp();
  const sport: Sport = route.sport ?? "nfl";
  const summary = boardSummary(sport);
  const board = getBoardFor(sport);
  const games = gamesForSport(sport);
  const sportMarkets = MARKET_KEYS_BY_SPORT[sport];
  const [market, setMarket] = useState<MarketKey>(sportMarkets[0]);

  // reset the selected market when the league context changes
  useEffect(() => {
    setMarket(MARKET_KEYS_BY_SPORT[sport][0]);
  }, [sport]);

  const marketRows = board
    .filter((r) => r.market === market)
    .sort((a, b) => b.projectedVolume - a.projectedVolume)
    .slice(0, 9);
  const divergences = largestDivergences(sport, 5);
  const meta = MARKET_META[market];

  return (
    <div className="flex flex-col gap-6">
      {/* ——— research header ——— */}
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="label-micro">
              {SPORT_META[sport].label} · {sport === "nfl" ? "Regular season · Week 9" : "Friday slate · Nov 6"} ·{" "}
              {summary.games} games
            </p>
            <h1 className="mt-1 font-display text-[28px] font-semibold tracking-tight text-text">
              Player Research
            </h1>
            <p className="mt-1 text-xs text-text-muted">
              {summary.markets} modeled markets · {summary.players} players · full distributions,
              captured quotes, public evaluation
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="flex h-11 w-full max-w-[420px] items-center gap-2.5 rounded-[8px] border border-hairline bg-panel px-3.5 text-left text-sm text-text-muted transition-colors hover:border-sapphire/40"
            aria-label="Open command search"
          >
            <Search className="h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1 truncate">Search players, teams, markets…</span>
            <kbd className="rounded-[3px] border border-hairline bg-workspace px-1.5 py-0.5 font-data text-[10px] text-text-muted">
              ⌘K
            </kbd>
          </button>
        </div>

        {/* league switcher — mobile (desktop lives in the top bar) */}
        <div className="flex items-center gap-1.5 lg:hidden" role="tablist" aria-label="League">
          {(["nfl", "nba"] as Sport[]).map((s) => {
            const active = sport === s;
            return (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setSport(s)}
                className={cn(
                  "rounded-[6px] px-3 py-1.5 text-xs font-semibold transition-colors",
                  active
                    ? "bg-sapphire/12 text-sapphire shadow-[inset_0_0_0_1px_rgba(56,189,248,0.35)]"
                    : "border border-hairline bg-panel text-text-muted"
                )}
              >
                {SPORT_META[s].label}
              </button>
            );
          })}
          {["MLB", "NHL", "UFC"].map((s) => (
            <button
              key={s}
              type="button"
              disabled
              aria-label={`${s} — not yet modeled`}
              className="cursor-not-allowed rounded-[6px] border border-hairline bg-panel px-3 py-1.5 text-xs font-semibold text-text-muted/50"
            >
              {s}
            </button>
          ))}
        </div>

        {/* market tabs */}
        <div
          className="flex items-center gap-2 overflow-x-auto pb-px"
          role="tablist"
          aria-label="Market"
        >
          {sportMarkets.map((m) => {
            const active = m === market;
            const rows = board.filter((r) => r.market === m);
            const quoted = rows.filter((r) => r.quote).length;
            return (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setMarket(m)}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-[8px] border px-3.5 py-2 text-xs font-medium transition-colors",
                  active
                    ? "border-sapphire/50 bg-sapphire-surface text-sapphire"
                    : "border-hairline bg-panel text-text hover:border-sapphire/30"
                )}
              >
                {MARKET_META[m].label}
                <span className="font-data text-[10px] text-text-muted">{quoted} quoted</span>
              </button>
            );
          })}
        </div>
      </header>

      {/* ——— scheduled games ——— */}
      <section aria-label="Scheduled games">
        <p className="label-micro mb-2.5">
          {sport === "nfl" ? "Week 9 slate" : "Friday slate"} · all times ET
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
          {games.map((g) => (
            <div key={g.id} className="rounded-[8px] border border-hairline bg-workspace px-2.5 py-2">
              <p className="flex items-center justify-between gap-1">
                <span className="flex items-center gap-1.5 font-data text-[11px] text-text">
                  <TeamMark abbr={g.away} size={16} />
                  <span className="text-text-muted">@</span>
                  <TeamMark abbr={g.home} size={16} />
                </span>
                <span className="shrink-0 rounded-[4px] bg-panel px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-text-muted">
                  {{ THU: "Thu", SUN_EARLY: "Sun 1p", SUN_LATE: "Sun 4p", SUN_NIGHT: "Sun 8p", MON: "Mon", FRI: "Fri", SAT: "Sat" }[g.slot] ?? g.slot}
                </span>
              </p>
              <p className="mt-1.5 font-data text-[10px] leading-snug text-text-muted">
                {formatKickoffShort(g.kickoff)}
              </p>
              <p className="mt-0.5 font-data text-[10px] leading-snug text-text-muted">
                {g.home} {g.spread > 0 ? `-${g.spread}` : `+${-g.spread}`}
                {g.total ? ` · o/u ${g.total}` : ""}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ——— player research cards ——— */}
      <section aria-label="Player research">
        <SectionHeading
          title={`${meta.label} research`}
          subtitle={`Highest projected volume · ${meta.short} · fair line (median) vs captured market`}
          action={
            <button
              type="button"
              onClick={() => setRoute({ view: "markets", sport, boardMarket: market })}
              className="flex items-center gap-1 text-xs text-sapphire transition-colors hover:text-sapphire-hover"
            >
              Open board <ArrowRight className="h-3 w-3" aria-hidden />
            </button>
          }
        />
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {marketRows.map((row) => (
            <PlayerResearchCard key={row.key} row={row} sport={sport} />
          ))}
        </div>
        {marketRows.length === 0 ? (
          <Panel className="mt-4 p-8 text-center">
            <p className="text-sm text-text">No modeled players for this market in the snapshot.</p>
          </Panel>
        ) : null}
      </section>

      {/* ——— divergences + compact model status ——— */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Panel className="p-4 lg:p-5">
          <SectionHeading
            title="Largest model–market divergences"
            subtitle={`Where the ${SPORT_META[sport].label} model median sits farthest from captured lines — research, not recommendations`}
          />
          <div className="mt-4 flex flex-col">
            {divergences.map((row) => {
              const game = gameFor(row.player.gameId);
              const home = game.home === row.player.team;
              const opp = home ? game.away : game.home;
              return (
                <button
                  key={row.key}
                  type="button"
                  onClick={() => useApp.getState().openDrawer(row.player.id, row.market)}
                  className="group flex items-center gap-3 rounded-[6px] px-2 py-2.5 text-left transition-colors hover:bg-workscreen"
                >
                  <TeamMark abbr={row.player.team} size={26} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-text">{row.player.name}</p>
                    <p className="truncate text-[11px] text-text-muted">
                      {home ? "vs" : "@"} {opp} · {MARKET_META[row.market].label} ·{" "}
                      <span className="font-data">
                        fair {fmt(row.fairLine, 1)} vs line {row.quote!.line}
                      </span>
                    </p>
                  </div>
                  <div className="hidden w-24 shrink-0 sm:block">
                    <SparkDistribution
                      law={row.projection.law}
                      market={row.market}
                      quoteLine={row.quote!.line}
                      height={34}
                    />
                  </div>
                  <div className="shrink-0 text-right">
                    <p
                      className={cn(
                        "font-data text-sm",
                        Math.abs(row.comparison.standardizedDivergence!) >= 0.25
                          ? "text-sapphire-hover"
                          : "text-text"
                      )}
                    >
                      {fmtSigned(row.comparison.lineDivergence, 1)}
                    </p>
                    <p className="font-data text-[10px] text-text-muted">
                      {fmtSigned(row.comparison.standardizedDivergence, 2)}σ
                    </p>
                  </div>
                  <StatusChip status={row.status} size="xs" />
                </button>
              );
            })}
          </div>
          <p className="mt-3 border-t border-hairline pt-3 text-[10px] leading-snug text-text-muted">
            Divergence = model fair (median) − captured line, in model standard deviations. Quotes
            carry capture timestamps and verification states; stale captures are excluded from this
            list.
          </p>
        </Panel>

        {/* compact model status + research library */}
        <div className="flex flex-col gap-3">
          <Panel className="p-4 lg:p-5">
            <SectionHeading
              title="Model status"
              subtitle="Public evidence posture at the snapshot instant"
              action={
                <button
                  type="button"
                  onClick={() => setRoute({ view: "performance" })}
                  className="flex items-center gap-1 text-xs text-sapphire transition-colors hover:text-sapphire-hover"
                >
                  Performance <ArrowRight className="h-3 w-3" aria-hidden />
                </button>
              }
            />
            <dl className="mt-3 space-y-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-text-muted">
                  <GitCommitHorizontal className="h-3 w-3" aria-hidden /> Model
                </dt>
                <dd className="font-data text-text">v3.2.1 · game-script conditioned</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-text-muted">
                  <Clock className="h-3 w-3" aria-hidden /> Latest capture
                </dt>
                <dd className="font-data text-text">1.2h ago · Book A feed</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-text-muted">
                  <ShieldCheck className="h-3 w-3" aria-hidden /> Verification
                </dt>
                <dd className="font-data text-text">
                  <span className="text-[--status-verified]">{summary.verified} verified</span>
                  <span className="text-text-muted"> · {summary.observed} observed · </span>
                  <span className="text-caution">{summary.stale} stale</span>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1.5 text-text-muted">
                  <Snowflake className="h-3 w-3" aria-hidden /> Evidence gate
                </dt>
                <dd className="font-data text-text">
                  {ARCHIVE_COHORT.evaluable} / {GOVERNANCE.confirmatoryThreshold} · tiers frozen
                </dd>
              </div>
            </dl>
            <p className="mt-3 border-t border-hairline pt-3 text-[10px] leading-snug text-text-muted">
              Snapshot {`Wed Nov 4, 2026 · 2:15 PM ET`} — frozen capture, never presented as live.
              Historical evaluation covers {ARCHIVE_COHORT.evaluable} evaluable NFL markets; NBA
              markets have no settled history yet.
            </p>
          </Panel>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 xl:grid-cols-1">
            {[
              {
                icon: BookOpen,
                title: "Methodology",
                desc: "Negative Binomial counts, Gamma volume, and the exact compound law — with published parameters.",
                target: "#/research/methodology",
                tag: "research",
              },
              {
                icon: Sigma,
                title: "Value boundaries",
                desc: "How no-value bands are derived from break-even probabilities and the model distribution.",
                target: "#/research/value-boundaries",
                tag: "research",
              },
              {
                icon: LineChart,
                title: "Performance & audit",
                desc: `Full-board CLV (${ARCHIVE_COHORT.evaluable} evaluable markets), calibration, model versions, limitations.`,
                target: "#/performance",
                tag: "audit",
              },
            ].map((card) => (
              <button
                key={card.title}
                type="button"
                onClick={() => (window.location.hash = card.target.slice(1))}
                className="group flex flex-col rounded-[10px] border border-hairline bg-panel p-4 text-left transition-colors hover:border-sapphire/40"
              >
                <card.icon className="h-4 w-4 text-sapphire" aria-hidden />
                <p className="mt-2.5 text-[13px] font-medium text-text">{card.title}</p>
                <p className="mt-1 flex-1 text-[11px] leading-relaxed text-text-muted">{card.desc}</p>
                <p className="mt-3 font-data text-[10px] text-text-muted">{card.tag}</p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- player research card ---------- */

function PlayerResearchCard({ row, sport }: { row: BoardRow; sport: Sport }) {
  const game = gameFor(row.player.gameId);
  const home = game.home === row.player.team;
  const oppAbbr = home ? game.away : game.home;
  const meta = MARKET_META[row.market];
  const modelOver = row.quote ? overProb(row.quote.line, row.projection.law) : null;
  const edge =
    modelOver !== null && row.quote
      ? modelOver - breakEvenProb(row.quote.overOdds)
      : null;

  return (
    <button
      type="button"
      onClick={() => useApp.getState().setRoute({ view: "player", playerId: row.player.id, market: row.market })}
      className="group flex flex-col gap-3 rounded-[10px] border border-hairline bg-panel p-4 text-left transition-colors hover:border-sapphire/40"
    >
      {/* identity */}
      <div className="flex items-start gap-3">
        <TeamMark abbr={row.player.team} size={36} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-text">{row.player.name}</p>
          <p className="mt-0.5 truncate text-[11px] text-text-muted">
            {row.player.pos} · {home ? "vs" : "@"} {TEAMS[oppAbbr].abbr} ·{" "}
            {sport === "nfl" ? `WK ${game.week}` : formatKickoff(game.kickoff)}
          </p>
        </div>
        <StatusChip status={row.status} size="xs" />
      </div>

      {/* fair / mean / market */}
      <div className="grid grid-cols-3 items-end gap-2">
        <div>
          <p className="label-micro">Fair line</p>
          <p className="mt-1 font-data text-xl leading-none text-sapphire">
            {fmt(row.fairLine, row.fairLine % 1 === 0 ? 0 : 1)}
          </p>
          <p className="mt-1 text-[9px] text-text-muted">median · {meta.unit}</p>
        </div>
        <div>
          <p className="label-micro">Projection</p>
          <p className="mt-1 font-data text-xl leading-none text-mint">
            {fmt(row.projectedVolume, 1)}
          </p>
          <p className="mt-1 text-[9px] text-text-muted">mean · {meta.unit}</p>
        </div>
        <div>
          <p className="label-micro">Market</p>
          {row.quote ? (
            <>
              <p className="mt-1 font-data text-xl leading-none text-text">{row.quote.line}</p>
              <p className="mt-1 font-data text-[9px] text-text-muted">
                {fmtOdds(row.quote.overOdds)} / {fmtOdds(row.quote.underOdds)} ·{" "}
                {formatAge(row.quote.capturedAt)} ago
              </p>
            </>
          ) : (
            <>
              <p className="mt-1 font-data text-xl leading-none text-text-muted">—</p>
              <p className="mt-1 text-[9px] text-text-muted">
                {row.status === "UNAVAILABLE" ? "not offered" : "no quote"}
              </p>
            </>
          )}
        </div>
      </div>

      {/* distribution sparkline + edge */}
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <SparkDistribution
            law={row.projection.law}
            market={row.market}
            quoteLine={row.quote?.line ?? null}
            height={38}
          />
        </div>
        {edge !== null && row.quote ? (
          <div className="shrink-0 text-right">
            <p
              className={cn(
                "font-data text-sm leading-none",
                Math.abs(edge) >= 0.02 ? "text-sapphire-hover" : "text-text"
              )}
            >
              {fmtSigned(edge * 100, 1)}%
            </p>
            <p className="mt-1 font-data text-[9px] text-text-muted">
              P(o {row.quote.line}) {fmtPct(modelOver, 0)}
            </p>
          </div>
        ) : (
          <p className="shrink-0 font-data text-[9px] text-text-muted">model only</p>
        )}
      </div>

      <p className="flex items-center gap-1 text-[11px] font-medium text-sapphire transition-colors group-hover:text-sapphire-hover">
        Inspect distribution
        <ArrowRight className="h-3 w-3" aria-hidden />
      </p>
    </button>
  );
}
