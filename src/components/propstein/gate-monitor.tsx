'use client';

/**
 * PropStein — Gate Monitor view.
 *
 * Displays the preregistered commercialization gate per sport: parameters,
 * progress, attempt history with exact verdicts, compliance approval state,
 * and the commercial actionable-signal flag (default deny). Includes the
 * deterministic recompute control (fixed seed 20261024).
 */

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useToast } from '@/hooks/use-toast';
import { Note, SectionLabel, fmtEt, fmtPp } from './shared';
import { cn } from '@/lib/utils';

interface GateStatus {
  sport: string;
  preregistered: {
    nConfirm: number;
    nInterim: number;
    meanClvMinPp: number;
    alphaOneSided: number;
    bootstrapReplicates: number;
    seed: number;
    maxAttempts: number;
    minClusters: number;
  };
  nSignalsStored: number;
  nEvaluable: number;
  distinctClusters: number;
  attempts: {
    attemptNo: number;
    nEvaluable: number;
    distinctClusters: number;
    meanClvPp: number;
    bootstrapLbPp: number;
    verdict: string;
    notes: string[];
    evaluatedAtUtc: string;
  }[];
  compliance: { status: string; approver: string; recordedAtUtc: string; note: string } | null;
  commercial: { gatePassed: boolean; retired: boolean; commercialSignalEnabled: boolean; explanation: string };
}

const VERDICT_STYLES: Record<string, string> = {
  PASS: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  FAIL: 'border-amber-900/40 bg-amber-900/5 text-amber-300',
  IN_PROGRESS: 'border-zinc-500/40 bg-[#0D0F16]0/5 text-zinc-300',
  INTERIM: 'border-zinc-500/40 bg-[#0D0F16]0/5 text-zinc-300',
  INCONCLUSIVE: 'border-amber-500/30 bg-amber-500/10 text-amber-300/90',
  PENDING: 'border-zinc-400/40 bg-white/[0.04] text-zinc-500',
  RETIRED: 'border-zinc-700/50 bg-white/[0.08] text-zinc-100',
};

