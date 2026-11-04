"use client";

/* PropStein — compact distribution sparkline
   Used in the detail sheet and overview cards. Exact math,
   median + captured-line markers, no axes (labels live outside). */

import { useId, useMemo } from "react";
import {
  DistLaw,
  lawQuantile,
  negBinPmf,
  negBinSupportMax,
  compoundPdf,
} from "@/lib/propstein/distributions";
import { MARKET_META, type MarketKey } from "@/lib/propstein/types";

/** Quantize emitted coordinates — hydration-safe across engines. */
const R3 = (v: number) => Math.round(v * 1000) / 1000;

export function SparkDistribution({
  law,
  market,
  quoteLine,
  height = 64,
  className,
}: {
  law: DistLaw;
  market: MarketKey;
  quoteLine: number | null;
  height?: number;
  className?: string;
}) {
  const svgId = useId();
  const discrete = law.kind === "negbin";
  const W = 320;
  const H = height;
  const PAD = 2;

  const geom = useMemo(() => {
    const lo = Math.max(0, lawQuantile(0.005, law));
    const hi = lawQuantile(0.995, law);
    const pad = (hi - lo) * 0.05;
    const dlo = lo - pad;
    const dhi = hi + pad;
    const xs = (x: number) => R3(PAD + ((x - dlo) / (dhi - dlo)) * (W - PAD - 10));

    if (discrete) {
      const pts: Array<{ k: number; p: number }> = [];
      const nMax = Math.min(negBinSupportMax(law.nb), Math.ceil(dhi));
      for (let k = 0; k <= nMax; k++) {
        const p = negBinPmf(k, law.nb);
        if (p < 1e-4 && k > law.nb.mu + 2) continue;
        pts.push({ k, p });
      }
      const maxP = Math.max(...pts.map((p) => p.p), 1e-9);
      return { xs, dlo, dhi, pts, maxP, curve: null as null };
    }
    const N = 160;
    const pts: Array<[number, number]> = [];
    for (let i = 0; i <= N; i++) {
      const x = dlo + ((dhi - dlo) * i) / N;
      if (x <= 0) continue;
      pts.push([
        x,
        compoundPdf(x, { r: law.nb.r, mu: law.nb.mu, k: law.gamma!.k, theta: law.gamma!.theta }),
      ]);
    }
    const maxP = Math.max(...pts.map((p) => p[1]), 1e-9);
    return { xs, dlo, dhi, pts: null, maxP, curve: pts };
  }, [law, discrete]);

  const ys = (p: number) => R3(H - PAD - (p / (geom.maxP * 1.1)) * (H - 2 * PAD));
  const unit = MARKET_META[market].unit;

  return (
    <svg
      role="img"
      aria-label={`Distribution sparkline: ${market.replace("_", " ")}. Median and captured line marked.`}
      viewBox={`0 0 ${W} ${H}`}
      className={className}
      width="100%"
    >
      <title id={svgId}>{`Distribution of ${unit}`}</title>
      {/* baseline */}
      <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="var(--ps-border)" strokeWidth={1} />
      {/* series */}
      {geom.pts
        ? geom.pts.map((p) => {
            const barW = R3(Math.min(14, (W / (geom.dhi - geom.dlo)) * 0.68));
            return (
              <rect
                key={p.k}
                x={R3(geom.xs(p.k) - barW / 2)}
                y={ys(p.p)}
                width={barW}
                height={R3(Math.max(0, H - PAD - ys(p.p)))}
                fill="var(--chart-series-pdf)"
                opacity={0.8}
                rx={1}
              />
            );
          })
        : null}
      {geom.curve ? (
        <path
          d={geom.curve.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${geom.xs(x)} ${ys(y)}`).join(" ")}
          fill="none"
          stroke="var(--chart-series-pdf)"
          strokeWidth={1.6}
        />
      ) : null}
      {/* captured line */}
      {quoteLine !== null && quoteLine >= geom.dlo && quoteLine <= geom.dhi ? (
        <line
          x1={geom.xs(quoteLine)}
          x2={geom.xs(quoteLine)}
          y1={PAD}
          y2={H - PAD}
          stroke="var(--chart-marker-market)"
          strokeWidth={1.4}
        />
      ) : null}
    </svg>
  );
}
