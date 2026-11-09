'use client';

/**
 * PropStein — Luck Meter (deliverable 5).
 *
 * Reports the user's record honestly: evaluable count, exclusions with
 * reason-code histogram, mean CLV, shrunk estimate, game-clustered bootstrap
 * interval, percentage beating close, calibration where model probabilities
 * exist, slices with minimum-sample warnings, and the six verdict states.
 *
 * Forbidden claims are structurally impossible here: the copy registry has no
 * such strings and the copy-compliance test scans this file.
 */

import { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts';
import { Note, SectionLabel, fmtPp } from './shared';
import { cn } from '@/lib/utils';
import type { LuckMeterReport } from '@/lib/domain/types';

const VERDICT_STYLES: Record<string, string> = {
  'NO RECORD': 'border-zinc-400/40 bg-zinc-100 text-zinc-600',
  'INSUFFICIENT SAMPLE': 'border-amber-700/40 bg-amber-700/5 text-amber-800',
  'DESCRIPTIVE ONLY': 'border-zinc-500/40 bg-zinc-500/5 text-zinc-700',
  INCONCLUSIVE: 'border-amber-700/40 bg-amber-700/5 text-amber-800',
  'POSITIVE BUT UNPROVEN': 'border-amber-800/40 bg-amber-800/5 text-amber-900',
  'GATE PASSED': 'border-teal-800/40 bg-teal-800/5 text-teal-900',
};

export function LuckMeter({ refreshKey }: { refreshKey: number }) {
  const [report, setReport] = useState<LuckMeterReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await fetch('/api/records/luck-meter');
        const json = await res.json();
        if (!cancelled && json.ok) setReport(json.report);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (loading && !report) {
    return <div className="pst-card rounded-md p-10 text-center text-[13px] text-zinc-400">Computing your record…</div>;
  }
  if (!report) return null;

  const histData = report.exclusions.map((e) => ({ name: e.reason, count: e.count }));

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-zinc-900">Your record, reported honestly</h2>
        <p className="mt-0.5 text-[12.5px] text-zinc-500 max-w-2xl">
          Descriptive statistics over your graded ledger entries. This record does not authorize any commercial
          actionable-signal claim. This is not a betting recommendation.
        </p>
      </div>

      {/* Verdict chip */}
      <div className="pst-card rounded-md p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <SectionLabel>Record verdict</SectionLabel>
            <span
              role="status"
              aria-live="polite"
              aria-label={`Record verdict: ${report.verdict}. ${report.verdictDisplayRule}`}
              className={cn(
                'inline-flex items-center rounded-sm border px-3 py-1 mt-1 text-sm font-semibold tracking-wide',
                VERDICT_STYLES[report.verdict] ?? VERDICT_STYLES['DESCRIPTIVE ONLY'],
              )}
            >
              {report.verdict}
            </span>
          </div>
          <p className="text-[13px] text-zinc-600 max-w-md">{report.verdictDisplayRule}</p>
        </div>
        {report.notes.length > 0 && (
          <div className="mt-3 space-y-1">
            {report.notes.map((n, i) => (
              <Note key={i} tone={report.verdict === 'GATE PASSED' ? 'teal' : 'warn'}>
                {n}
              </Note>
            ))}
          </div>
        )}
      </div>

      {/* Headline stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label="Evaluable entries" value={String(report.evaluableCount)} />
        <Stat label="Excluded entries (retained with reason codes)" value={String(report.excludedCount)} />
        <Stat label="Mean price CLV" value={fmtPp(report.meanClvPp)} />
        <Stat label="Shrunk CLV estimate" value={fmtPp(report.shrunkClvPp)} sub={`shrinkage N/(N+100) applied`} />
        <Stat
          label="Confidence interval (95%, game-clustered bootstrap)"
          value={
            report.confidenceIntervalPp
              ? `[${report.confidenceIntervalPp.lower.toFixed(2)}, ${report.confidenceIntervalPp.upper.toFixed(2)}] pp`
              : '—'
          }
          sub={`${report.bootstrapReplicates.toLocaleString()} replicates · seed ${report.bootstrapSeed}`}
        />
        <Stat
          label="Entries beating close"
          value={report.beatClosePct !== null ? `${report.beatClosePct.toFixed(1)}%` : '—'}
          sub="share with positive price CLV"
        />
      </div>

      {/* CLV explainer */}
      <div className="pst-card rounded-md p-4">
        <SectionLabel>How price CLV is computed</SectionLabel>
        <p className="mt-1 text-[12.5px] text-zinc-600 leading-relaxed max-w-3xl">
          CLV = de-vigged closing fair probability − de-vigged entry fair probability, in percentage points, using
          two-way proportional de-vig at both entry and close. Positive means the recorded price was superior to the
          closing reference. Model-versus-close probability difference is a diagnostic only and is never presented as
          CLV. Excluded records are never counted as losses or zeros.
        </p>
      </div>

      {/* Exclusions histogram */}
      {histData.length > 0 && (
        <div className="pst-card rounded-md p-4">
          <SectionLabel>Reason-code histogram — nothing silently dropped</SectionLabel>
          <div className="h-44 mt-2">
            <BarChart data={histData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} width={640} height={160}>
              <CartesianGrid stroke="#e4e4e7" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#71717a' }} interval={0} angle={-18} dy={8} height={36} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: '#71717a' }} width={24} />
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {histData.map((_, i) => (
                  <Cell key={i} fill="#a16207" fillOpacity={0.75} />
                ))}
              </Bar>
            </BarChart>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
            {report.exclusions.map((e) => (
              <span key={e.reason} className="text-[11.5px] text-zinc-500 pst-num">
                {e.reason} ×{e.count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Calibration */}
      {report.calibration && report.calibration.nWithModelProbability > 0 && (
        <div className="pst-card rounded-md p-4">
          <SectionLabel>Model calibration (entries with calibrated model probabilities)</SectionLabel>
          <div className="mt-1 text-[12.5px] text-zinc-700">
            <span className="pst-num">Brier score {report.calibration.brierScore ?? '—'}</span>
            <span className="text-zinc-400"> · n = {report.calibration.nWithModelProbability}</span>
          </div>
          {report.calibration.deciles.length > 0 && (
            <table className="w-full text-[12px] mt-2">
              <thead>
                <tr className="text-left pst-label border-b border-zinc-200">
                  <th className="py-1 font-medium">Predicted band</th>
                  <th className="py-1 font-medium">n</th>
                  <th className="py-1 font-medium">Mean predicted</th>
                  <th className="py-1 font-medium">Observed</th>
                </tr>
              </thead>
              <tbody>
                {report.calibration.deciles.map((d) => (
                  <tr key={d.bucket} className="border-b border-zinc-100 last:border-b-0 pst-num">
                    <td className="py-1">{d.bucket}</td>
                    <td className="py-1">{d.n}</td>
                    <td className="py-1">{(d.predicted * 100).toFixed(1)}%</td>
                    <td className="py-1">{(d.observed * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Slices */}
      <div className="pst-card rounded-md p-4">
        <SectionLabel>Performance by sport, market, odds band, model version, and entry source</SectionLabel>
        <div className="max-h-72 overflow-y-auto mt-2">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 bg-white/95 backdrop-blur-sm">
              <tr className="text-left pst-label border-b border-zinc-200">
                <th className="py-1.5 font-medium">Dimension</th>
                <th className="py-1.5 font-medium">Group</th>
                <th className="py-1.5 font-medium">n</th>
                <th className="py-1.5 font-medium">Mean CLV</th>
                <th className="py-1.5 font-medium">Shrunk</th>
                <th className="py-1.5 font-medium">Beating close</th>
              </tr>
            </thead>
            <tbody>
              {report.slices.map((s, i) => (
                <tr key={`${s.dimension}-${s.value}`} className={cn('border-b border-zinc-100 last:border-b-0 pst-num', s.belowMinSample && 'text-amber-800')}>
                  <td className="py-1.5 font-sans">{s.dimension}</td>
                  <td className="py-1.5 font-sans">{s.value}</td>
                  <td className="py-1.5">{s.n}</td>
                  <td className="py-1.5">{fmtPp(s.meanClvPp)}</td>
                  <td className="py-1.5">{fmtPp(s.shrunkClvPp)}</td>
                  <td className="py-1.5">{s.beatClosePct !== null ? `${s.beatClosePct.toFixed(0)}%` : '—'}</td>
                </tr>
              ))}
              {report.slices.some((s) => s.belowMinSample) && (
                <tr>
                  <td colSpan={6} className="py-2 text-[11.5px] text-amber-800 font-sans">
                    Amber rows are below the minimum sample of {report.minSampleThreshold}: not enough evaluable entries
                    to draw a conclusion.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="pst-card rounded-md p-4">
      <SectionLabel>{label}</SectionLabel>
      <div className="pst-num text-xl font-semibold text-zinc-900 mt-1">{value}</div>
      {sub && <div className="text-[11.5px] text-zinc-400 mt-0.5">{sub}</div>}
    </div>
  );
}
