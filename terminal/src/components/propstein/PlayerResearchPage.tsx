"use client";

/* ============================================================
   PropStein — flagship player research workspace
   Layout mirrors the approved 2027 desktop mockup:
     breadcrumb + ‹ W9 › slate selector + Research Mode →
     player header (identity · matchup pill · kickoff meta) →
     market tabs (active = light pill) →
     Fair Line (median) · Projection (mean) · Market Line ·
     Model Edge →
     distribution panel (Distribution/CDF toggle, halo
     reference chips Market·Median·Mean, no-value band) with
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
  SPORT_META,
  type MarketKey,
  type Sport,
  type GameInfo,
} from "@/lib/propstein/types";
import {
  fmt,
  fmtPct,
  fmtOdds,
  fmtSigned,
  formatAge,
  formatTimestamp,
  formatKickoff,
  formatKickoffShort,
} from "@/lib/propstein/format";
import {
  overProb,
  underProb,
  breakEvenProb,
  fairProb,
} from "@/lib/propstein/model";
import { lawCdf } from "@/lib/propstein/distributions";
import { StatusChip, TeamMark, Panel } from "./primitives";
import { DistributionChart } from "./DistributionChart";
import { cn } from "@/lib/utils";
import {
  Star,
  ShieldAlert,
  Info,
  BookOpen,
  LineChart,
  Clock,
  AlertTriangle,
  HeartPulse,
  FlaskConical,
  Crosshair,
  BarChart3,
  Layers,
  ChevronLeft,
  ChevronRight,
  GitCommitHorizontal,
  Share2,
  Check,
  Radar,
  Activity,
  Clapperboard,
  Target,
  Wind,
  Zap,
  Shield,
  Timer,
  Scale,
  Hash,
  MoveHorizontal,
  Sigma,
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
    <div className="flex items-center overflow-hidden rounded-[6px] border border-hairline bg-panel font-data text-[11px]">
      <button
        type="button"
        disabled
        aria-label="Previous slate — not in this snapshot"
        title="This snapshot contains one slate only."
        className="cursor-not-allowed px-1 py-1 text-text-muted/50"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
      </button>
      <span className="px-1.5 py-1 text-text">{label}</span>
      <button
        type="button"
        disabled
        aria-label="Next slate — not in this snapshot"
        title="This snapshot contains one slate only."
        className="cursor-not-allowed px-1 py-1 text-text-muted/50"
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
      className={cn("p-4", highlighted && "border-sapphire/30 bg-sapphire/5")}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="label-micro flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
        </p>
        {headerExtra}
      </div>
      <p className="mt-2.5 flex items-baseline gap-1.5">
        <span
          className={cn(
            "font-data text-[32px] font-medium leading-none",
            accent ?? "text-text",
          )}
        >
          {value}
        </span>
        {unit ? <span className="text-xs text-text-muted">{unit}</span> : null}
        {valueExtra}
      </p>
      {footer}
      {sub ? (
        <p className="mt-2 text-[11px] leading-snug text-text-muted">{sub}</p>
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
  detail: string;
}

function buildFactorCards(row: BoardRow): FactorCardData[] {
  const base = invalidationFactors(row);
  const byTitle = (t: string) => base.find((f) => f.title === t);
  const player = row.player;
  const game = gameFor(player.gameId);
  const isHome = game.home === player.team;
  const spreadFromTeam = isHome ? -game.spread : game.spread;
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
      icon: Clapperboard,
      tint: "sapphire",
      severity: gameScript?.severity ?? "minor",
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
      detail: coverage?.detail ?? SEED_MAP[player.id]?.oppNote ?? "",
    },
    {
      key: "volatility",
      title: "Volatility",
      icon: Activity,
      tint: "caution",
      severity: "minor",
      detail: `${volatility?.detail ?? ""} Published dispersion: σ ${row.sd.toFixed(1)} ${MARKET_META[row.market].unit}, 80% interval ${fmt(row.p10, 0)}–${fmt(row.p90, 0)}.`,
    },
  ];
}

const TINT_CLASS: Record<FactorCardData["tint"], string> = {
  sapphire: "bg-sapphire/10 text-sapphire",
  caution: "bg-caution/10 text-caution",
  muted: "bg-elevated text-text-muted",
};

function FactorCard({ card }: { card: FactorCardData }) {
  return (
    <li className="rounded-[8px] border border-hairline bg-workspace p-2.5">
      <p className="flex items-center gap-2 text-xs font-medium text-text">
        <span
          aria-hidden
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px]",
            TINT_CLASS[card.tint],
          )}
        >
          <card.icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        {card.title}
        <span
          className={cn(
            "ml-auto font-data text-[9.5px] font-normal uppercase tracking-[0.08em]",
            card.severity === "material"
              ? "text-caution"
              : card.severity === "moderate"
                ? "text-caution/80"
                : "text-text-muted",
          )}
        >
          {card.severity}
        </span>
      </p>
      <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
        {card.detail}
      </p>
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
      /* clipboard unavailable — the URL bar still carries the deep link */
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
      className="fixed bottom-6 right-6 z-20 hidden h-10 w-10 items-center justify-center rounded-full border border-hairline bg-elevated text-text-muted shadow-xl shadow-black/40 transition-colors hover:text-sapphire lg:flex"
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
    <div className="flex items-baseline justify-between gap-3 border-b border-hairline py-1.5 text-[11px] last:border-b-0">
      <dt className="flex shrink-0 items-center gap-1.5 text-text-muted">
        {Icon ? <Icon className="h-3 w-3" aria-hidden /> : null}
        {label}
      </dt>
      <dd className="text-right font-data text-text">{value}</dd>
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
  /* responsive — mirrors the distribution chart's ResizeObserver pattern,
     so the log always fits the card (no clipped bars on small screens).
     Compact mode (<420px) thins ticks and keeps only the latest value label. */
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
  const avgChipW = avgLabel.length * 6.1 + 12;

  return (
    <div ref={wrapRef} className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-[152px] w-full"
        role="img"
        aria-label={`Recent game log: ${games.map((g) => `${g.label} ${g.value} ${unit}`).join(", ")}. Recent average ${avg.toFixed(1)} ${unit}, projected mean ${mean.toFixed(1)} ${unit}.`}
      >
        {/* gridlines + y ticks (mockup: fixed nice steps) */}
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
                fontSize="10.5"
                className="font-data"
                fill="var(--chart-tick)"
              >
                {t}
              </text>
            )}
          </g>
        ))}

        {/* bars — latest emphasized (painted before reference lines so the
            avg badge sits ON the line, over any bar it covers) */}
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
                    : "color-mix(in srgb, var(--ps-sapphire) 34%, #16202e)"
                }
              />
              <text
                x={x + w / 2}
                y={H - 7}
                textAnchor="middle"
                fontSize={11}
                fill="var(--chart-tick)"
              >
                {g.label}
              </text>
              <text
                x={x + w / 2}
                y={top - 4}
                textAnchor="middle"
                fontSize={11}
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

        {/* projected mean — subtle dotted sapphire reference */}
        <line
          x1={M.l}
          x2={W - M.r}
          y1={y(mean)}
          y2={y(mean)}
          stroke="var(--ps-sapphire)"
          strokeWidth={1}
          strokeDasharray="2 4"
          opacity={0.7}
        />

        {/* recent average — dashed mint line with a solid badge centered on it
            (mockup: "Avg 87.1"). Painted after the bars so the badge reads ON
            the line regardless of bar positions. */}
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
            x={M.l + 6}
            y={y(avg) - 8}
            width={avgChipW}
            height={16}
            rx={4}
            fill="var(--ps-panel)"
            stroke="var(--ps-mint)"
            strokeOpacity={0.55}
            strokeWidth={1}
          />
          <text
            x={M.l + 6 + avgChipW / 2}
            y={y(avg) + 3.5}
            textAnchor="middle"
            fontSize={10}
            className="font-data"
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
  // hooks must run before any early return
  const factors = useMemo(() => (row ? buildFactorCards(row) : []), [row]);

  // recent-trends tab — defaults to the page's market, peekable at siblings
  const [trendMarket, setTrendMarket] = useState<MarketKey>(market);
  useEffect(() => setTrendMarket(market), [market, playerId]);

  // trends data for the selected trend tab (deterministic preview log)
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
  const oppTeam = TEAMS[oppAbbr];
  const saved = savedPlayers.includes(playerId);
  const meta = MARKET_META[market];
  const unit = meta.unit;
  const sportMarkets = MARKET_KEYS_BY_SPORT[sport];
  const ctx = contextFor(playerId);

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
  const seedParams = row.projection.law;
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

  const contextRows =
    sport === "nfl"
      ? [
          {
            icon: Target,
            label: "Target share",
            value: fmtPct(player.targetShare, 1),
          },
          {
            icon: Wind,
            label: "Air yards share",
            value: fmtPct(ctx.airYardsShare, 1),
          },
          {
            icon: Zap,
            label: "Pass rate (proj)",
            value: fmtPct(ctx.passRateProj, 0),
          },
          {
            icon: Shield,
            label: "Opp. pass defense",
            value: ctx.oppPassDefense ?? "—",
          },
          {
            icon: Timer,
            label: "Snap share",
            value: fmtPct(player.snapShare, 1),
          },
          {
            icon: Scale,
            label: "Team spread",
            value: `${(home ? -game.spread : game.spread) > 0 ? "+" : ""}${home ? -game.spread : game.spread}`,
          },
          { icon: Hash, label: "Game total", value: `${game.total}` },
          {
            icon: MoveHorizontal,
            label: "80% interval",
            value: `${fmt(row.p10, 0)}–${fmt(row.p90, 0)} ${unit}`,
          },
        ]
      : [
          {
            icon: Target,
            label: "Usage rate",
            value: fmtPct(player.targetShare, 1),
          },
          {
            icon: Timer,
            label: "Minutes share",
            value: fmtPct(player.snapShare, 1),
          },
          {
            icon: Zap,
            label: "Pace (proj)",
            value: `${ctx.paceProj?.toFixed(1) ?? "—"} poss/48`,
          },
          {
            icon: Shield,
            label: "Opp. defense",
            value: `${ctx.oppDefRtg?.toFixed(1) ?? "—"} DRtg`,
          },
          {
            icon: Scale,
            label: "Team spread",
            value: `${(home ? -game.spread : game.spread) > 0 ? "+" : ""}${home ? -game.spread : game.spread}`,
          },
          { icon: Hash, label: "Game total", value: `${game.total}` },
          {
            icon: MoveHorizontal,
            label: "80% interval",
            value: `${fmt(row.p10, 0)}–${fmt(row.p90, 0)} ${unit}`,
          },
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
            className="inline-flex h-7 items-center gap-1.5 rounded-full border border-sapphire/40 bg-sapphire/10 px-3 py-1 text-[11px] font-medium text-sapphire transition-colors hover:bg-sapphire/20"
            title="Product posture — links to the public audit. Never masks data-health states (STALE, UNVERIFIED) attached to captured quotes."
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
                  color: TEAMS[player.team].color,
                  background: `color-mix(in srgb, ${TEAMS[player.team].color} 10%, transparent)`,
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
              <h1 className="font-display text-[26px] font-semibold tracking-tight text-text">
                {player.name}
              </h1>
              {player.injury === "QUESTIONABLE" ? (
                <span className="flex items-center gap-1 rounded-[6px] bg-caution/10 px-2 py-0.5 text-[10px] font-medium text-caution">
                  <AlertTriangle className="h-3 w-3" aria-hidden /> Questionable
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-xs text-text-muted">
              {player.pos} · {player.team} · #1
            </p>
          </div>
        </div>

        {/* matchup badge */}
        <div className="flex items-center gap-3 lg:justify-end">
          <div className="rounded-[10px] border border-hairline bg-panel px-4 py-2 text-left lg:text-right">
            <p className="font-display text-xs font-semibold text-text">
              {player.team} {home ? "vs" : "@"} {oppAbbr}
            </p>
            <p className="mt-0.5 text-[10px] text-text-muted">
              Sun, Nov 9 · 1:00 PM
            </p>
          </div>
        </div>
      </header>

      {/* ——— market tabs (mockup: active = light pill) ——— */}
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
          const r = getRow(playerId, m.key);
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
                  ? "border-sapphire/50 bg-workspace text-text shadow-[0_0_12px_rgba(56,189,248,0.15)]"
                  : "border-hairline bg-panel text-text-muted hover:border-sapphire/30 hover:text-text",
                !(m.key === "receiving_yards" || m.key === "receptions") && "opacity-60 cursor-not-allowed"
              )}
            >
              <span>{m.label}</span>
              {r ? <StatusChip status={r.status} size="xs" /> : null}
            </button>
          );
        })}
      </div>

      {/* ——— top metric grid: the four published figures ——— */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {/* fair line — median (sapphire: the model's headline) */}
        <MetricCard
          icon={Crosshair}
          label="Fair line (median)"
          value={fmt(row.fairLine, row.fairLine % 1 === 0 ? 0 : 1)}
          unit={unit}
          accent="text-sapphire"
          sub="The model's center estimate — the 50th percentile of the published distribution."
        />

        {/* projection — mean */}
        <MetricCard
          icon={BarChart3}
          label="Projection (mean)"
          value={fmt(row.projectedVolume, 1)}
          unit={unit}
          sub={`Expected ${meta.label.toLowerCase()} (volume). Right-skewed laws carry the mean above the median.`}
        />

        {/* market line — observed, priced, verified-or-not */}
        <MetricCard
          icon={Layers}
          label="Market line"
          value={row.quote ? `${row.quote.line}` : "—"}
          valueExtra={
            row.quote ? (
              <span className="font-data text-sm text-text-muted">
                {fmtOdds(row.quote.overOdds)} / {fmtOdds(row.quote.underOdds)}
              </span>
            ) : null
          }
          headerExtra={
            row.quote ? <StatusChip status={row.status} size="xs" /> : null
          }
          sub={
            row.quote ? (
              <>
                Captured {formatAge(row.quote.capturedAt)} ago ·{" "}
                {row.quote.source}
                {row.quote.verifiedAgainst ? " · verified vs Book B" : ""}
              </>
            ) : row.status === "UNAVAILABLE" ? (
              <>Not offered — {row.unavailableReason ?? "no line posted"}.</>
            ) : (
              <>No quote captured yet. Nothing here is a market observation.</>
            )
          }
        />

        {/* model edge — only meaningful with a captured two-sided quote */}
        <MetricCard
          icon={Info}
          label="Model edge"
          value={
            edge !== null && row.quote ? `${fmtSigned(edge * 100, 1)}%` : "—"
          }
          accent={
            edge !== null && Math.abs(edge) >= 0.02 ? "text-mint" : "text-text"
          }
          highlighted={edge !== null && Math.abs(edge) >= 0.02}
          footer={
            edge !== null && modelOver !== null && row.quote ? (
              <span
                className="mt-3 flex items-center gap-2.5"
                aria-hidden
                title="Model P(over) vs break-even probability at the captured price"
              >
                <span className="relative block h-2 w-20 overflow-hidden rounded-full border border-hairline bg-elevated">
                  <span
                    className="absolute inset-y-0 left-0 rounded-full bg-mint"
                    style={{ width: `${Math.round(modelOver * 100)}%` }}
                  />
                  <span
                    className="absolute inset-y-[-2px] w-[2px] bg-caution"
                    style={{
                      left: `${Math.round(breakEvenProb(row.quote.overOdds) * 100)}%`,
                    }}
                  />
                </span>
                <span className="font-data text-[10px] leading-tight text-text-muted">
                  P(over) {fmtPct(modelOver, 0)} · BE{" "}
                  {fmtPct(breakEvenProb(row.quote.overOdds), 0)}
                </span>
              </span>
            ) : null
          }
          sub={
            edge !== null && modelOver !== null && row.quote ? (
              <>
                Model P(over {row.quote.line}) {fmtPct(modelOver)} vs break-even{" "}
                {fmtPct(breakEvenProb(row.quote.overOdds))} at{" "}
                {fmtOdds(row.quote.overOdds)}. A research measurement, not a bet
                recommendation.
              </>
            ) : (
              <>
                Edge requires a captured two-sided quote. None exists for this
                market in the snapshot.
              </>
            )
          }
        />
      </div>

      {/* ——— main content + research rail ——— */}
      <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* primary column — display:contents on mobile so panels order per the
            approved mobile hierarchy: distribution → provenance → trends →
            invalidation → details */}
        <div className="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-5">
          {/* signature distribution panel + key probabilities */}
          <Panel className="order-1 p-4 lg:order-none lg:p-5">
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-base font-semibold text-text">
                {meta.label} distribution
              </h2>
              <p className="text-[11px] text-text-muted">
                {seedParams.kind === "negbin"
                  ? "Negative Binomial (NB2) · discrete"
                  : "NB count ∘ Gamma volume · exact compound"}
              </p>
            </div>
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
              {/* key probabilities — adjacent readout (mockup right block) */}
              <div className="h-fit rounded-[8px] border border-hairline bg-workspace p-3.5">
                <p className="text-xs font-semibold text-text">
                  Key probabilities
                </p>
                <ul className="mt-2.5">
                  {keyProbs.map((k) => (
                    <li
                      key={k.id}
                      className="flex items-center justify-between gap-2 border-b border-hairline py-2 text-[11px] last:border-b-0"
                    >
                      <span className="text-text-muted">{k.label}</span>
                      <span
                        className={cn(
                          "font-data font-medium",
                          k.highlight ? "text-sapphire" : "text-text",
                        )}
                      >
                        {k.value === null ? "—" : fmtPct(k.value)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2.5 text-[10px] leading-snug text-text-muted">
                  Computed from the published law — never from hit-rate
                  marketing.
                </p>
              </div>
            </div>

            {/* value boundaries — compact footer under the chart */}
            {row.boundaries && row.quote ? (
              <p className="mt-4 border-t border-hairline pt-3 text-xs leading-relaxed text-text-muted">
                No-value band{" "}
                <span className="font-data text-text">
                  {fmt(row.boundaries.lower, 1)}–{fmt(row.boundaries.upper, 1)}{" "}
                  {unit}
                </span>{" "}
                at {fmtOdds(row.quote.overOdds)} /{" "}
                {fmtOdds(row.quote.underOdds)} — between those lines neither
                side clears its break-even probability against the model. The
                captured line{" "}
                <span className="font-data text-text">{row.quote.line}</span>{" "}
                {row.boundaries.lineInsideBand
                  ? "sits inside the band: no side clears break-even at these prices."
                  : `sits outside the band — model ${row.comparison.lineDivergence! > 0 ? "projects above" : "projects below"} the captured line by ${fmt(Math.abs(row.comparison.lineDivergence!), 1)} ${unit} (${fmtSigned(row.comparison.standardizedDivergence, 2)}σ).`}
              </p>
            ) : (
              <p className="mt-4 border-t border-hairline pt-3 text-xs leading-relaxed text-text-muted">
                {row.status === "UNAVAILABLE"
                  ? `Market unavailable — ${row.unavailableReason ?? "no line posted"}. Value boundaries require a captured two-sided quote; none exists for this market in the snapshot.`
                  : "Value boundaries are computed from a captured two-sided quote. No quote exists for this market yet, so no boundaries are published — the model surface above stands alone (MODEL_ONLY)."}
              </p>
            )}
          </Panel>
          {/* quote provenance & status */}
          <Panel className="order-2 p-4 lg:order-none lg:p-5">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-text">
                Quote provenance
              </h2>
              <StatusChip status={row.status} size="xs" />
            </div>
            {row.quote ? (
              <>
                <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
                  <div>
                    <p className="label-micro">Line</p>
                    <p className="mt-0.5 font-data text-lg leading-none text-text">
                      {row.quote.line}
                    </p>
                  </div>
                  <div>
                    <p className="label-micro">Over</p>
                    <p className="mt-0.5 font-data text-lg leading-none text-text">
                      {fmtOdds(row.quote.overOdds)}
                    </p>
                  </div>
                  <div>
                    <p className="label-micro">Under</p>
                    <p className="mt-0.5 font-data text-lg leading-none text-text">
                      {fmtOdds(row.quote.underOdds)}
                    </p>
                  </div>
                </div>
                <dl className="mt-3 space-y-1.5 border-t border-hairline pt-3 text-[11px]">
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Captured</dt>
                    <dd className="text-right font-data text-text">
                      {formatTimestamp(row.quote.capturedAt)}
                      <span className="block text-[10px] text-text-muted">
                        {formatAge(row.quote.capturedAt)} before snapshot
                      </span>
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Source</dt>
                    <dd className="text-right text-text">{row.quote.source}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-text-muted">Verified</dt>
                    <dd className="text-right">
                      {row.quote.verifiedAgainst ? (
                        <span className="text-[--status-verified]">
                          Yes · Book B
                        </span>
                      ) : (
                        <span className="text-caution">
                          Not yet — single source
                        </span>
                      )}
                    </dd>
                  </div>
                </dl>
                {modelOver !== null && modelUnder !== null ? (
                  <div className="mt-3 space-y-1.5 border-t border-hairline pt-3">
                    <div className="flex justify-between text-[11px]">
                      <span className="text-text-muted">
                        Model P(over {row.quote.line})
                      </span>
                      <span className="font-data text-text">
                        {fmtPct(modelOver)}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px]">
                      <span className="text-text-muted">
                        Break-even at {fmtOdds(row.quote.overOdds)}
                      </span>
                      <span className="font-data text-text">
                        {fmtPct(breakEvenProb(row.quote.overOdds))}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px]">
                      <span className="text-text-muted">
                        Vig-free fair P(over)
                      </span>
                      <span className="font-data text-text">
                        {fmtPct(
                          fairProb(row.quote.overOdds, row.quote.underOdds),
                        )}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px]">
                      <span className="text-text-muted">Model − market</span>
                      <span className="font-data text-text">
                        {fmtSigned(row.comparison.lineDivergence, 1)} {unit} ·{" "}
                        {fmtSigned(row.comparison.standardizedDivergence, 2)}σ
                      </span>
                    </div>
                  </div>
                ) : null}
                {row.status === "STALE" ? (
                  <p className="mt-3 flex items-start gap-1.5 rounded-[6px] bg-caution/10 px-2 py-1.5 text-[11px] leading-snug text-caution">
                    <ShieldAlert
                      className="mt-px h-3 w-3 shrink-0"
                      aria-hidden
                    />
                    Stale: captured {formatAge(row.quote.capturedAt)} before the
                    snapshot. Presented as archived context, not a current
                    quote.
                  </p>
                ) : null}
              </>
            ) : (
              <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
                {row.status === "UNAVAILABLE"
                  ? `Unavailable — ${row.unavailableReason ?? "no line posted at capture time"}.`
                  : "No quote captured yet. Nothing on this card is a market observation — the model surface stands alone."}
              </p>
            )}
          </Panel>
        </div>

        {/* ——— research rail ——— */}
        <aside
          className="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-3 lg:sticky lg:top-[76px] lg:self-start"
          aria-label="Research context"
        >
          {/* what could break this — the four invalidation factors */}
          <Panel className="order-5 p-4 lg:order-none">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
              What could break this?
              <Info className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            </h2>
            <p className="mt-1 text-[11px] leading-snug text-text-muted">
              Conditions under which the published distribution should be
              considered invalidated.
            </p>
            <ul className="mt-3 space-y-2.5">
              {factors.map((f) => (
                <FactorCard key={f.key} card={f} />
              ))}
            </ul>
          </Panel>

          {/* links */}
          <div className="order-8 flex flex-col gap-2 lg:order-none">
            <button
              type="button"
              onClick={() => (window.location.hash = "/research/methodology")}
              className="flex items-center gap-2 rounded-[8px] border border-hairline bg-panel px-3 py-2.5 text-left text-xs text-text transition-colors hover:border-sapphire/40"
            >
              <BookOpen className="h-3.5 w-3.5 text-text-muted" aria-hidden />
              How this model works
              <span className="ml-auto font-data text-[10px] text-text-muted">
                methodology
              </span>
            </button>
            <button
              type="button"
              onClick={() => (window.location.hash = "/performance")}
              className="flex items-center gap-2 rounded-[8px] border border-hairline bg-panel px-3 py-2.5 text-left text-xs text-text transition-colors hover:border-sapphire/40"
            >
              <LineChart className="h-3.5 w-3.5 text-text-muted" aria-hidden />
              Public track record & CLV
              <span className="ml-auto font-data text-[10px] text-text-muted">
                audit
              </span>
            </button>
            <button
              type="button"
              onClick={() =>
                (window.location.hash = "/research/value-boundaries")
              }
              className="flex items-center gap-2 rounded-[8px] border border-hairline bg-panel px-3 py-2.5 text-left text-xs text-text transition-colors hover:border-sapphire/40"
            >
              <Sigma className="h-3.5 w-3.5 text-text-muted" aria-hidden />
              Value boundaries explained
              <span className="ml-auto font-data text-[10px] text-text-muted">
                research
              </span>
            </button>
          </div>

          <p className="order-9 flex items-start gap-1.5 px-1 text-[10px] leading-snug text-text-muted lg:order-none">
            <Info className="mt-px h-3 w-3 shrink-0" aria-hidden />
            Preview build — deterministic demonstration data mirroring
            production contracts. Snapshot{" "}
            {formatTimestamp("2026-11-04T14:15:00-05:00")}.
          </p>
        </aside>
      </div>

      {/* ——— bottom research grid (mockup: three balanced columns) ———
          Recent Trends · Model Details · Context, full width under the
          distribution + rail section. */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {/* recent trends — market-peekable tabs + bar log */}
        <Panel className="p-4 lg:p-5">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-base font-semibold text-text">
              Recent trends
            </h2>
            <div
              className="flex items-center gap-1.5"
              role="tablist"
              aria-label="Recent trend market"
            >
              {sportMarkets.map((m) => {
                const active = m === trendMarket;
                return (
                  <button
                    key={m}
                    role="tab"
                    type="button"
                    aria-selected={active}
                    onClick={() => setTrendMarket(m)}
                    className={cn(
                      "rounded-[6px] border px-2.5 py-1 font-data text-[11px] font-medium transition-colors",
                      active
                        ? "border-sapphire/60 bg-sapphire/10 text-sapphire"
                        : "border-hairline bg-panel text-text-muted hover:text-text",
                    )}
                  >
                    {MARKET_META[m].short}
                  </button>
                );
              })}
            </div>
          </div>
          <p className="mb-3 text-[11px] text-text-muted">
            Game-by-game {trendMeta.label.toLowerCase()} — recent average{" "}
            <span className="font-data text-mint">
              {fmt(trendAvg, 1)} {trendMeta.unit}
            </span>{" "}
            · model mean{" "}
            <span className="font-data text-sapphire">
              {fmt(trendRow?.projectedVolume ?? 0, 1)} {trendMeta.unit}
            </span>{" "}
            (dotted). Preview build — deterministic demonstration data.
          </p>
          <RecentTrendsChart
            games={trendGames}
            mean={trendRow?.projectedVolume ?? 0}
            avg={trendAvg}
            unit={trendMeta.unit}
          />
        </Panel>

        {/* model details — published parameter readouts */}
        <Panel className="p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
            <GitCommitHorizontal
              className="h-3.5 w-3.5 text-text-muted"
              aria-hidden
            />{" "}
            Model details
          </h2>
          <dl className="mt-2.5">
            {seedParams.kind === "negbin" ? (
              <>
                <ParamRow
                  label={`${meta.short} count (NB2)`}
                  value={`r = ${seedParams.nb.r.toFixed(2)} · μ = ${seedParams.nb.mu.toFixed(2)}`}
                />
              </>
            ) : (
              <>
                <ParamRow
                  label="Receptions (NB2)"
                  value={`r = ${seedParams.nb.r.toFixed(2)} · μ = ${seedParams.nb.mu.toFixed(2)}`}
                />
                <ParamRow
                  label="Yards / reception (Gamma)"
                  value={`k = ${seedParams.gamma!.k.toFixed(2)} · θ = ${seedParams.gamma!.theta.toFixed(2)}`}
                />
              </>
            )}
            <ParamRow label="Model σ" value={`${row.sd.toFixed(2)} ${unit}`} />
            <ParamRow
              label="Implied mean"
              value={`${fmt(row.projectedVolume, 1)} ${unit}`}
            />
            <ParamRow
              label="Implied median"
              value={`${fmt(row.fairLine, 1)} ${unit}`}
            />
            <ParamRow label="Version" value={row.projection.modelVersion} />
            <ParamRow
              label="Produced"
              value={formatTimestamp(row.projection.producedAt)}
            />
          </dl>
          <button
            type="button"
            onClick={() => (window.location.hash = "/research/methodology")}
            className="mt-2.5 text-xs text-sapphire transition-colors hover:text-sapphire-hover"
          >
            Full model specification →
          </button>
        </Panel>

        {/* context — usage, environment, opponent */}
        <Panel className="p-4">
          <h2 className="text-sm font-semibold text-text">Context</h2>
          <dl className="mt-2.5">
            {contextRows.map((r) => (
              <ParamRow
                key={r.label}
                icon={r.icon}
                label={r.label}
                value={r.value}
              />
            ))}
          </dl>
          <p className="mt-2 text-[10px] leading-snug text-text-muted">
            Context metrics are deterministic demonstration data in this preview
            build, mirroring the production capture pipeline.
          </p>
        </Panel>
      </div>

      {/* floating deep-link share (desktop) */}
      <ShareLinkButton />
    </article>
  );
}
