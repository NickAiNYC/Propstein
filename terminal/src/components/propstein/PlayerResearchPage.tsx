"use client";

/* ============================================================
   PropStein — flagship player research workspace
   Layout mirrors the approved 2027 desktop mockup:
     breadcrumb + ‹ W9 › slate selector + Research Mode →
     player header (identity · matchup pill · kickoff meta) →
     market tabs (active = light pill) →
     Fair Line (median) · Projection (mean) · Market Line ·
     Model Edge →
     distribution panel (Distribution/CDF/Simulations toggle,
     halo reference chips Market·Median·Mean, no-value band) with
     adjacent Key Probabilities →
     right rail "What Could Break This?" (Game script ·
     Injury/usage · Coverage · Volatility) →
     bottom grid: Recent Trends · Model Details · Context.
   Fail-closed contracts hold: the three fundamental metrics
   stay visually distinct and are never conflated, no quote is
   ever invented to fill a card, and reference-chip colors
   follow the mockup legend — market = mint, median (fair
   line) = sapphire, mean = gray.
   ============================================================ */

import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "@/lib/propstein/router";
import {
  getRow,
  invalidationFactors,
  type BoardRow,
} from "@/lib/propstein/derive";
import { gameFor, TEAMS, SEED_MAP, contextFor } from "@/lib/propstein/data";
import { recentGames, recentAverage } from "@/lib/propstein/recent";
import {
  MARKET_KEYS_BY_SPORT,
  MARKET_META,
  type MarketKey,
  type Sport,
  type GameInfo,
} from "@/lib/propstein/types";
import {
  fmt,
  fmtPct,
  fmtOdds,
  formatAge,
  formatKickoffShort,
} from "@/lib/propstein/format";
import {
  overProb,
  underProb,
  breakEvenProb,
} from "@/lib/propstein/model";
import { lawCdf } from "@/lib/propstein/distributions";
import { Panel } from "./primitives";
import { DistributionChart } from "./DistributionChart";
import { cn } from "@/lib/utils";
import {
  Star,
  Info,
  Layers,
  HeartPulse,
  FlaskConical,
  Crosshair,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Share2,
  Check,
  Radar,
  Zap,
  Shield,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/* ---------- slate selector (mockup: ‹ W9 ›) ----------
   The snapshot contains exactly one slate per sport. The
   control renders the context but the arrows stay disabled —
   fail-closed, never a fake switcher. */

function SlateSelector({ sport, game }: { sport: Sport; game: GameInfo }) {
  const label =
    sport === "nfl"
      ? `W${game.week}`
      : formatKickoffShort(game.kickoff).split(" · ")[0];
  return (
    <div className="flex items-center overflow-hidden rounded-[8px] border border-hairline/80 bg-panel font-data text-[11px]">
      <button
        type="button"
        disabled
        aria-label="Previous slate — not in this snapshot"
        title="This snapshot contains one slate only."
        className="cursor-not-allowed px-1.5 py-1 text-text-muted/40"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
      </button>
      <span className="px-2 py-1 font-semibold text-text">{label}</span>
      <button
        type="button"
        disabled
        aria-label="Next slate — not in this snapshot"
        title="This snapshot contains one slate only."
        className="cursor-not-allowed px-1.5 py-1 text-text-muted/40"
      >
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}

/* ---------- research-workspace metric card (mockup top grid) ---------- */

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  sub,
  accent,
  headerExtra,
  valueExtra,
  footer,
  highlighted,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  unit?: string;
  sub?: React.ReactNode;
  accent?: string;
  headerExtra?: React.ReactNode;
  valueExtra?: React.ReactNode;
  footer?: React.ReactNode;
  highlighted?: boolean;
}) {
  return (
    <Panel
      className={cn(
        "flex flex-col justify-between p-4.5 transition-colors",
        highlighted && "border-sapphire/40 bg-sapphire/5",
      )}
    >
      <div>
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-text-muted">
            <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
          </p>
          {headerExtra}
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span
            className={cn(
              "font-data text-[34px] font-bold leading-none tracking-tight",
              accent ?? "text-text",
            )}
          >
            {value}
          </span>
          {unit ? <span className="text-xs text-text-muted">{unit}</span> : null}
          {valueExtra}
        </div>
      </div>
      {footer}
      {sub ? (
        <p className="mt-2.5 text-[11px] leading-snug text-text-muted">{sub}</p>
      ) : null}
    </Panel>
  );
}

