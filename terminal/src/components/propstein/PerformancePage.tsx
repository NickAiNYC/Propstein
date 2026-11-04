"use client";

/* ============================================================
   PropStein — Performance & audit (Phase 5)
   Full-board evaluation: complete cohorts, CLV distribution
   with mean/CI, calibration by predicted-probability decile,
   model version timeline, exclusions, and governance gates.
   Insufficient evidence is a designed state, never styled-up
   into a positive claim.
   ============================================================ */

import { useMemo } from "react";
import { useApp } from "@/lib/propstein/router";
import { ARCHIVE, ARCHIVE_COHORT, VERSION_TIMELINE } from "@/lib/propstein/archive";
import { GOVERNANCE } from "@/lib/propstein/types";
import { summarizeClv, standardizedClv } from "@/lib/propstein/model";
import { fmtPct, fmtSigned } from "@/lib/propstein/format";
import { Panel, SectionHeading } from "./primitives";
import { cn } from "@/lib/utils";
import { ShieldCheck, ShieldAlert, GitCommitHorizontal, CircleSlash } from "lucide-react";

/** Quantize emitted coordinates — hydration-safe across engines. */
const R3 = (v: number) => Math.round(v * 1000) / 1000;

/* ---------- CLV histogram ---------- */

function ClvHistogram({ values }: { values: number[] }) {
  const W = 640;
  const H = 200;
  const M = { l: 40, r: 12, t: 12, b: 26 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;

  const geom = useMemo(() => {
    const bins = 21;
    const lo = -2.5;
    const hi = 2.5;
    const counts = new Array(bins).fill(0);
    for (const v of values) {
      const idx = Math.min(bins - 1, Math.max(0, Math.floor(((v - lo) / (hi - lo)) * bins)));
      counts[idx]++;
    }
    const maxC = Math.max(...counts);
    return { bins, lo, hi, counts, maxC };
  }, [values]);

  const xs = (x: number) => R3(M.l + ((x - geom.lo) / (geom.hi - geom.lo)) * iw);
  const ys = (c: number) => R3(M.t + ih - (c / geom.maxC) * ih);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;

  return (
    <svg role="img" aria-labelledby="clv-hist-title" viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 440 }}>
      <title id="clv-hist-title">
        Histogram of standardized CLV — (closing line minus model fair) over model sigma, across all
        evaluable markets.
      </title>
      {[-2, -1, 0, 1, 2].map((t) => (
        <g key={t}>
          <line x1={xs(t)} x2={xs(t)} y1={M.t} y2={M.t + ih} stroke="var(--chart-grid)" strokeWidth={1} />
          <text x={xs(t)} y={H - 8} textAnchor="middle" className="font-data" fill="var(--chart-tick)" fontSize={10}>
            {fmtSigned(t, 0)}σ
          </text>
        </g>
      ))}
      {geom.counts.map((c, i) => {
        const x0 = M.l + (i / geom.bins) * iw;
        const x1 = M.l + ((i + 1) / geom.bins) * iw;
        return (
          <rect
            key={i}
            x={x0 + 0.5}
            y={ys(c)}
            width={Math.max(0, x1 - x0 - 1)}
            height={M.t + ih - ys(c)}
            fill="var(--chart-series-pdf)"
            opacity={0.8}
            rx={1}
          />
        );
      })}
      {/* mean line + legend annotation, clear of bars */}
      <line x1={xs(mean)} x2={xs(mean)} y1={M.t} y2={M.t + ih} stroke="var(--ps-mint)" strokeWidth={1.6} strokeDasharray="5 3" />
      <line x1={W - M.r - 60} x2={W - M.r - 48} y1={M.t + 8} y2={M.t + 8} stroke="var(--ps-mint)" strokeWidth={1.6} strokeDasharray="4 3" />
      <text x={W - M.r - 44} y={M.t + 11} textAnchor="start" className="font-data" fill="var(--ps-mint)" fontSize={10}>
        mean {fmtSigned(mean, 3)}σ
      </text>
      {/* zero reference */}
      <line x1={xs(0)} x2={xs(0)} y1={M.t} y2={M.t + ih} stroke="var(--ps-border)" strokeWidth={1} />
    </svg>
  );
}

