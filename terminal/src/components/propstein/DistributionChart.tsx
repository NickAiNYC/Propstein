"use client";

/* ============================================================
   PropStein — distribution chart (flagship visualization)
   Mathematically exact rendering of the published law:
     • receptions — discrete NB stems + step CDF
     • receiving yards — exact compound density + smooth CDF
   Overlays: median (sapphire) · mean (mint, dashed) ·
   captured market line (caution) · no-value band (shaded) ·
   central 80% interval (dotted).
   Probe: pointer and keyboard (← → Home End), exact
   probabilities, and a full tabular data alternative.
   ============================================================ */

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  DistLaw,
  lawCdf,
  lawQuantile,
  lawMean,
  lawMedian,
  lawSd,
  negBinPmf,
  negBinSupportMax,
  compoundPdf,
  compoundP0,
} from "@/lib/propstein/distributions";
import { lawSurvival } from "@/lib/propstein/distributions";
import type { ValueBoundaries } from "@/lib/propstein/model";
import type { Quote, MarketKey } from "@/lib/propstein/types";
import { MARKET_META } from "@/lib/propstein/types";
import { fmtOdds } from "@/lib/propstein/format";
import { cn } from "@/lib/utils";

type ChartMode = "pdf" | "cdf";

/** Quantize emitted coordinates to sub-pixel precision — keeps SSR and
    client hydration bit-identical despite ULP drift in Math.* across engines. */
const R3 = (v: number) => Math.round(v * 1000) / 1000;

interface DistributionChartProps {
  law: DistLaw;
  market: MarketKey;
  boundaries: ValueBoundaries | null;
  quote: Quote | null;
  fairLine: number;
  projectedVolume: number;
  pOver?: number | null;
  className?: string;
}

function niceTicks(lo: number, hi: number, target: number): number[] {
  const span = hi - lo;
  if (span <= 0) return [lo];
  const raw = span / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step)
    ticks.push(t);
  return ticks;
}