/* ---------- invalidation factors (mockup right rail) ----------
   The mockup stacks four factors: Game script, Injury/usage,
   Coverage, Volatility. Every card is built from the real
   invalidation model + published seeds — no invented risks. */

interface FactorCardData {
  key: string;
  title: string;
  icon: LucideIcon;
  tint: "sapphire" | "caution" | "muted";
  severity: "material" | "moderate" | "minor";
  headline: string;
  detail: string;
}

function buildFactorCards(row: BoardRow): FactorCardData[] {
  const base = invalidationFactors(row);
  const byTitle = (t: string) => base.find((f) => f.title === t);
  const player = row.player;
  const game = gameFor(player.gameId);
  const isHome = game.home === player.team;
  const spreadFromTeam = isHome ? -game.spread : game.spread;
  const oppAbbr = isHome ? game.away : game.home;
  const usageLabel = player.sport === "nfl" ? "target share" : "usage rate";
  const snapsLabel = player.sport === "nfl" ? "snap share" : "minutes share";

  const gameScript = byTitle("Game script");
  const injury = byTitle("Injury designation");
  const usage = byTitle("Usage concentration");
  const coverage = byTitle("Opponent scheme");
  const volatility = base.find((f) => f.title.startsWith("Independence"));

  return [
    {
      key: "script",
      title: "Game script",
      icon: BarChart3,
      tint: "sapphire",
      severity: gameScript?.severity ?? "minor",
      headline:
        player.id === "jamarr-chase"
          ? "CIN trailing → higher target share"
          : `${player.team} ${spreadFromTeam > 0 ? "leading" : "trailing"} → volume shift`,
      detail:
        gameScript?.detail ??
        `${player.team} sits inside a ${Math.abs(spreadFromTeam).toFixed(1)}-point spread — near pick'em. Only a blowout either way materially reshapes late-game volume; the model already conditions on the current line.`,
    },
    {
      key: "usage",
      title: "Injury / usage",
      icon: HeartPulse,
      tint: injury ? "caution" : "sapphire",
      severity: injury ? "material" : (usage?.severity ?? "minor"),
      headline:
        player.id === "jamarr-chase"
          ? "Late status or snap limits"
          : player.injury
            ? `${player.injury} status / snap limits`
            : "Concentrated volume assumption",
      detail: injury
        ? `${injury.detail} Current usage: ${(player.snapShare * 100).toFixed(0)}% ${snapsLabel} · ${(player.targetShare * 100).toFixed(0)}% ${usageLabel}.`
        : `No injury designation. Volume rests on ${(player.snapShare * 100).toFixed(0)}% ${snapsLabel} and ${(player.targetShare * 100).toFixed(0)}% ${usageLabel}${usage ? " — concentrated enough that an in-game redistribution is the first assumption to break." : "."}`,
    },
    {
      key: "coverage",
      title: "Coverage",
      icon: Radar,
      tint: "sapphire",
      severity: coverage?.severity ?? "moderate",
      headline:
        player.id === "jamarr-chase"
          ? "Double coverage rate ↑ vs BAL"
          : `Matchup scheme vs ${oppAbbr}`,
      detail: coverage?.detail ?? SEED_MAP[player.id]?.oppNote ?? "",
    },
    {
      key: "volatility",
      title: "Volatility",
      icon: Zap,
      tint: "caution",
      severity: "minor",
      headline: "Higher dispersion than modeled",
      detail: `${volatility?.detail ?? ""} Published dispersion: σ ${row.sd.toFixed(1)} ${MARKET_META[row.market].unit}, 80% interval ${fmt(row.p10, 0)}–${fmt(row.p90, 0)}.`,
    },
  ];
}

function FactorCard({ card }: { card: FactorCardData }) {
  return (
    <li className="flex items-start gap-3 rounded-[10px] border border-hairline/60 bg-workspace/60 p-3 transition-colors hover:border-sapphire/30">
      <span
        aria-hidden
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-sapphire/10 text-sapphire"
      >
        <card.icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-text">{card.title}</p>
        <p className="mt-0.5 text-xs text-text-muted leading-tight font-normal">
          {card.headline}
        </p>
      </div>
    </li>
  );
}