export function GateMonitor() {
  const { toast } = useToast();
  const [statuses, setStatuses] = useState<GateStatus[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await fetch('/api/gates');
    const json = await res.json();
    if (json.ok) setStatuses(json.statuses);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const recompute = useCallback(
    async (sport: string) => {
      setBusy(sport);
      try {
        const res = await fetch('/api/gates/recompute', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sport, attemptNo: 1 }),
        });
        const json = await res.json();
        if (json.ok) {
          toast({
            title: `${sport} attempt 1 recomputed`,
            description: `Verdict ${json.recomputed.verdict} · mean ${fmtPp(json.recomputed.meanClvPp)} · lower bound ${fmtPp(json.recomputed.bootstrapLbPp)} · ${
              json.matchesStored ? 'matches the stored record exactly (seed 20261024).' : 'DIFFERS from stored record — investigate.'
            }`,
          });
        }
      } finally {
        setBusy(null);
      }
    },
    [toast],
  );

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Preregistered gate monitor</h2>
        <p className="mt-0.5 text-[12.5px] text-zinc-500 max-w-2xl">
          One evaluation per sport. A commercial actionable-signal surface may launch for a sport only after the
          preregistered gate records a passing verdict AND an explicit compliance approval record exists. Default is
          deny. Cross-sport pooling is forbidden: evidence for one sport never authorizes claims about another.
        </p>
      </div>

      {statuses.map((g) => {
        const progress = Math.min(100, (g.nEvaluable / g.preregistered.nConfirm) * 100);
        const currentVerdict = g.commercial.retired
          ? 'RETIRED'
          : g.attempts.length > 0
            ? g.attempts[g.attempts.length - 1].verdict
            : 'PENDING';
        return (
          <div key={g.sport} className="pst-card rounded-md p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-[15px] font-semibold text-zinc-100">{g.sport}</h3>
                <div className="text-[12px] text-zinc-500 pst-num mt-0.5">
                  attempt {g.currentAttempt} progress: {g.nEvaluable} evaluable qualifying signals of{' '}
                  {g.preregistered.nConfirm} · {g.distinctClusters} distinct game clusters (floor{' '}
                  {g.preregistered.minClusters}) · {g.nSignalsStored} signals stored across attempts
                </div>
              </div>
              <span
                className={cn('inline-flex items-center rounded-sm border px-2.5 py-0.5 text-xs font-semibold tracking-wide', VERDICT_STYLES[currentVerdict] ?? VERDICT_STYLES.PENDING)}
                role="status"
                aria-label={`${g.sport} gate status: ${currentVerdict}`}
              >
                {currentVerdict === 'PASS' || currentVerdict === 'FAIL' ? `GATE ${currentVerdict}` : currentVerdict}
              </span>
            </div>

            {/* progress */}
            <div className="mt-3">
              <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} aria-label={`${g.sport} gate progress`}>
                <div className={cn('h-full rounded-full', progress >= 100 ? 'bg-emerald-500/70' : 'bg-indigo-500/60')} style={{ width: `${progress}%` }} />
              </div>
              <div className="flex justify-between mt-1 text-[11px] text-zinc-400 pst-num">
                <span>0</span>
                <span>interim {g.preregistered.nInterim} (descriptive only)</span>
                <span>confirmatory {g.preregistered.nConfirm}</span>
              </div>
            </div>

            {/* attempts */}
            <div className="mt-3">
              <SectionLabel>Attempt history (max {g.preregistered.maxAttempts} prospective attempts)</SectionLabel>
              {g.attempts.length === 0 ? (
                <p className="text-[12.5px] text-zinc-500 mt-1">No attempts recorded yet.</p>
              ) : (
                <div className="mt-1 space-y-2">
                  {g.attempts.map((a) => (
                    <div key={a.attemptNo} className="border-l-2 border-white/[0.07] pl-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cn('inline-flex items-center rounded-sm border px-2 py-0.5 text-[11px] font-semibold', VERDICT_STYLES[a.verdict] ?? VERDICT_STYLES.PENDING)}>
                          {a.verdict}
                        </span>
                        <span className="pst-num text-[12px] text-zinc-300">
                          attempt {a.attemptNo} · N={a.nEvaluable} · clusters={a.distinctClusters} · mean {fmtPp(a.meanClvPp)} ·
                          one-sided lower bound {fmtPp(a.bootstrapLbPp)}
                        </span>
                      </div>
                      <div className="text-[11px] text-zinc-400 pst-num">{fmtEt(a.evaluatedAtUtc)}</div>
                      {a.notes.slice(0, 3).map((n, i) => (
                        <p key={i} className="text-[11.5px] text-zinc-500 leading-snug mt-0.5">{n}</p>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* compliance + commercial flag */}
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <SectionLabel>Compliance approval</SectionLabel>
                {g.compliance ? (
                  <div className="text-[12.5px] text-zinc-300 mt-1">
                    <span className="pst-num">{g.compliance.status.toUpperCase()}</span> · {g.compliance.approver}
                    <div className="text-[11.5px] text-zinc-500">{g.compliance.note}</div>
                    <div className="text-[11px] text-zinc-400 pst-num">recorded {fmtEt(g.compliance.recordedAtUtc)}</div>
                  </div>
                ) : (
                  <Note tone="warn">No compliance approval record. Default is deny.</Note>
                )}
              </div>
              <div>
                <SectionLabel>Commercial actionable-signal flag</SectionLabel>
                <div
                  className={cn(
                    'mt-1 inline-flex items-center rounded-sm border px-2.5 py-0.5 text-xs font-semibold tracking-wide',
                    g.commercial.commercialSignalEnabled ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-zinc-700/50 bg-white/[0.08] text-zinc-100',
                  )}
                  role="status"
                >
                  {g.commercial.commercialSignalEnabled ? 'ENABLED' : 'DENIED'}
                </div>
                <p className="text-[12px] text-zinc-400 mt-1 leading-snug">{g.commercial.explanation}</p>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-white/[0.07] pt-3">
              <Button variant="outline" size="sm" disabled={busy === g.sport} onClick={() => recompute(g.sport)}>
                {busy === g.sport ? 'Recomputing…' : 'Recompute from stored signals (deterministic)'}
              </Button>
              <Note>
                Preregistered parameters: N={g.preregistered.nConfirm}, threshold +{g.preregistered.meanClvMinPp.toFixed(1)} pp,
                one-sided α={g.preregistered.alphaOneSided}, {g.preregistered.bootstrapReplicates.toLocaleString()} replicates,
                seed {g.preregistered.seed}. Interim look at N={g.preregistered.nInterim} is descriptive only and never a
                verdict.
              </Note>
            </div>
          </div>
        );
      })}
    </div>
  );
}