export function DistributionChart({
  law,
  market,
  boundaries,
  quote,
  fairLine,
  projectedVolume,
  pOver,
  className,
}: DistributionChartProps) {
  const [mode, setMode] = useState<ChartMode>("pdf");
  const [showInterval, setShowInterval] = useState(true);
  const [probeX, setProbeX] = useState<number | null>(null);
  const [tableOpen, setTableOpen] = useState(false);
  const [width, setWidth] = useState(640);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgId = useId();

  const discrete = law.kind === "negbin";
  const height = width < 480 ? 300 : 384;

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

  /* ---------- geometry ---------- */
  /* left margin carries the rotated y-axis title, bottom the x-axis title */
  const M = useMemo(
    () => ({ l: 56, r: 14, t: 62, b: 50, w: width, h: height }),
    [width, height],
  );
  const iw = Math.max(10, M.w - M.l - M.r);
  const ih = Math.max(10, M.h - M.t - M.b);

  const domain = useMemo(() => {
    const lo = Math.max(0, lawQuantile(0.005, law));
    const hi = lawQuantile(0.995, law);
    const pad = (hi - lo) * 0.06;
    return { lo: Math.max(discrete ? 0 : 0, lo - pad), hi: hi + pad };
  }, [law, discrete]);

  const xScale = useCallback(
    (x: number) => R3(M.l + ((x - domain.lo) / (domain.hi - domain.lo)) * iw),
    [M.l, domain, iw],
  );
  const invX = useCallback(
    (px: number) => domain.lo + ((px - M.l) / iw) * (domain.hi - domain.lo),
    [M.l, domain, iw],
  );

  /* ---------- series ---------- */
  const pmf = useMemo(() => {
    if (!discrete) return null;
    const nMax = Math.min(negBinSupportMax(law.nb), Math.ceil(domain.hi));
    const pts: Array<{ k: number; p: number }> = [];
    for (let k = 0; k <= nMax; k++) {
      const p = negBinPmf(k, law.nb);
      if (p < 1e-5 && k > law.nb.mu + 3) continue;
      pts.push({ k, p });
    }
    return pts;
  }, [discrete, law, domain]);

  const pdfCurve = useMemo(() => {
    if (discrete) return null;
    const N = 240;
    const pts: Array<[number, number]> = [];
    const p0 = compoundP0({
      r: law.nb.r,
      mu: law.nb.mu,
      k: law.gamma!.k,
      theta: law.gamma!.theta,
    });
    for (let i = 0; i <= N; i++) {
      const x = domain.lo + ((domain.hi - domain.lo) * i) / N;
      if (x <= 0) continue;
      pts.push([
        x,
        compoundPdf(x, {
          r: law.nb.r,
          mu: law.nb.mu,
          k: law.gamma!.k,
          theta: law.gamma!.theta,
        }),
      ]);
    }
    return { pts, p0 };
  }, [discrete, law, domain]);

  const yMax = useMemo(() => {
    if (mode === "cdf") return 1;
    if (pmf) return Math.max(...pmf.map((p) => p.p), 0.001) * 1.14;
    if (pdfCurve)
      return Math.max(...pdfCurve.pts.map((p) => p[1]), 0.001) * 1.14;
    return 1;
  }, [mode, pmf, pdfCurve]);

  const yScale = useCallback(
    (v: number) => R3(M.t + ih - (v / yMax) * ih),
    [M.t, ih, yMax],
  );

  const cdfPath = useMemo(() => {
    if (discrete) {
      // step function
      let d = "";
      const nMax = Math.min(negBinSupportMax(law.nb), Math.ceil(domain.hi));
      let prev = 0;
      for (let k = 0; k <= nMax; k++) {
        const f = lawCdf(k, law);
        const x1 = xScale(k);
        const x2 = xScale(Math.min(domain.hi, k + 1));
        if (k === 0) d += `M ${x1} ${yScale(f)}`;
        else d += ` L ${x1} ${yScale(prev)} L ${x1} ${yScale(f)}`;
        d += ` L ${x2} ${yScale(f)}`;
        prev = f;
        if (f > 0.9999) break;
      }
      return d;
    }
    const N = 240;
    let d = "";
    for (let i = 0; i <= N; i++) {
      const x = domain.lo + ((domain.hi - domain.lo) * i) / N;
      const f = lawCdf(Math.max(x, 0.001), law);
      const px = xScale(x);
      const py = yScale(f);
      d += i === 0 ? `M ${px} ${py}` : ` L ${px} ${py}`;
    }
    return d;
  }, [discrete, law, domain, xScale, yScale]);

  const pdfAreaPath = useMemo(() => {
    if (!pdfCurve || pdfCurve.pts.length === 0) return "";
    const base = yScale(0);
    let d = `M ${xScale(pdfCurve.pts[0][0])} ${base}`;
    for (const [x, y] of pdfCurve.pts) d += ` L ${xScale(x)} ${yScale(y)}`;
    d += ` L ${xScale(pdfCurve.pts[pdfCurve.pts.length - 1][0])} ${base} Z`;
    return d;
  }, [pdfCurve, xScale, yScale]);

  /* ---------- ticks ---------- */
  const xTicks = useMemo(() => {
    if (discrete) {
      const step = Math.max(1, Math.round((domain.hi - domain.lo) / 8));
      const ticks: number[] = [];
      for (let k = Math.ceil(domain.lo); k <= domain.hi; k += step)
        ticks.push(k);
      return ticks;
    }
    return niceTicks(domain.lo, domain.hi, 7);
  }, [discrete, domain]);

  const yTicks = useMemo(() => {
    if (mode === "cdf") return [0, 0.25, 0.5, 0.75, 1];
    if (yMax > 0.4) return niceTicks(0, yMax, 4);
    const raw = [0.05, 0.1, 0.15, 0.2, 0.3].filter((v) => v < yMax);
    return [0, ...raw];
  }, [mode, yMax]);

  /* ---------- key figures (declared before probe/annotation sections that use them) ---------- */
  const median = fairLine;
  const mean = projectedVolume;
  const sd = lawSd(law);
  const band = boundaries && quote ? boundaries : null;

  /* ---------- probe ---------- */
  const step = discrete ? 1 : 2.5;
  const snapProbe = useCallback(
    (x: number) => {
      if (discrete) return Math.round(Math.min(Math.max(x, 0), domain.hi));
      return Math.round(Math.min(Math.max(x, 0), domain.hi) * 10) / 10;
    },
    [discrete, domain],
  );

  /** probe readout defaults to the fair line before the user interacts */
  const effectiveProbeX = probeX ?? median;

  const probeInfo = useMemo(() => {
    const px = probeX ?? median;
    const cdf = lawCdf(px, law);
    const surv = 1 - (discrete ? lawCdf(Math.ceil(px) - 1, law) : cdf);
    let density: number;
    if (discrete) density = negBinPmf(Math.round(px), law.nb);
    else
      density = compoundPdf(px, {
        r: law.nb.r,
        mu: law.nb.mu,
        k: law.gamma!.k,
        theta: law.gamma!.theta,
      });
    return { x: px, cdf, surv, density, active: probeX !== null };
  }, [probeX, median, law, discrete]);

  const onPointer = useCallback(
    (e: React.PointerEvent<SVGRectElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * M.w;
      const x = invX(px);
      if (x >= domain.lo && x <= domain.hi) setProbeX(snapProbe(x));
    },
    [invX, domain, snapProbe, M.w],
  );

  const onChartKey = useCallback(
    (e: React.KeyboardEvent) => {
      const cur = effectiveProbeX;
      let next: number | null = null;
      if (e.key === "ArrowLeft") next = cur - step;
      else if (e.key === "ArrowRight") next = cur + step;
      else if (e.key === "Home") next = domain.lo;
      else if (e.key === "End") next = domain.hi;
      if (next !== null) {
        e.preventDefault();
        setProbeX(snapProbe(Math.min(Math.max(next, domain.lo), domain.hi)));
      }
    },
    [probeX, effectiveProbeX, step, domain, snapProbe],
  );

  /* ---------- labels & markers ---------- */
  const fmtX = (x: number) =>
    discrete ? `${x}` : x >= 100 ? x.toFixed(0) : x.toFixed(1);
  const fmtTick = (x: number) => `${Math.round(x)}`;
  const fmtProb = (p: number) => `${(p * 100).toFixed(1)}%`;
  const unit = MARKET_META[market].unit;
  const marketLabel = MARKET_META[market].label;
  const pOverMarket = quote ? lawSurvival(quote.line, law) : null;

  const interval = useMemo(
    () => ({ p10: lawQuantile(0.1, law), p90: lawQuantile(0.9, law) }),
    [law],
  );

  /** Reference chips — the approved mockup's halo chips:
   *  Market <line> (mint) · Median <fair> (sapphire) · Mean (gray).
   *  One row above the plot, greedily packed so chips never overlap,
   *  each connected to its dashed reference line by an elbow stub. */
  const chips = (() => {
    type Chip = { key: string; lineX: number; label: string; color: string };
    const fx = (x: number) =>
      discrete ? `${x}` : x >= 100 ? x.toFixed(0) : x.toFixed(1);
    const items: Chip[] = [
      {
        key: "median",
        lineX: xScale(median),
        label: `Median ${fx(median)}`,
        color: "var(--chart-marker-median)",
      },
      {
        key: "mean",
        lineX: xScale(mean),
        label: `Mean ${fx(mean)}`,
        color: "var(--chart-marker-mean)",
      },
    ];
    if (quote) {
      items.unshift({
        key: "market",
        lineX: xScale(quote!.line),
        label: `Market ${quote!.line}`,
        color: "var(--chart-marker-market)",
      });
    }
    // mono chip width ≈ 6.1px/char at 10px + 14px padding
    const chipW = (t: string) => t.length * 6.1 + 14;
    const sorted = [...items].sort((a, b) => a.lineX - b.lineX);
    // greedy left-pack on a single row: never overlap, keep each chip as
    // close to its reference line as the previous chip allows
    const placed: Array<Chip & { cx: number; w: number }> = [];
    let prevRight = M.l;
    for (const it of sorted) {
      const w = chipW(it.label);
      const cx = Math.max(it.lineX, prevRight + w / 2 + 6);
      placed.push({ ...it, cx, w });
      prevRight = cx + w / 2;
    }
    // clamp the whole row inside the plot, shifting left together if needed
    const overflow = prevRight - (M.w - M.r);
    const row =
      overflow > 0
        ? placed.map((p) => ({ ...p, cx: p.cx - overflow }))
        : placed;
    const ROW_TOP = M.t - 36; // rect top; bottom sits 19px above the plot
    return row.map((p) => ({ ...p, top: ROW_TOP, bottom: ROW_TOP + 17 }));
  })();

  /* ---------- render ---------- */
  return (
    <div className={cn("flex flex-col", className)} ref={wrapRef}>
      {/* controls — mockup pill toggle: Distribution · CDF · Simulations.
          Simulations stays disabled (fail-closed): this snapshot publishes
          the exact law, not sampled paths. */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div
          role="tablist"
          aria-label="Chart mode"
          className="flex items-center gap-1.5"
        >
          {[
            { m: "pdf" as ChartMode, label: "Distribution" },
            { m: "cdf" as ChartMode, label: "CDF" },
          ].map((t) => (
            <button
              key={t.m}
              role="tab"
              type="button"
              aria-selected={mode === t.m}
              onClick={() => setMode(t.m)}
              className={cn(
                "rounded-[6px] border px-3 py-1 text-[11px] font-medium transition-colors",
                mode === t.m
                  ? "border-sapphire/60 bg-sapphire/10 text-sapphire"
                  : "border-hairline bg-panel text-text-muted hover:text-text",
              )}
            >
              {t.label}
            </button>
          ))}
          <button
            type="button"
            role="tab"
            aria-selected={false}
            aria-disabled="true"
            disabled
            title="Simulations are not part of this snapshot build — the published law is rendered exactly instead."
            className="cursor-not-allowed rounded-[6px] border border-hairline bg-panel px-3 py-1 text-[11px] font-medium text-text-muted/50"
          >
            Simulations
          </button>
        </div>
        <button
          type="button"
          aria-pressed={showInterval}
          onClick={() => setShowInterval((v) => !v)}
          className={cn(
            "rounded-[6px] border px-2.5 py-1 text-[11px] font-medium transition-colors",
            showInterval
              ? "border-hairline bg-workspace text-text"
              : "border-hairline bg-panel text-text-muted hover:text-text",
          )}
        >
          80% interval
        </button>
        {pOver !== null && pOver !== undefined ? (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-sapphire/40 bg-sapphire/10 px-3 py-1 font-data text-xs text-sapphire shadow-[0_0_8px_rgba(56,189,248,0.15)]">
            <span>P(Over)</span>
            <span className="font-semibold">{Math.round(pOver * 1000) / 10}%</span>
          </span>
        ) : null}
        <button
          type="button"
          aria-expanded={tableOpen}
          onClick={() => setTableOpen((v) => !v)}
          className={cn(
            "rounded-[6px] border border-hairline bg-panel px-2.5 py-1 text-[11px] font-medium text-text-muted transition-colors hover:text-text",
            !(pOver !== null && pOver !== undefined) && "ml-auto"
          )}
        >
          {tableOpen ? "Hide data table" : "View as table"}
        </button>
      </div>

      {/* chart */}
      <div
        className="relative rounded-[4px] focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sapphire"
        tabIndex={0}
        role="application"
        aria-label={`Interactive distribution chart. Use left and right arrow keys to move the probability probe; Home and End jump to the domain edges. Current probe: ${probeInfo ? `${probeInfo.x} ${unit}` : "unset"}.`}
        onKeyDown={onChartKey}
      >
        <svg
          role="img"
          aria-labelledby={`${svgId}-title`}
          width="100%"
          viewBox={`0 0 ${M.w} ${M.h}`}
          className="touch-pan-y select-none"
        >
          <title id={`${svgId}-title`}>
            {`Probability ${mode === "pdf" ? "density" : "distribution"} of ${market.replace("_", " ")} — median ${fmtX(median)}, mean ${fmtX(mean)}${quote ? `, captured line ${quote.line}` : ""}`}
          </title>
          <defs>
            <linearGradient id={`${svgId}-pdfFill`} x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--chart-series-pdf)"
                stopOpacity={0.3}
              />
              <stop
                offset="100%"
                stopColor="var(--chart-series-pdf)"
                stopOpacity={0.02}
              />
            </linearGradient>
          </defs>

          {/* no-value band — label rendered later, above the series */}
          {band ? (
            <g>
              <rect
                x={xScale(Math.max(band.lower, domain.lo))}
                y={M.t}
                width={Math.max(
                  0,
                  xScale(Math.min(band.upper, domain.hi)) -
                    xScale(Math.max(band.lower, domain.lo)),
                )}
                height={ih}
                fill="var(--chart-band-novalue)"
                stroke="var(--chart-band-novalue-edge)"
                strokeWidth={1}
                strokeDasharray="2 3"
              />
            </g>
          ) : null}

          {/* gridlines */}
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line
                x1={M.l}
                x2={M.w - M.r}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="var(--chart-grid)"
                strokeWidth={1}
              />
              <text
                x={M.l - 8}
                y={yScale(t) + 3}
                textAnchor="end"
                className="font-data"
                fill="var(--chart-tick)"
                fontSize={10.5}
              >
                {mode === "cdf"
                  ? fmtProb(t)
                  : t === 0
                    ? "0"
                    : yMax < 0.05
                      ? t.toFixed(3)
                      : t.toFixed(2)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <g key={`x${t}`}>
              <line
                x1={xScale(t)}
                x2={xScale(t)}
                y1={M.t}
                y2={M.t + ih}
                stroke="var(--chart-grid)"
                strokeWidth={1}
              />
              <text
                x={xScale(t)}
                y={M.h - 20}
                textAnchor="middle"
                className="font-data"
                fill="var(--chart-tick)"
                fontSize={10.5}
              >
                {fmtTick(t)}
              </text>
            </g>
          ))}
          <line
            x1={M.l}
            x2={M.w - M.r}
            y1={M.t + ih}
            y2={M.t + ih}
            stroke="var(--ps-border)"
            strokeWidth={1}
          />

          {/* axis titles — mockup: “Probability Density” / market label */}
          <text
            transform={`rotate(-90)`}
            x={-(M.t + ih / 2)}
            y={13}
            textAnchor="middle"
            fontSize={10}
            fill="var(--chart-tick)"
          >
            {mode === "pdf" ? "Probability Density" : "Cumulative Probability"}
          </text>
          <text
            x={(M.l + M.w - M.r) / 2}
            y={M.h - 5}
            textAnchor="middle"
            fontSize={10}
            fill="var(--chart-tick)"
          >
            {marketLabel}
          </text>

          {/* series */}
          {mode === "pdf" && pmf
            ? pmf.map((p) => {
                const barW = R3(
                  Math.min(18, (iw / (domain.hi - domain.lo)) * 0.72),
                );
                return (
                  <rect
                    key={p.k}
                    x={R3(xScale(p.k) - barW / 2)}
                    y={yScale(p.p)}
                    width={barW}
                    height={R3(Math.max(0, yScale(0) - yScale(p.p)))}
                    fill="var(--chart-series-pdf)"
                    opacity={0.82}
                    rx={1}
                  />
                );
              })
            : null}

          {mode === "pdf" && pdfCurve ? (
            <g>
              <path d={pdfAreaPath} fill={`url(#${svgId}-pdfFill)`} />
              <path
                d={pdfCurve.pts
                  .map(
                    ([x, y], i) =>
                      `${i === 0 ? "M" : "L"} ${xScale(x)} ${yScale(y)}`,
                  )
                  .join(" ")}
                fill="none"
                stroke="var(--chart-series-pdf)"
                strokeWidth={1.8}
              />
              {pdfCurve.p0 > 0.004 ? (
                <g>
                  <circle
                    cx={xScale(0)}
                    cy={yScale(pdfCurve.p0)}
                    r={3}
                    fill="var(--chart-series-pdf)"
                  />
                  <text
                    x={xScale(0) + 6}
                    y={yScale(pdfCurve.p0) - 6}
                    className="font-data"
                    fill="var(--chart-tick)"
                    fontSize={9}
                  >
                    P(0) {fmtProb(pdfCurve.p0)}
                  </text>
                </g>
              ) : null}
            </g>
          ) : null}

          {mode === "cdf" ? (
            <path
              d={cdfPath}
              fill="none"
              stroke="var(--chart-series-cdf)"
              strokeWidth={1.8}
            />
          ) : null}

          {/* central 80% interval band */}
          {showInterval ? (
            <g>
              <rect
                x={xScale(Math.max(interval.p10, domain.lo))}
                y={M.t}
                width={Math.max(
                  0,
                  xScale(Math.min(interval.p90, domain.hi)) -
                    xScale(Math.max(interval.p10, domain.lo)),
                )}
                height={ih}
                fill="var(--ps-sapphire)"
                opacity={0.045}
              />
              {[interval.p10, interval.p90].map((q, i) => (
                <line
                  key={i}
                  x1={xScale(Math.max(q, domain.lo))}
                  x2={xScale(Math.max(q, domain.lo))}
                  y1={M.t}
                  y2={M.t + ih}
                  stroke="var(--chart-axis)"
                  strokeWidth={1}
                  strokeDasharray="1.5 3.5"
                  opacity={0.7}
                />
              ))}
            </g>
          ) : null}

          {/* reference lines — mockup: dashed, one color per metric.
              market = mint · median (fair line) = sapphire · mean = gray */}
          {quote ? (
            <line
              x1={xScale(quote.line)}
              x2={xScale(quote.line)}
              y1={M.t}
              y2={M.t + ih}
              stroke="var(--chart-marker-market)"
              strokeWidth={1.6}
              strokeDasharray="5 3"
              opacity={0.9}
            />
          ) : null}

          <line
            x1={xScale(median)}
            x2={xScale(median)}
            y1={M.t}
            y2={M.t + ih}
            stroke="var(--chart-marker-median)"
            strokeWidth={1.6}
            strokeDasharray="6 3"
          />

          <line
            x1={xScale(mean)}
            x2={xScale(mean)}
            y1={M.t}
            y2={M.t + ih}
            stroke="var(--chart-marker-mean)"
            strokeWidth={1.4}
            strokeDasharray="4 4"
            opacity={0.9}
          />

          {/* reference chips — single packed row, anchored by elbow stubs */}
          {chips.map((c) => (
            <g key={c.key}>
              {/* elbow stub from chip bottom to the top of its dashed line */}
              <path
                d={`M ${R3(c.cx)} ${c.bottom} L ${R3(c.cx)} ${M.t - 12} L ${R3(c.lineX)} ${M.t - 2}`}
                fill="none"
                stroke={c.color}
                strokeOpacity={0.55}
                strokeWidth={1}
              />
              <rect
                x={R3(c.cx - c.w / 2)}
                y={c.top}
                width={R3(c.w)}
                height={17}
                rx={4}
                fill={c.color}
                fillOpacity={0.1}
                stroke={c.color}
                strokeOpacity={0.5}
                strokeWidth={1}
              />
              <text
                x={R3(c.cx)}
                y={c.top + 12}
                textAnchor="middle"
                fontSize={10}
                className="font-data"
                fill={c.color}
              >
                {c.label}
              </text>
            </g>
          ))}

          {/* footnote labels — painted after the series so they read over bars and fills.
              The 80%-interval label anchors on whichever side of the band sits farther
              from the captured-line label, so the two never crowd the axis together. */}
          {showInterval ? (
            <text
              x={R3(
                quote &&
                  Math.abs(
                    xScale(quote.line) -
                      xScale(Math.max(interval.p10, domain.lo)),
                  ) < 120
                  ? xScale(Math.min(interval.p90, domain.hi)) - 6
                  : xScale(Math.max(interval.p10, domain.lo)) + 6,
              )}
              y={M.t + ih - 8}
              textAnchor={
                quote &&
                Math.abs(
                  xScale(quote.line) -
                    xScale(Math.max(interval.p10, domain.lo)),
                ) < 120
                  ? "end"
                  : "start"
              }
              className="font-data"
              fill="var(--ps-sapphire)"
              fontSize={10}
              stroke="var(--ps-canvas)"
              strokeWidth={3.5}
              paintOrder="stroke"
            >
              80% interval
            </text>
          ) : null}
          {band &&
          xScale(Math.min(band.upper, domain.hi)) -
            xScale(Math.max(band.lower, domain.lo)) >
            84 ? (
            <text
              x={R3(
                (xScale(Math.max(band.lower, domain.lo)) +
                  xScale(Math.min(band.upper, domain.hi))) /
                  2,
              )}
              y={M.t + ih - 8}
              textAnchor="middle"
              className="font-data"
              fill="var(--chart-tick)"
              fontSize={10}
              stroke="var(--ps-canvas)"
              strokeWidth={3.5}
              paintOrder="stroke"
            >
              no-value band
            </text>
          ) : null}

          {/* probe — defaults to the fair line until the user probes */}
          {probeInfo && probeInfo.active ? (
            <g>
              <line
                x1={xScale(probeInfo.x)}
                x2={xScale(probeInfo.x)}
                y1={M.t}
                y2={M.t + ih}
                stroke="var(--ps-text)"
                strokeWidth={1}
                strokeDasharray="2 2"
              />
              <circle
                cx={xScale(probeInfo.x)}
                cy={yScale(mode === "cdf" ? probeInfo.cdf : probeInfo.density)}
                r={3.5}
                fill="var(--ps-text)"
                stroke="var(--ps-canvas)"
                strokeWidth={1.5}
              />
            </g>
          ) : null}

          {/* pointer capture surface */}
          <rect
            x={M.l}
            y={M.t}
            width={iw}
            height={ih}
            fill="transparent"
            onPointerDown={onPointer}
            onPointerMove={(e) => {
              if (e.buttons === 1 || e.pointerType === "mouse") onPointer(e);
            }}
            style={{ cursor: "crosshair", touchAction: "pan-y" }}
          />
        </svg>

        <p className="pointer-events-none absolute right-2 top-1 text-[10px] text-text-muted">
          hover or focus · ← → to probe
        </p>

        {/* headline probability callout — mockup: pill right of the curve.
            Sits below the reference-chip row so it never covers a chip. */}
        {quote && pOverMarket !== null ? (
          <span className="pointer-events-none absolute right-2 top-12 rounded-[6px] border border-sapphire/40 bg-sapphire-surface/90 px-2 py-0.5 font-data text-[11px] font-medium text-sapphire">
            P(Over {quote.line}) {fmtProb(pOverMarket)}
          </span>
        ) : null}
      </div>

      {/* legend — mockup bottom row inside the distribution panel */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[10.5px] text-text-muted">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full"
            style={{ background: "var(--chart-series-pdf)" }}
          />
          {mode === "pdf" ? "Outcome distribution (PDF)" : "Cumulative (CDF)"}
        </span>
        {band && quote ? (
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-2.5 w-4 rounded-[2px] border border-dashed"
              style={{
                borderColor: "var(--chart-band-novalue-edge)",
                background: "var(--chart-band-novalue)",
              }}
            />
            No-value band ({fmtOdds(quote.overOdds)})
          </span>
        ) : null}
        {quote ? (
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-0 w-4 border-t border-dashed"
              style={{ borderColor: "var(--chart-marker-market)" }}
            />
            Market line
          </span>
        ) : null}
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-0 w-4 border-t border-dashed"
            style={{ borderColor: "var(--chart-marker-median)" }}
          />
          Median (fair line)
        </span>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-0 w-4 border-t border-dashed"
            style={{ borderColor: "var(--chart-marker-mean)" }}
          />
          Mean (projection)
        </span>
        {showInterval ? (
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-0 w-4 border-t border-dotted"
              style={{ borderColor: "var(--chart-axis)" }}
            />
            80% interval
          </span>
        ) : null}
      </div>

      {/* probe readout — defaults to the fair line until the user probes */}
      <div
        aria-live="polite"
        className="mt-3 grid grid-cols-3 gap-px overflow-hidden rounded-[4px] border border-hairline bg-hairline"
      >
        {[
          {
            label: `P(≤ x)`,
            value: fmtProb(probeInfo.cdf),
          },
          {
            label: `P(≥ x)`,
            value: fmtProb(probeInfo.surv),
          },
          {
            label: discrete ? "PMF(x)" : "density(x)",
            value:
              probeInfo.density < 0.01
                ? probeInfo.density.toExponential(1)
                : probeInfo.density.toFixed(3),
          },
        ].map((cell) => (
          <div key={cell.label} className="bg-workspace px-3 py-2">
            <p className="label-micro">
              {cell.label}
              <span className="ml-1 normal-case tracking-normal text-text">
                · x = {fmtX(probeInfo.x)} {unit}
                {!probeInfo.active ? (
                  <span className="text-text-muted"> (fair line)</span>
                ) : null}
              </span>
            </p>
            <p className="mt-0.5 font-data text-sm text-text">{cell.value}</p>
          </div>
        ))}
      </div>

      {/* accessible data table alternative */}
      {tableOpen ? (
        <DistributionTable
          law={law}
          discrete={discrete}
          domain={domain}
          unit={unit}
        />
      ) : null}
    </div>
  );
}