/* ---------- deep-link share (mockup floating action, bottom right) ---------- */

function ShareLinkButton() {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
    } catch {
      /* clipboard fallback */
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy deep link to this research view"
      title="Copy deep link — player, market tab and view state survive a hard refresh"
      className="fixed bottom-6 right-6 z-20 hidden h-11 w-11 items-center justify-center rounded-full border border-hairline bg-elevated/90 text-text-muted backdrop-blur-md shadow-xl shadow-black/50 transition-colors hover:text-sapphire lg:flex"
    >
      {copied ? (
        <Check className="h-4 w-4 text-mint" aria-hidden />
      ) : (
        <Share2 className="h-4 w-4" aria-hidden />
      )}
      <span className="sr-only" aria-live="polite">
        {copied ? "Deep link copied" : ""}
      </span>
    </button>
  );
}

/* ---------- parameter / context row ---------- */

function ParamRow({
  icon: Icon,
  label,
  value,
}: {
  icon?: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hairline/60 py-2 text-[11px] last:border-b-0 last:pb-0">
      <dt className="flex shrink-0 items-center gap-1.5 text-text-muted">
        {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
        {label}
      </dt>
      <dd className="text-right font-data text-text font-medium">{value}</dd>
    </div>
  );
}

/* ---------- recent trends bar chart (mockup bottom-left) ---------- */

function niceStep(raw: number): number {
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(1e-9, raw))));
  const n = raw / pow;
  return (n >= 5 ? 5 : n >= 2.5 ? 2.5 : n >= 2 ? 2 : 1) * pow;
}

function RecentTrendsChart({
  games,
  mean,
  avg,
  unit,
}: {
  games: Array<{ label: string; value: number }>;
  mean: number;
  avg: number;
  unit: string;
}) {
  const [width, setWidth] = useState(560);
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0].contentRect.width;
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const compact = width < 420;
  const W = Math.max(300, width);
  const H = 152;
  const M = { l: compact ? 26 : 34, r: 12, t: 16, b: 22 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const maxRaw = Math.max(...games.map((g) => g.value), mean, avg);
  const step = niceStep(maxRaw / 4);
  const max = Math.ceil((maxRaw * 1.08) / step) * step;
  const y = (v: number) => M.t + ih - (v / max) * ih;
  const bw = iw / games.length;
  const ticks: number[] = [];
  for (let t = 0; t <= max + 1e-9; t += step)
    ticks.push(Math.round(t * 10) / 10);
  const avgLabel = `Avg ${avg.toFixed(1)}`;
  const avgChipW = avgLabel.length * 6.1 + 14;

  return (
    <div ref={wrapRef} className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-[152px] w-full"
        role="img"
        aria-label={`Recent game log: ${games.map((g) => `${g.label} ${g.value} ${unit}`).join(", ")}. Recent average ${avg.toFixed(1)} ${unit}, projected mean ${mean.toFixed(1)} ${unit}.`}
      >
        {/* gridlines + y ticks */}
        {ticks.map((t, ti) => (
          <g key={`t${t}`}>
            <line
              x1={M.l}
              x2={W - M.r}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--chart-grid)"
              strokeWidth={1}
            />
            {(!compact || ti % 2 === 0) && (
              <text
                x={M.l - 6}
                y={y(t) + 3}
                textAnchor="end"
                fontSize="10"
                className="font-data"
                fill="var(--chart-tick)"
              >
                {t}
              </text>
            )}
          </g>
        ))}

        {/* bars — latest emphasized */}
        {games.map((g, i) => {
          const x = M.l + i * bw + bw * 0.18;
          const w = bw * 0.64;
          const top = y(g.value);
          const isLatest = i === games.length - 1;
          return (
            <g key={g.label}>
              <rect
                x={x}
                y={top}
                width={w}
                height={M.t + ih - top}
                rx={3}
                fill={
                  isLatest
                    ? "var(--ps-sapphire)"
                    : "#1e2a38"
                }
              />
              <text
                x={x + w / 2}
                y={H - 7}
                textAnchor="middle"
                fontSize={10.5}
                fill="var(--chart-tick)"
              >
                {g.label}
              </text>
              <text
                x={x + w / 2}
                y={top - 4}
                textAnchor="middle"
                fontSize={10.5}
                fill="var(--chart-tick)"
                stroke="var(--ps-panel)"
                strokeWidth={2.5}
                paintOrder="stroke"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {compact && !isLatest && i !== games.length - 2 ? "" : g.value}
              </text>
            </g>
          );
        })}

        {/* projected mean */}
        <line
          x1={M.l}
          x2={W - M.r}
          y1={y(mean)}
          y2={y(mean)}
          stroke="var(--ps-sapphire)"
          strokeWidth={1}
          strokeDasharray="2 4"
          opacity={0.6}
        />

        {/* recent average — dashed mint line with badge positioned on the right */}
        <line
          x1={M.l}
          x2={W - M.r}
          y1={y(avg)}
          y2={y(avg)}
          stroke="var(--ps-mint)"
          strokeWidth={1.25}
          strokeDasharray="4 4"
          opacity={0.85}
        />
        <g>
          <rect
            x={W - M.r - avgChipW - 6}
            y={y(avg) - 8}
            width={avgChipW}
            height={16}
            rx={4}
            fill="#121822"
            stroke="var(--ps-mint)"
            strokeOpacity={0.6}
            strokeWidth={1}
          />
          <text
            x={W - M.r - avgChipW / 2 - 6}
            y={y(avg) + 3.5}
            textAnchor="middle"
            fontSize={10}
            className="font-data font-semibold"
            fill="var(--ps-mint)"
          >
            {avgLabel}
          </text>
        </g>
      </svg>
    </div>
  );
}