/* ---------- calibration chart ---------- */

interface DecilePoint {
  predicted: number;
  observed: number;
  n: number;
  ci: number;
}

function CalibrationChart({ points }: { points: DecilePoint[] }) {
  const W = 480;
  const H = 320;
  const M = { l: 44, r: 14, t: 14, b: 34 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const xs = (p: number) => R3(M.l + p * iw);
  const ys = (p: number) => R3(M.t + ih - p * ih);

  return (
    <svg role="img" aria-labelledby="calib-title" viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 380 }}>
      <title id="calib-title">
        Calibration by predicted-probability decile: observed over rate versus model predicted
        probability, with 95% binomial intervals. Dashed line is perfect calibration.
      </title>
      {/* diagonal */}
      <line x1={xs(0)} y1={ys(0)} x2={xs(1)} y2={ys(1)} stroke="var(--ps-border)" strokeWidth={1} strokeDasharray="4 4" />
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={`y${t}`}>
          <line x1={M.l} x2={W - M.r} y1={ys(t)} y2={ys(t)} stroke="var(--chart-grid)" strokeWidth={1} />
          <text x={M.l - 6} y={ys(t) + 3} textAnchor="end" className="font-data" fill="var(--chart-tick)" fontSize={10}>
            {(t * 100).toFixed(0)}%
          </text>
        </g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <text key={`x${t}`} x={xs(t)} y={H - 18} textAnchor="middle" className="font-data" fill="var(--chart-tick)" fontSize={10}>
          {(t * 100).toFixed(0)}%
        </text>
      ))}
      <text x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle" fill="var(--chart-tick)" fontSize={9}>
        model predicted P(over) at close
      </text>
      {/* points */}
      {points.map((pt, i) => (
        <g key={i}>
          <line
            x1={xs(pt.predicted)}
            x2={xs(pt.predicted)}
            y1={ys(Math.max(0, pt.observed - pt.ci))}
            y2={ys(Math.min(1, pt.observed + pt.ci))}
            stroke="var(--chart-series-pdf)"
            strokeWidth={1.4}
            opacity={0.65}
          />
          <circle
            cx={xs(pt.predicted)}
            cy={ys(pt.observed)}
            r={3.6}
            fill="var(--chart-series-pdf)"
            stroke="var(--ps-canvas)"
            strokeWidth={1.4}
          />
          <text x={xs(pt.predicted)} y={ys(pt.observed) - 8} textAnchor="middle" className="font-data" fill="var(--chart-tick)" fontSize={8.5}>
            {pt.n}
          </text>
        </g>
      ))}
    </svg>
  );
}

/* ---------- main page ---------- */