/* ---------- tabular alternative (accessibility & verification) ---------- */

function DistributionTable({
  law,
  discrete,
  domain,
  unit,
}: {
  law: DistLaw;
  discrete: boolean;
  domain: { lo: number; hi: number };
  unit: string;
}) {
  const rows = useMemo(() => {
    const out: Array<{ x: number; p: number; cdf: number; surv: number }> = [];
    if (law.kind === "negbin") {
      for (
        let k = Math.max(0, Math.floor(domain.lo));
        k <= Math.ceil(domain.hi);
        k++
      ) {
        const cdf = lawCdf(k, law);
        const surv = 1 - lawCdf(k - 1, law);
        const p = negBinPmf(k, law.nb);
        if (p < 1e-4 && (k < law.nb.mu - 2 || k > law.nb.mu + 3)) continue;
        out.push({ x: k, p, cdf, surv });
      }
    } else {
      const lo = Math.max(domain.lo, 0);
      const stepX = Math.max(
        2.5,
        Math.round((domain.hi - lo) / 24 / 2.5) * 2.5,
      );
      for (let x = lo; x <= domain.hi; x += stepX) {
        const cdf = lawCdf(Math.max(x, 0.01), law);
        out.push({
          x: Math.round(x * 10) / 10,
          p: compoundPdf(x, {
            r: law.nb.r,
            mu: law.nb.mu,
            k: law.gamma!.k,
            theta: law.gamma!.theta,
          }),
          cdf,
          surv: 1 - cdf,
        });
      }
    }
    return out;
  }, [law, domain]);

  return (
    <div className="mt-3 max-h-72 overflow-auto rounded-[4px] border border-hairline">
      <table className="w-full border-collapse text-xs">
        <caption className="sr-only">
          Tabular distribution data: x, probability mass or density, cumulative
          probability, and survival probability
        </caption>
        <thead className="sticky top-0 bg-workspace">
          <tr className="text-left">
            <th scope="col" className="px-3 py-2 font-medium text-text-muted">
              x ({unit})
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-right font-medium text-text-muted"
            >
              {discrete ? "P(X = x)" : "density"}
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-right font-medium text-text-muted"
            >
              P(X ≤ x)
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-right font-medium text-text-muted"
            >
              P(X ≥ x)
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.x} className="hairline-t border-hairline">
              <td className="px-3 py-1.5 font-data text-text">{r.x}</td>
              <td className="px-3 py-1.5 text-right font-data text-text">
                {r.p < 0.0001 ? r.p.toExponential(1) : r.p.toFixed(4)}
              </td>
              <td className="px-3 py-1.5 text-right font-data text-text">
                {(r.cdf * 100).toFixed(1)}%
              </td>
              <td className="px-3 py-1.5 text-right font-data text-text">
                {(r.surv * 100).toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
