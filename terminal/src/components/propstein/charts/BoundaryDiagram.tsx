"use client";

/* PropStein — value-boundary diagram
   A precise, small visualization of the no-value band derivation:
   the survival curve S(L) = P(X ≥ L) against the two break-even
   thresholds. Where S crosses be(over) from above and
   1 − be(under) from below, the band lives.
   Responsive: measures its container so labels render at true
   pixel sizes on every viewport — no horizontal scrolling. */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { DistLaw, lawSurvival } from "@/lib/propstein/distributions";
import { MARKET_META, type MarketKey } from "@/lib/propstein/types";
import type { ValueBoundaries } from "@/lib/propstein/model";

/** Quantize emitted coordinates — hydration-safe across engines. */
const R3 = (v: number) => Math.round(v * 1000) / 1000;

export function BoundaryDiagram({
  law,
  boundaries,
  quoteLine,
  market,
  height = 190,
}: {
  law: DistLaw;
  boundaries: ValueBoundaries;
  quoteLine: number | null;
  market: MarketKey;
  height?: number;
}) {
  const svgId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);

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

  const W = Math.max(320, Math.min(680, width));
  const H = height;
  const M = { l: 40, r: 14, t: 22, b: 24 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;

  const geom = useMemo(() => {
    const lo = Math.max(0, boundaries.lower - 4);
    const hi = boundaries.upper + 4;
    const xs = (x: number) => R3(M.l + ((x - lo) / (hi - lo)) * iw);
    const ys = (p: number) => R3(M.t + ih - p * ih);
    const N = 140;
    const pts: Array<[number, number]> = [];
    for (let i = 0; i <= N; i++) {
      const x = lo + ((hi - lo) * i) / N;
      pts.push([x, lawSurvival(x, law)]);
    }
    return { lo, hi, xs, ys, pts };
  }, [law, boundaries, M.l, ih, iw, M.t]);

  const { xs, ys, pts, lo, hi } = geom;
  const unit = MARKET_META[market].unit;

  const xTicks = useMemo(() => {
    const span = hi - lo;
    const step = market === "receptions" ? Math.max(1, Math.round(span / 6)) : Math.max(2, Math.round(span / 5 / 2) * 2);
    const out: number[] = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(t);
    return out;
  }, [lo, hi, market]);

  return (
    <div ref={wrapRef}>
      <svg
        role="img"
        aria-labelledby={`${svgId}-title`}
        width={W}
        height={H}
        className="max-w-full"
      >
        <title id={`${svgId}-title`}>
          Survival curve P(X ≥ L) with the two break-even thresholds. The no-value band is the range
          of lines between the thresholds; the captured line is marked.
        </title>
        {/* threshold lines — opposite ends, clear of one another.
            Framing matches the survival axis: over clears when S(L) > beOver;
            under clears when S(L) < 1 − beUnder. */}
        <line x1={M.l} x2={W - M.r} y1={ys(boundaries.breakEvenOver)} y2={ys(boundaries.breakEvenOver)} stroke="var(--ps-caution)" strokeWidth={1} strokeDasharray="5 3" opacity={0.85} />
        <line x1={M.l} x2={W - M.r} y1={ys(1 - boundaries.breakEvenUnder)} y2={ys(1 - boundaries.breakEvenUnder)} stroke="var(--ps-caution)" strokeWidth={1} strokeDasharray="2 3" opacity={0.85} />
        <text x={W - M.r - 2} y={ys(boundaries.breakEvenOver) - 6} textAnchor="end" className="font-data" fill="var(--ps-caution)" fontSize={10.5} stroke="var(--ps-canvas)" strokeWidth={2.5} paintOrder="stroke">
          over clears above {(boundaries.breakEvenOver * 100).toFixed(1)}%
        </text>
        <text x={M.l + 26} y={ys(1 - boundaries.breakEvenUnder) + 24} textAnchor="start" className="font-data" fill="var(--ps-caution)" fontSize={10.5} stroke="var(--ps-canvas)" strokeWidth={2.5} paintOrder="stroke">
          under clears below {((1 - boundaries.breakEvenUnder) * 100).toFixed(1)}%
        </text>

        {/* no-value band */}
        <rect
          x={xs(boundaries.lower)}
          y={ys(boundaries.breakEvenOver)}
          width={Math.max(1, xs(boundaries.upper) - xs(boundaries.lower))}
          height={Math.max(1, ys(1 - boundaries.breakEvenUnder) - ys(boundaries.breakEvenOver))}
          fill="rgba(148, 163, 184, 0.13)"
          stroke="rgba(148, 163, 184, 0.35)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
        <text
          x={Math.min(xs(boundaries.upper) + 8, W - M.r - 78)}
          y={ys(1 - boundaries.breakEvenUnder) + 21}
          textAnchor="start"
          className="font-data" fill="var(--chart-tick)"
          fontSize={10.5}
          stroke="var(--ps-canvas)"
          strokeWidth={2}
          paintOrder="stroke"
        >
          no-value band
        </text>

        {/* axis */}
        <line x1={M.l} x2={W - M.r} y1={M.t + ih} y2={M.t + ih} stroke="var(--ps-border)" strokeWidth={1} />
        {[0, 0.5, 1].map((p) => (
          <text key={p} x={M.l - 6} y={ys(p) + 3} textAnchor="end" className="font-data" fill="var(--chart-tick)" fontSize={10}>
            {(p * 100).toFixed(0)}%
          </text>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={xs(t)} y={H - 7} textAnchor="middle" className="font-data" fill="var(--chart-tick)" fontSize={10}>
            {market === "receptions" ? t : t.toFixed(0)}
          </text>
        ))}

        {/* survival curve */}
        <path
          d={pts.map(([x, p], i) => `${i === 0 ? "M" : "L"} ${xs(x)} ${ys(p)}`).join(" ")}
          fill="none"
          stroke="var(--chart-series-pdf)"
          strokeWidth={1.8}
        />

        {/* boundaries */}
        {[boundaries.lower, boundaries.upper].map((b, i) => (
          <g key={i}>
            <line x1={xs(b)} x2={xs(b)} y1={M.t} y2={M.t + ih} stroke="var(--chart-axis)" strokeWidth={1} strokeDasharray="1.5 3" />
            <circle
              cx={xs(b)}
              cy={ys(i === 0 ? boundaries.breakEvenOver : 1 - boundaries.breakEvenUnder)}
              r={3}
              fill="var(--ps-canvas)"
              stroke="var(--ps-text)"
              strokeWidth={1.5}
            />
          </g>
        ))}

        {/* captured line — label top of its marker, anchored away from the edge */}
        {quoteLine !== null && quoteLine >= lo && quoteLine <= hi ? (
          <g>
            <line x1={xs(quoteLine)} x2={xs(quoteLine)} y1={M.t} y2={M.t + ih} stroke="var(--ps-caution)" strokeWidth={1.6} />
            <text
              x={xs(quoteLine) > M.l + iw * 0.7 ? xs(quoteLine) - 5 : xs(quoteLine) + 5}
              y={M.t - 7}
              textAnchor={xs(quoteLine) > M.l + iw * 0.7 ? "end" : "start"}
              className="font-data" fill="var(--ps-caution)"
              fontSize={10.5}
              stroke="var(--ps-canvas)"
              strokeWidth={2.5}
              paintOrder="stroke"
            >
              line {quoteLine}
            </text>
          </g>
        ) : null}
      </svg>
      <figcaption className="mt-1.5 text-[10px] text-text-muted">
        P(X ≥ L) in {unit}. Over clears break-even above its threshold; under clears below
        its own. Band: {boundaries.lower.toFixed(1)}–{boundaries.upper.toFixed(1)} {unit}.
      </figcaption>
    </div>
  );
}