export function PerformancePage() {
  const { setRoute } = useApp();

  const evaluable = useMemo(() => ARCHIVE.filter((m) => m.evaluable), []);
  const clv = useMemo(
    () =>
      summarizeClv(
        evaluable.map((m) => ({ fairLine: m.fairLine, closeLine: m.closeLine!, sd: m.sd }))
      ),
    [evaluable]
  );
  const clvValues = useMemo(
    () => evaluable.map((m) => standardizedClv({ fairLine: m.fairLine, closeLine: m.closeLine!, sd: m.sd })),
    [evaluable]
  );
  const deciles = useMemo(() => {
    const withPred = evaluable.filter((m) => m.predictedOverAtClose !== null);
    const sorted = [...withPred].sort((a, b) => a.predictedOverAtClose! - b.predictedOverAtClose!);
    const pts: DecilePoint[] = [];
    for (let d = 0; d < 10; d++) {
      const slice = sorted.slice(
        Math.floor((d * sorted.length) / 10),
        Math.floor(((d + 1) * sorted.length) / 10)
      );
      if (slice.length === 0) continue;
      const predicted = slice.reduce((a, b) => a + b.predictedOverAtClose!, 0) / slice.length;
      const observed = slice.filter((m) => m.overHit).length / slice.length;
      const ci = 1.96 * Math.sqrt((observed * (1 - observed)) / slice.length);
      pts.push({ predicted, observed, n: slice.length, ci });
    }
    return pts;
  }, [evaluable]);

  const gateProgress = ARCHIVE_COHORT.evaluable / GOVERNANCE.confirmatoryThreshold;

  return (
    <div className="flex flex-col gap-6">
      {/* header */}
      <header>
        <p className="label-micro">Public evaluation · updated after each completed week</p>
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text">
          Performance & audit
        </h1>
        <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-text-muted">
          Every modeled market with a captured closing line is evaluated — nothing is excluded after
          the fact except for the stated reasons below. Selective presentation of favorable weeks or
          players is a reporting failure this page is built to prevent. Evaluation cohorts below
          cover <span className="text-text">NFL receiving markets (Weeks 3–8, 2026)</span> — NBA
          markets launched with the Nov 6 slate and have no settled history yet, so none are
          represented in these figures.
        </p>
      </header>

      {/* governance banner */}
      <Panel className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between lg:p-5">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-caution" aria-hidden />
          <div>
            <p className="text-sm font-medium text-text">Commercial tiers remain frozen</p>
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
              The confirmatory evidence gate requires {GOVERNANCE.confirmatoryThreshold} evaluable
              markets per sport under the preregistered specification. Current cohort:{" "}
              <span className="font-data text-text">{ARCHIVE_COHORT.evaluable}</span> of{" "}
              <span className="font-data text-text">{GOVERNANCE.confirmatoryThreshold}</span> (
              {fmtPct(gateProgress, 0)}). The screening threshold (N ≥ {GOVERNANCE.screenedThreshold})
              has been passed; that does not activate paid features.
            </p>
          </div>
        </div>
        <div className="w-full max-w-xs shrink-0 lg:w-56">
          <div
            className="h-1.5 w-full overflow-hidden rounded-[2px] bg-workspace"
            role="progressbar"
            aria-valuenow={ARCHIVE_COHORT.evaluable}
            aria-valuemin={0}
            aria-valuemax={GOVERNANCE.confirmatoryThreshold}
            aria-label={`Confirmatory cohort progress: ${ARCHIVE_COHORT.evaluable} of ${GOVERNANCE.confirmatoryThreshold} markets`}
          >
            <span
              className="block h-full rounded-[2px] bg-caution"
              style={{ width: `${Math.min(100, gateProgress * 100)}%` }}
            />
          </div>
          <p className="mt-1 text-right font-data text-[10px] text-text-muted">
            {ARCHIVE_COHORT.evaluable}/{GOVERNANCE.confirmatoryThreshold}
          </p>
        </div>
      </Panel>

      {/* cohort summary */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-hairline bg-hairline md:grid-cols-5">
        {[
          { label: "Markets settled (wk 3–8)", value: `${ARCHIVE_COHORT.total}`, hint: "NFL receiving markets", span: false },
          { label: "Evaluable", value: `${ARCHIVE_COHORT.evaluable}`, hint: "captured close + result", span: false },
          { label: "Excluded", value: `${ARCHIVE_COHORT.excluded}`, hint: "reasons itemized below", span: false },
          { label: "Mean CLV", value: `${fmtSigned(clv.mean, 3)}σ`, hint: `95% CI ±${clv.ci95.toFixed(3)}σ`, span: false },
          { label: "Close moved toward model", value: fmtPct(clv.beatCloseRate, 1), hint: "of evaluable markets", span: true },
        ].map((s) => (
          <div key={s.label} className={cn("bg-workspace px-3.5 py-3", s.span && "col-span-2 md:col-span-1")}>
            <p className="label-micro">{s.label}</p>
            <p className="mt-1.5 font-data text-xl leading-none text-text">{s.value}</p>
            <p className="mt-1 text-[10px] text-text-muted">{s.hint}</p>
          </div>
        ))}
      </div>

      {/* CLV + calibration */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel className="p-4 lg:p-5">
          <SectionHeading
            title="Closing-line value distribution"
            subtitle="Standardized CLV = (closing line − model fair) / model σ · all evaluable markets"
          />
          <div className="mt-4 overflow-x-auto">
            <ClvHistogram values={clvValues} />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
            A calibrated model sits near zero: the market closes where the model expected, on
            average. The current cohort mean is{" "}
            <span className="font-data text-text">{fmtSigned(clv.mean, 3)}σ</span> with a 95%
            confidence interval of ±{clv.ci95.toFixed(3)}σ — statistically indistinguishable from
            zero. That is the honest reading: no closing-line edge is claimed.
          </p>
        </Panel>

        <Panel className="p-4 lg:p-5">
          <SectionHeading
            title="Calibration by predicted probability"
            subtitle="Observed over rate vs model P(over) at the closing line · deciles with 95% intervals"
          />
          <div className="mt-4 overflow-x-auto">
            <CalibrationChart points={deciles} />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
            Low-probability deciles show observed rates modestly below prediction — the model is
            slightly overconfident in long-shot overs at current N. The deviation is within sampling
            uncertainty, is flagged as a known limitation, and is monitored weekly rather than
            smoothed away.
          </p>
        </Panel>
      </div>

      {/* exclusions + weekly cohorts */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel className="p-4 lg:p-5">
          <SectionHeading title="Exclusions, itemized" subtitle="Why markets leave the evaluable cohort" />
          <ul className="mt-4 flex flex-col gap-2">
            {[
              { reason: "No closing line captured", n: ARCHIVE_COHORT.exclusions.NO_CLOSE ?? 0, note: "market never posted a close in the capture window" },
              { reason: "Stale close", n: ARCHIVE_COHORT.exclusions.STALE_CLOSE ?? 0, note: "closing quote failed the freshness gate" },
              { reason: "Postponed / void", n: (ARCHIVE_COHORT.exclusions.POSTPONED ?? 0) + (ARCHIVE_COHORT.exclusions.VOID ?? 0), note: "event not completed as scheduled" },
            ].map((row) => (
              <li
                key={row.reason}
                className="flex items-center justify-between gap-3 rounded-[4px] border border-hairline bg-workspace px-3 py-2.5"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <CircleSlash className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-text">{row.reason}</p>
                    <p className="truncate text-[10px] text-text-muted">{row.note}</p>
                  </div>
                </div>
                <span className="font-data text-sm text-text">{row.n}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
            Excluded markets are counted, listed, and never silently dropped. The full-board
            obligation applies to positive and negative weeks alike.
          </p>
        </Panel>

        <Panel className="p-4 lg:p-5">
          <SectionHeading title="Weekly cohorts" subtitle="Evaluable vs total settled, by week" />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[420px] border-collapse text-xs">
              <thead>
                <tr className="text-left text-text-muted">
                  <th scope="col" className="pb-2 font-medium">Week</th>
                  <th scope="col" className="pb-2 text-right font-medium">Settled</th>
                  <th scope="col" className="pb-2 text-right font-medium">Evaluable</th>
                  <th scope="col" className="pb-2 text-right font-medium">Excluded</th>
                  <th scope="col" className="pb-2 text-right font-medium">Coverage</th>
                </tr>
              </thead>
              <tbody>
                {ARCHIVE_COHORT.byWeek.map((w) => (
                  <tr key={w.week} className="hairline-t border-hairline">
                    <td className="py-2 font-data text-text">{w.week}</td>
                    <td className="py-2 text-right font-data text-text">{w.total}</td>
                    <td className="py-2 text-right font-data text-text">{w.evaluable}</td>
                    <td className="py-2 text-right font-data text-text-muted">{w.total - w.evaluable}</td>
                    <td className="py-2 text-right font-data text-text-muted">
                      {((w.evaluable / w.total) * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* version timeline */}
      <Panel className="p-4 lg:p-5">
        <SectionHeading
          title="Model version timeline"
          subtitle="Chronological deployment history; each cohort above is labeled with the version that produced it"
        />
        <ol className="mt-5 flex flex-col gap-0">
          {VERSION_TIMELINE.map((v, i) => (
            <li key={v.version} className="relative flex gap-4 pb-6 last:pb-0">
              {/* rail */}
              <span className="absolute left-[7px] top-5 h-full w-px bg-hairline last:hidden" aria-hidden />
              <span
                className={cn(
                  "relative mt-1 inline-flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-full border",
                  i === VERSION_TIMELINE.length - 1
                    ? "border-sapphire bg-sapphire-surface"
                    : "border-hairline bg-workspace"
                )}
                aria-hidden
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    i === VERSION_TIMELINE.length - 1 ? "bg-sapphire" : "bg-text-muted"
                  )}
                />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-baseline gap-x-3">
                  <span className="font-data text-sm font-medium text-text">{v.version}</span>
                  <span className="text-[11px] text-text-muted">
                    {v.since} · deployed {v.deployedAt}
                    {i === VERSION_TIMELINE.length - 1 ? (
                      <span className="ml-1.5 rounded-[2px] border border-sapphire/40 bg-sapphire-surface px-1 py-px font-data text-[9px] text-sapphire">current</span>
                    ) : null}
                  </span>
                  <span className="ml-auto font-data text-[10px] text-text-muted">
                    n = {ARCHIVE_COHORT.byVersion.find((x) => x.version === v.version)?.n ?? 0} evaluable
                  </span>
                </p>
                <p className="mt-1 text-xs leading-relaxed text-text-muted">{v.note}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      {/* known limitations */}
      <Panel className="p-4 lg:p-5">
        <SectionHeading title="Known limitations" subtitle="Stated plainly, monitored weekly" />
        <ul className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {[
            "Slight overconfidence in low-probability overs visible in calibration deciles 1–3; within sampling uncertainty at current N.",
            "Catch sequencing independence is an approximation; real targets cluster on scripted drives, fattening both tails.",
            "Yards-per-reception Gamma fits are pool-then-adjust; route-depth mix shifts (trades, injuries) reprice slowly.",
            "Game-script conditioning (v3.2.1) has only two weeks of live evaluation; its cohort contribution is still small.",
            "Closing lines are captured, not streamed — a close captured 50 minutes before kickoff can differ from the true final close.",
            "Calibration deciles pool both markets (receptions and yards); per-market calibration needs more evaluable N before publication.",
          ].map((lim) => (
            <li key={lim} className="rounded-[4px] border border-hairline bg-workspace p-3 text-xs leading-relaxed text-text-muted">
              {lim}
            </li>
          ))}
        </ul>
      </Panel>

      {/* posture footer */}
      <div className="flex flex-col gap-3 px-1 text-[11px] leading-relaxed text-text-muted sm:flex-row sm:items-start">
        <p className="flex items-start gap-2 sm:flex-1">
          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-caution" aria-hidden />
          <span>
            Research posture: this page reports complete evaluation cohorts. It never presents
            selectively positive records, and no staking, bankroll, or pricing advice is offered
            anywhere in the terminal.
          </span>
        </p>
        <p className="flex items-center gap-4 sm:shrink-0">
          <button
            type="button"
            onClick={() => setRoute({ view: "methodology" })}
            className="text-sapphire underline decoration-dotted underline-offset-2"
          >
            Methodology
          </button>
          <button
            type="button"
            onClick={() => setRoute({ view: "boundaries" })}
            className="text-sapphire underline decoration-dotted underline-offset-2"
          >
            Value boundaries
          </button>
        </p>
      </div>
    </div>
  );
}