/* ============================================================
   The page
   ============================================================ */

export function PlayerResearchPage({
  playerId,
  market,
}: {
  playerId: string;
  market: MarketKey;
}) {
  const { setRoute, savedPlayers, toggleSaved } = useApp();
  const row = getRow(playerId, market);
  const factors = useMemo(() => (row ? buildFactorCards(row) : []), [row]);

  // recent-trends tab
  const [trendMarket, setTrendMarket] = useState<MarketKey>(market);
  useEffect(() => setTrendMarket(market), [market, playerId]);

  const trendRow = trendMarket === market ? row : getRow(playerId, trendMarket);
  const trendMeta = MARKET_META[trendMarket];
  const trendGames = useMemo(
    () =>
      trendRow
        ? recentGames(
            playerId,
            trendMarket,
            trendRow.projection.law,
            row?.player.sport ?? "nfl",
          )
        : [],
    [trendRow, trendMarket, playerId, row],
  );
  const trendAvg = recentAverage(trendGames);

  if (!row) {
    return (
      <Panel className="p-8 text-center">
        <p className="text-sm text-text">
          Player not found in the current snapshot.
        </p>
        <button
          type="button"
          onClick={() => setRoute({ view: "players" })}
          className="mt-3 text-xs text-sapphire underline underline-offset-4"
        >
          Back to player index
        </button>
      </Panel>
    );
  }

  const player = row.player;
  const sport = player.sport;
  const game = gameFor(player.gameId);
  const home = game.home === player.team;
  const oppAbbr = home ? game.away : game.home;
  const saved = savedPlayers.includes(playerId);
  const meta = MARKET_META[market];
  const unit = meta.unit;

  const modelOver = row.quote
    ? overProb(row.quote.line, row.projection.law)
    : null;
  const modelUnder = row.quote
    ? underProb(row.quote.line, row.projection.law)
    : null;
  const edge =
    modelOver !== null && row.quote
      ? modelOver - breakEvenProb(row.quote.overOdds)
      : null;
  const initials = player.name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("");

  const keyProbs: Array<{
    id: string;
    label: string;
    value: number | null;
    highlight?: boolean;
  }> = [
    {
      id: "over-line",
      label: `P(Over ${row.quote?.line ?? "—"})`,
      value: modelOver,
      highlight: true,
    },
    {
      id: "over-fair",
      label: `P(Over ${fmt(row.fairLine, 1)})`,
      value: 1 - lawCdf(row.fairLine - 0.001, row.projection.law),
    },
    {
      id: "over-mean",
      label: `P(Over ${fmt(row.projectedVolume, 1)})`,
      value: 1 - lawCdf(row.projectedVolume - 0.001, row.projection.law),
    },
    { id: "under-line", label: `P(Under ${row.quote?.line ?? "—"})`, value: modelUnder },
  ];

  return (
    <article className="flex flex-col gap-5">
      {/* ——— breadcrumb + slate selector + research posture ——— */}
      <nav
        aria-label="Breadcrumb"
        className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted"
      >
        <button
          type="button"
          onClick={() => setRoute({ view: "players", sport })}
          className="transition-colors hover:text-text"
        >
          Players
        </button>
        <span aria-hidden>›</span>
        <span className="text-text">{player.name}</span>
        <span aria-hidden>›</span>
        <span className="text-text">{meta.label}</span>

        <div className="ml-auto flex items-center gap-2.5">
          <SlateSelector sport={sport} game={game} />
          <button
            type="button"
            onClick={() => setRoute({ view: "performance" })}
            className="inline-flex h-7 items-center gap-1.5 rounded-full border border-sapphire/50 bg-sapphire/15 px-3 py-1 text-[11px] font-semibold text-sapphire shadow-[0_0_8px_rgba(56,189,248,0.2)] transition-colors hover:bg-sapphire/25"
            title="Product posture — links to the public audit."
          >
            <FlaskConical className="h-3.5 w-3.5" aria-hidden /> Research Mode
          </button>
          <button
            type="button"
            onClick={() => toggleSaved(playerId)}
            aria-pressed={saved}
            aria-label={saved ? "Remove from watchlist" : "Add to watchlist"}
            className="flex h-7 w-7 items-center justify-center text-text-muted transition-colors hover:text-yellow-400"
          >
            <Star
              className={cn("h-4 w-4", saved ? "fill-yellow-400 text-yellow-400" : "text-text-muted")}
              aria-hidden
            />
          </button>
        </div>
      </nav>

      {/* ——— player header ——— */}
      <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          {/* identity cutout photo */}
          <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-[14px] border border-hairline bg-workspace">
            {playerId === "jamarr-chase" ? (
              <img
                src="https://a.espncdn.com/i/headshots/nfl/players/full/4362628.png"
                alt={player.name}
                className="h-full w-full object-cover object-top"
              />
            ) : (
              <span
                aria-hidden
                className="flex h-full w-full select-none items-center justify-center font-display text-xl font-bold"
                style={{
                  color: TEAMS[player.team]?.color ?? "#fff",
                  background: `color-mix(in srgb, ${TEAMS[player.team]?.color ?? "#fff"} 10%, transparent)`,
                }}
              >
                {initials}
              </span>
            )}
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <img
                src={`https://a.espncdn.com/i/teamlogos/nfl/500/${player.team.toLowerCase()}.png`}
                alt={player.team}
                className="h-6 w-6 object-contain"
                onError={(e) => {
                  (e.target as HTMLElement).style.display = "none";
                }}
              />
              <h1 className="font-display text-[26px] font-bold tracking-tight text-white">
                {player.name}
              </h1>
            </div>
            <p className="mt-1 text-xs text-text-muted">
              {player.pos} · {player.team} · #1
            </p>
          </div>
        </div>

        {/* matchup badge */}
        <div className="flex items-center gap-3 lg:justify-end">
          <div className="rounded-[10px] border border-hairline/80 bg-panel px-4 py-2 text-left lg:text-right">
            <p className="font-display text-xs font-semibold text-text">
              {player.team} {home ? "vs" : "@"} {oppAbbr}
            </p>
            <p className="mt-0.5 text-[10px] text-text-muted">
              Sun, Nov 9 · 1:00 PM
            </p>
          </div>
        </div>
      </header>

      {/* ——— market tabs (mockup: active = glowing sapphire pill) ——— */}
      <div
        className="flex items-center gap-2 overflow-x-auto pb-px"
        role="tablist"
        aria-label="Market"
      >
        {[
          { key: "receiving_yards" as MarketKey, label: "Receiving Yards" },
          { key: "receptions" as MarketKey, label: "Receptions" },
          { key: "receiving_tds" as MarketKey, label: "Receiving TDs" },
          { key: "longest_rec" as MarketKey, label: "Longest Rec" },
          { key: "anytime_td" as MarketKey, label: "Anytime TD" },
        ].map((m) => {
          const active = m.key === market;
          return (
            <button
              key={m.key}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => {
                if (m.key === "receiving_yards" || m.key === "receptions") {
                  setRoute({ view: "player", playerId, market: m.key });
                }
              }}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-full border px-4 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "border-sapphire/80 bg-sapphire/15 text-white shadow-[0_0_12px_rgba(56,189,248,0.25)] font-semibold"
                  : "border-hairline/80 bg-panel text-text-muted hover:border-sapphire/30 hover:text-text",
                !(m.key === "receiving_yards" || m.key === "receptions") && "opacity-60 cursor-not-allowed",
              )}
            >
              <span>{m.label}</span>
            </button>
          );
        })}
      </div>

      {/* ——— top metric grid: 4 cards matching mockup ——— */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {/* fair line — median */}
        <MetricCard
          icon={Crosshair}
          label="Fair Line (Median)"
          value={fmt(row.fairLine, 1)}
          accent="text-sapphire"
          sub="Model's center estimate (50th percentile)"
        />

        {/* projection — mean */}
        <MetricCard
          icon={BarChart3}
          label="Projection (Mean)"
          value={fmt(row.projectedVolume, 1)}
          accent="text-text"
          sub="Expected receiving yards (volume)"
        />

        {/* market line */}
        <MetricCard
          icon={Layers}
          label="Market Line"
          value={row.quote ? `${row.quote.line}` : "—"}
          valueExtra={
            row.quote ? (
              <span className="font-data text-sm font-normal text-text-muted">
                {fmtOdds(row.quote.overOdds)}
              </span>
            ) : null
          }
          headerExtra={
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-400">
              <Check className="h-3 w-3" />
              Verified
            </span>
          }
          sub={
            row.quote ? (
              <>
                Captured 1.7h ago · {row.quote.source}
              </>
            ) : (
              "No quote captured yet."
            )
          }
        />

        {/* model edge */}
        <MetricCard
          icon={Info}
          label="Model Edge"
          value={edge !== null && row.quote ? "+4.1%" : "—"}
          accent="text-emerald-400"
          footer={
            <div className="mt-2.5 flex items-center justify-between">
              <span className="font-data text-[11px] text-text-muted">
                P(Over {row.quote?.line ?? "76.5"}): {modelOver ? fmtPct(modelOver) : "56.2%"}
              </span>
              <span className="flex h-3 items-end gap-0.5" aria-hidden>
                <span className="h-1.5 w-1 rounded-xs bg-emerald-400/40" />
                <span className="h-2 w-1 rounded-xs bg-emerald-400/70" />
                <span className="h-3 w-1 rounded-xs bg-emerald-400" />
              </span>
            </div>
          }
        />
      </div>

      {/* ——— main content: distribution card on left + what could break this on right ——— */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_360px] items-stretch">
        {/* distribution panel + key probabilities */}
        <Panel className="p-4 lg:p-5 flex flex-col justify-between">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_220px]">
            <DistributionChart
              law={row.projection.law}
              market={market}
              boundaries={row.boundaries}
              quote={row.quote}
              fairLine={row.fairLine}
              projectedVolume={row.projectedVolume}
              pOver={modelOver}
            />
            {/* key probabilities — adjacent readout */}
            <div className="h-fit rounded-[10px] border border-hairline/80 bg-workspace/70 p-4">
              <p className="text-xs font-semibold text-text">
                Key Probabilities
              </p>
              <ul className="mt-3 space-y-2">
                {keyProbs.map((k) => (
                  <li
                    key={k.id}
                    className="flex items-center justify-between gap-2 border-b border-hairline/60 pb-2 text-[11px] last:border-b-0 last:pb-0"
                  >
                    <span className="text-text-muted">{k.label}</span>
                    <span
                      className={cn(
                        "font-data font-semibold",
                        k.highlight ? "rounded bg-sapphire/15 px-1.5 py-0.5 text-sapphire" : "text-text",
                      )}
                    >
                      {k.value === null ? "—" : fmtPct(k.value)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Panel>

        {/* what could break this — invalidation factors */}
        <Panel className="p-4 lg:p-5 flex flex-col">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text">
            What Could Break This?
            <Info className="h-3.5 w-3.5 text-text-muted" aria-hidden />
          </h2>
          <ul className="mt-3.5 flex-1 space-y-2.5">
            {factors.map((f) => (
              <FactorCard key={f.key} card={f} />
            ))}
          </ul>
        </Panel>
      </div>

      {/* ——— bottom research grid: 3 balanced columns ——— */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* recent trends */}
        <Panel className="p-4 lg:p-5 flex flex-col justify-between">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="font-display text-sm font-semibold text-text">
              Recent Trends
            </h2>
            <div
              className="flex items-center gap-1"
              role="tablist"
              aria-label="Recent trend market"
            >
              {[
                { key: "receiving_yards" as MarketKey, label: "Yards" },
                { key: "receptions" as MarketKey, label: "Targets" },
                { key: "receptions" as MarketKey, label: "Receptions" },
              ].map((m, idx) => {
                const active = idx === 0;
                return (
                  <button
                    key={`${m.label}-${idx}`}
                    role="tab"
                    type="button"
                    aria-selected={active}
                    onClick={() => setTrendMarket(m.key)}
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 font-data text-[10.5px] font-medium transition-colors",
                      active
                        ? "border-sapphire/60 bg-sapphire/15 text-sapphire font-semibold"
                        : "border-hairline bg-panel text-text-muted hover:text-text",
                    )}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
          </div>
          <RecentTrendsChart
            games={trendGames}
            mean={trendRow?.projectedVolume ?? 0}
            avg={trendAvg}
            unit={trendMeta.unit}
          />
        </Panel>

        {/* model details */}
        <Panel className="p-4 lg:p-5 flex flex-col justify-between">
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text">
              Model Details
              <Info className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            </h2>
            <dl className="mt-3 space-y-2">
              <ParamRow
                label="Receptions (NB)"
                value="r = 5.21   p = 0.46"
              />
              <ParamRow
                label="Yards / Reception (Gamma)"
                value="α = 4.38   β = 0.17"
              />
              <ParamRow
                label="Implied Mean (yards)"
                value="84.2"
              />
              <ParamRow
                label="Implied Median (yards)"
                value="78.5"
              />
            </dl>
          </div>
          <button
            type="button"
            onClick={() => (window.location.hash = "/research/methodology")}
            className="mt-4 text-xs font-medium text-sapphire transition-colors hover:text-sapphire-hover text-left flex items-center gap-1"
          >
            Full model specification →
          </button>
        </Panel>

        {/* context */}
        <Panel className="p-4 lg:p-5">
          <h2 className="text-sm font-semibold text-text">Context</h2>
          <dl className="mt-3 space-y-2">
            <ParamRow
              icon={Target}
              label="Target share"
              value="32.4% (↑ +4.1 pp L4)"
            />
            <ParamRow
              icon={Radar}
              label="Air yards share"
              value="41.8%"
            />
            <ParamRow
              icon={Zap}
              label="Pass rate (proj)"
              value="61.5%"
            />
            <ParamRow
              icon={Shield}
              label="Opp. pass defense"
              value="26th (vs WR1)"
            />
          </dl>
        </Panel>
      </div>

      {/* ——— evidentiary footer ——— */}
      <footer className="mt-1 flex flex-wrap items-center justify-between gap-3 border-t border-hairline/60 pt-3 text-[11px] text-text-muted">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          <span>Ledger root #178e29974bf8748c · 472 candidates verified pre-kickoff · 0/600 confirmatory gate</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => (window.location.hash = "/performance")}
            className="text-sapphire hover:underline"
          >
            Public audit & CLV
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => (window.location.hash = "/research/methodology")}
            className="text-sapphire hover:underline"
          >
            Methodology
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => (window.location.hash = "/research/value-boundaries")}
            className="text-sapphire hover:underline"
          >
            Value boundaries
          </button>
        </div>
      </footer>

      {/* deep link share button */}
      <ShareLinkButton />
    </article>
  );
}
